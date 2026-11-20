"""The 21 MCP tools exposed by EEGLAB-MCP.

Every tool validates its own inputs in Python (fast, precise errors), runs the
method gates that apply to its action, delegates the actual computation to
MATLAB/EEGLAB, and returns the uniform envelope.  No tool accepts arbitrary
MATLAB code.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import envelope
from .adapter import MatlabAdapter, MatlabResult
from .config import Settings
from .gates import Facts, GateError, GateResult, apply_override, evaluate, merge_results
from .methodology import load_catalog
from .security import (ANALYSIS_SUFFIXES, IMPORT_SUFFIXES, SecurityError, resolve_input,
                       resolve_output_dir, require_range)

PREDEFINED_PIPELINES = ("basic_preprocess", "erp_analysis")
PLOT_KINDS = ("erp_waveform", "topomap", "psd")

# Tools that run method gates, and the action(s) each one gates.
GATED_ACTIONS = {
    "filter": "filter",
    "reref": "reref",
    "epoch": "epoch",
    "baseline": "baseline",
    "ica": "ica",
    "plot": "plot",
    "export_long": "export",
    "psd": "psd",
}


class Tools:
    def __init__(self, settings: Settings):
        self.s = settings
        self.adapter = MatlabAdapter(settings)
        self._facts_cache: dict[tuple[str, int, int], Facts] = {}

    # ------------------------------------------------------------------
    def _run(
        self,
        action: str,
        *,
        path: Path | None = None,
        params: dict | None = None,
        gate: GateResult | None = None,
    ) -> dict:
        input_obj = {"file_path": str(path)} if path else {}
        res: MatlabResult = self.adapter.run(action, input=input_obj, params=params or {})
        out = envelope.build(res)
        if gate is not None:
            out["gate"] = gate.to_dict()
            job_dir = (out.get("runtime") or {}).get("job_dir")
            if job_dir:
                try:
                    (Path(job_dir) / "gate.json").write_text(
                        json.dumps(gate.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    out.setdefault("warnings", []).append(f"gate.json could not be written: {exc}")
        return out

    @staticmethod
    def _fail(code: str, message: str, hint: str | None = None) -> dict:
        return {
            "success": False,
            "job_id": None,
            "action": None,
            "result": {},
            "warnings": [],
            "errors": [{"code": code, "message": message, "hint": hint}],
            "artifacts": [],
            "provenance": {},
            "runtime": {"wall_seconds": 0.0, "job_dir": None},
            "interpretation_limits": [],
        }

    # ------------------------------------------------------------ gates
    def _facts(self, path: Path) -> Facts:
        """Read what the file actually is (header-only load in MATLAB), with caching."""
        try:
            st = path.stat()
        except OSError as exc:
            raise GateError("GATE_FACTS_UNAVAILABLE", f"无法读取文件属性：{exc}") from exc
        key = (str(path), st.st_mtime_ns, st.st_size)
        cached = self._facts_cache.get(key)
        if cached is not None:
            return cached
        res = self.adapter.run("facts", input={"file_path": str(path)}, params={})
        if not res.ok:
            message = (res.error or {}).get("message", "MATLAB did not return facts")
            raise GateError(
                "GATE_FACTS_UNAVAILABLE",
                f"无法读取 {path.name} 的实际状态：{message}",
                "先调用 eeglab_inspect_dataset 确认文件可读",
            )
        facts = Facts.from_payload(res.data or {})
        self._facts_cache[key] = facts
        return facts

    def _gate(
        self,
        jobs: list[tuple[str, dict]],
        path: Path,
        *,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> tuple[GateResult | None, dict | None]:
        """Evaluate method gates. Returns (result, error_response)."""
        try:
            facts = self._facts(path)
            # In a multi-stage pipeline every stage sees the *output* of the
            # previous one. Gating later stages against the raw file would ask
            # "is this file epoched?" and block a pipeline that is about to
            # epoch. Project the facts forward using the pipeline's own
            # declared epoch window — not a guess about the data.
            current = facts
            epoch_window: tuple[float | None, float | None] = (None, None)
            results = []
            for i, (action, params) in enumerate(jobs):
                if action == "epoch":
                    epoch_window = (params.get("tmin_s"), params.get("tmax_s"))
                elif action == "baseline" and not current.is_epoched:
                    current = replace(
                        current,
                        is_continuous=False,
                        is_epoched=True,
                        trials=max(current.trials, 1),
                        tmin_s=epoch_window[0],
                        tmax_s=epoch_window[1],
                    )
                results.append(
                    evaluate(action, params, current, method_id=method if i == 0 else None)
                )
            merged = merge_results(jobs[0][0], results)
            return apply_override(merged, override_gate, override_reason), None
        except GateError as exc:
            return None, self._fail(exc.code, exc.message, exc.hint)

    def _gate_blocked(self, gate: GateResult) -> dict:
        data = gate.to_dict()
        advisory = [i["observed"] for i in data["items"] if i["status"] == "advisory"]
        return {
            "success": False,
            "job_id": None,
            "action": gate.action,
            "result": {},
            "warnings": advisory,
            "errors": [
                {
                    "code": "GATE_BLOCKED",
                    "message": "方法学门控未通过，操作未执行",
                    "hint": "调用 eeglab_method_preflight 查看全部检查项，或修正参数；如确需继续，使用 override_gate 并给出理由",
                }
            ],
            "artifacts": [],
            "provenance": {
                "catalog_version": gate.catalog_version,
                "method_id": gate.method_id,
            },
            "runtime": {"wall_seconds": 0.0, "job_dir": None},
            "gate": data,
            "interpretation_limits": [
                "No computation was performed: the method gates blocked this call.",
                "Overriding the gate does not make the flagged condition disappear; it only records that you accepted it.",
            ],
        }

    # ================================================================ P0
    def get_status(self) -> dict:
        """Check MATLAB, EEGLAB root and required functions. Run this first."""
        return self._run("status")

    def list_files(self, directory: str = "", pattern: str = "*.set") -> dict:
        """List EEG files under the configured allowed roots (read-only)."""
        try:
            roots = [Path(r) for r in self.s.paths.allowed_input_roots]
            if directory:
                base = Path(directory).expanduser().resolve()
                if not any(_within(base, Path(r).resolve()) or base == Path(r).resolve() for r in roots):
                    raise SecurityError("PATH_NOT_ALLOWED", f"Directory is outside allowed roots: {base}")
                roots = [base]
            found = []
            for root in roots:
                if not root.is_dir():
                    continue
                for p in sorted(root.rglob(pattern))[:500]:
                    if not p.is_file():
                        continue
                    st = p.stat()
                    found.append(
                        {
                            "path": str(p),
                            "bytes": st.st_size,
                            "modified": _ts(st.st_mtime),
                        }
                    )
            return {
                "success": True,
                "job_id": None,
                "action": "list_files",
                "result": {"count": len(found), "files": found, "roots": [str(r) for r in roots]},
                "warnings": [] if found else ["No matching files were found under the allowed roots."],
                "errors": [],
                "artifacts": [],
                "provenance": {"roots": [str(r) for r in roots]},
                "runtime": {"wall_seconds": 0.0, "job_dir": None},
                "interpretation_limits": [],
            }
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)

    def inspect_dataset(self, file_path: str) -> dict:
        """Report sampling rate, channels, duration, events and integrity."""
        try:
            p = resolve_input(file_path, self.s)
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        return self._run("inspect", path=p)

    def load_dataset(self, file_path: str) -> dict:
        """Load, validate and stage a copy in the job directory. Original is untouched."""
        try:
            p = resolve_input(file_path, self.s)
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        return self._run("stage", path=p)

    def run_pipeline(
        self,
        file_path: str,
        pipeline: str = "basic_preprocess",
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
        **params: Any,
    ) -> dict:
        """Run a predefined, validated pipeline in a single MATLAB process."""
        try:
            p = resolve_input(file_path, self.s)
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        if pipeline not in PREDEFINED_PIPELINES:
            return self._fail(
                "BAD_PARAMS",
                f"Unknown pipeline: {pipeline}",
                "Available: " + ", ".join(PREDEFINED_PIPELINES),
            )
        try:
            clean = self._validate_params(pipeline, params)
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        gate, err = self._gate(
            self._pipeline_gate_jobs(pipeline, clean), p, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        if gate.blocked:
            return self._gate_blocked(gate)
        return self._run("pipeline", path=p, params={"pipeline": pipeline, **clean}, gate=gate)

    def get_job_status(self, job_id: str) -> dict:
        """Read the recorded status, log and artifacts of a previous job."""
        job_dir = self.s.paths.output_root / "jobs" / job_id
        result_file = job_dir / "matlab_result.json"
        log_file = job_dir / "matlab_stdout.log"
        if not job_dir.is_dir():
            return self._fail("JOB_NOT_FOUND", f"No such job: {job_id}", str(self.s.paths.output_root / "jobs"))
        if not result_file.is_file():
            return self._fail("JOB_INCOMPLETE", f"Job {job_id} has no result yet", str(job_dir))
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        artifacts = []
        for a in payload.get("artifacts") or []:
            ap = Path(a.get("path", ""))
            artifacts.append(
                {
                    "path": str(ap),
                    "kind": a.get("kind"),
                    "bytes": ap.stat().st_size if ap.is_file() else 0,
                    "sha256": envelope.digest(ap),
                }
            )
        return {
            "success": bool(payload.get("ok")),
            "job_id": job_id,
            "action": payload.get("action"),
            "result": payload.get("data") or {},
            "warnings": payload.get("warnings") or [],
            "errors": [payload["error"]] if payload.get("error") else [],
            "artifacts": artifacts,
            "provenance": payload.get("provenance") or {},
            "runtime": {"wall_seconds": None, "job_dir": str(job_dir)},
            "interpretation_limits": [],
            "log_tail": _tail(log_file),
        }

    # ================================================================ P2
    def import_data(self, file_path: str) -> dict:
        """Convert EDF / BDF / CNT / BrainVision into an EEGLAB .set in the job directory."""
        try:
            p = resolve_input(file_path, self.s, suffixes=IMPORT_SUFFIXES)
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        return self._run("import", path=p)

    def batch_process(
        self,
        files: list[str],
        mode: str = "inspect",
        pipeline: str = "basic_preprocess",
        pipeline_params: dict | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Run inspect or a predefined pipeline over many files in one MATLAB process.

        A failure on one file does not abort the batch; per-file status is returned.
        """
        if not files:
            return self._fail("BAD_PARAMS", "files must not be empty")
        if mode not in ("inspect", "pipeline"):
            return self._fail("BAD_PARAMS", "mode must be 'inspect' or 'pipeline'")
        if mode == "pipeline" and pipeline not in PREDEFINED_PIPELINES:
            return self._fail(
                "BAD_PARAMS", f"Unknown pipeline: {pipeline}",
                "Available: " + ", ".join(PREDEFINED_PIPELINES),
            )
        if len(files) > self.s.limits.max_batch_files:
            return self._fail(
                "BATCH_TOO_LARGE",
                f"{len(files)} files exceeds the limit of {self.s.limits.max_batch_files}",
            )
        resolved: list[str] = []
        for f in files:
            try:
                resolved.append(str(resolve_input(f, self.s)))
            except SecurityError as e:
                return self._fail(e.code, f"{f}: {e.message}", e.hint)

        params: dict[str, Any] = {"files": resolved, "mode": mode}
        gate = None
        if mode == "pipeline":
            try:
                params["pipeline"] = pipeline
                params["pipeline_params"] = self._validate_params(pipeline, pipeline_params or {})
            except SecurityError as e:
                return self._fail(e.code, e.message, e.hint)
            gate, err = self._gate(
                self._pipeline_gate_jobs(pipeline, params["pipeline_params"]),
                Path(resolved[0]),
                override_gate=override_gate, override_reason=override_reason,
            )
            if err:
                return err
            if gate.blocked:
                return self._gate_blocked(gate)
        out = self._run("batch", params=params, gate=gate)
        if gate is not None:
            out.setdefault("warnings", []).append(
                "Method gates were evaluated on the first file only; "
                "the remaining files are processed with the same pipeline."
            )
        return out

    # ================================================================ P1
    def filter_data(
        self,
        file_path: str,
        highpass_hz: float | None = None,
        lowpass_hz: float | None = None,
        notch_hz: float | None = None,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Band-pass / high-pass / low-pass / notch filter with zero-phase FIR."""
        try:
            p = resolve_input(file_path, self.s)
            params: dict[str, Any] = {}
            if highpass_hz is not None:
                params["highpass_hz"] = require_range("highpass_hz", highpass_hz, 0.01, 500, " Hz")
            if lowpass_hz is not None:
                params["lowpass_hz"] = require_range("lowpass_hz", lowpass_hz, 0.02, 5000, " Hz")
            if notch_hz is not None:
                params["notch_hz"] = require_range("notch_hz", notch_hz, 1, 5000, " Hz")
            if not params:
                raise SecurityError("BAD_PARAMS", "Supply at least one of highpass_hz, lowpass_hz, notch_hz")
            if "highpass_hz" in params and "lowpass_hz" in params and params["highpass_hz"] >= params["lowpass_hz"]:
                raise SecurityError("BAD_PARAMS", "highpass_hz must be lower than lowpass_hz")
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        gate, err = self._gate(
            [("filter", params)], p, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        if gate.blocked:
            return self._gate_blocked(gate)
        return self._run("filter", path=p, params=params, gate=gate)

    def rereference(
        self,
        file_path: str,
        method: str = "average",
        channels: list[str] | None = None,
        method_profile: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Average reference or reference to explicit channel(s)."""
        try:
            p = resolve_input(file_path, self.s)
            if method not in ("average", "channels"):
                raise SecurityError("BAD_PARAMS", "method must be 'average' or 'channels'")
            if method == "channels" and not channels:
                raise SecurityError("BAD_PARAMS", "method='channels' requires a non-empty channels list")
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        gate, err = self._gate(
            [("reref", {"method": method, "channels": channels or []})], p, method=method_profile,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        if gate.blocked:
            return self._gate_blocked(gate)
        return self._run("reref", path=p,
                         params={"method": method, "channels": channels or []}, gate=gate)

    def epoch_data(
        self,
        file_path: str,
        event_types: list[str],
        tmin_s: float = -0.2,
        tmax_s: float = 0.8,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Segment continuous data around event codes."""
        try:
            p = resolve_input(file_path, self.s)
            if not event_types:
                raise SecurityError("BAD_PARAMS", "event_types must not be empty")
            tmin_s, tmax_s = self._check_window(tmin_s, tmax_s)
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        params = {"event_types": event_types, "tmin_s": tmin_s, "tmax_s": tmax_s}
        gate, err = self._gate(
            [("epoch", params)], p, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        if gate.blocked:
            return self._gate_blocked(gate)
        return self._run("epoch", path=p, params=params, gate=gate)

    def baseline_correct(
        self,
        file_path: str,
        baseline_start_s: float = -0.2,
        baseline_end_s: float = 0.0,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Subtract the mean of a baseline window from epoched data."""
        try:
            p = resolve_input(file_path, self.s)
            if baseline_start_s >= baseline_end_s:
                raise SecurityError("BAD_PARAMS", "baseline_start_s must be lower than baseline_end_s")
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        params = {"baseline_start_s": baseline_start_s, "baseline_end_s": baseline_end_s}
        gate, err = self._gate(
            [("baseline", params)], p, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        if gate.blocked:
            return self._gate_blocked(gate)
        return self._run("baseline", path=p, params=params, gate=gate)

    def run_ica(
        self,
        file_path: str,
        algorithm: str = "runica",
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Run ICA and save weights. Never auto-rejects components."""
        try:
            p = resolve_input(file_path, self.s)
            if algorithm not in ("runica", "pca"):
                raise SecurityError("BAD_PARAMS", "algorithm must be 'runica' or 'pca'")
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        params = {"algorithm": algorithm}
        gate, err = self._gate(
            [("ica", params)], p, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        if gate.blocked:
            return self._gate_blocked(gate)
        return self._run("ica", path=p, params=params, gate=gate)

    def compute_erp(self, file_path: str, channel: str = "") -> dict:
        """Average epochs into an ERP and export the full channel × time matrix."""
        try:
            p = resolve_input(file_path, self.s)
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        return self._run("erp", path=p, params={"channel": channel})

    def compute_psd(
        self,
        file_path: str,
        fmax_hz: float | None = None,
        fmin_hz: float | None = None,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Estimate a Welch power spectrum and standard band powers."""
        params: dict[str, Any] = {}
        try:
            p = resolve_input(file_path, self.s)
            if fmax_hz is not None:
                params["fmax_hz"] = require_range("fmax_hz", fmax_hz, 0.5, 5000.0, " Hz")
            if fmin_hz is not None:
                params["fmin_hz"] = require_range("fmin_hz", fmin_hz, 0.0, 5000.0, " Hz")
            if "fmin_hz" in params and "fmax_hz" in params:
                if params["fmin_hz"] >= params["fmax_hz"]:
                    raise SecurityError("BAD_PARAMS", "fmin_hz must be lower than fmax_hz")
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        gate, err = self._gate(
            [("psd", params)], p, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        if gate.blocked:
            return self._gate_blocked(gate)
        out = self._run("psd", path=p, params=params, gate=gate)
        advisory = [
            item["observed"]
            for item in gate.to_dict()["items"]
            if item["status"] == "advisory"
        ]
        out.setdefault("warnings", []).extend(advisory)
        return out

    def plot_results(
        self,
        file_path: str,
        kind: str = "erp_waveform",
        time_s: float = 0.3,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Render an ERP waveform, scalp topography, or PSD figure to PNG."""
        try:
            p = resolve_input(file_path, self.s)
            if kind not in PLOT_KINDS:
                raise SecurityError("BAD_PARAMS", f"kind must be one of {PLOT_KINDS}")
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        params = {"kind": kind, "time_s": time_s}
        gate, err = self._gate(
            [("plot", params)], p, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        if gate.blocked:
            return self._gate_blocked(gate)
        return self._run("plot", path=p, params=params, gate=gate)

    def qc_report(self, file_path: str) -> dict:
        """Compute amplitude, flat-channel, outlier-channel and event quality metrics."""
        try:
            p = resolve_input(file_path, self.s)
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        return self._run("qc", path=p)

    def export_long_table(
        self,
        file_path: str,
        window_start_s: float | None = None,
        window_end_s: float | None = None,
        subject_id: str = "",
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Export epoched data as a long-format table (subject, condition, channel, mean_uv).

        The schema matches the MNE-MCP / Pingouin-MCP hand-off convention, so the
        output can be fed directly into statistical tools.
        """
        try:
            p = resolve_input(file_path, self.s)
            params: dict[str, Any] = {"subject_id": subject_id}
            if window_start_s is not None:
                params["window_start_s"] = float(window_start_s)
            if window_end_s is not None:
                params["window_end_s"] = float(window_end_s)
            if "window_start_s" in params and "window_end_s" in params:
                if params["window_start_s"] >= params["window_end_s"]:
                    raise SecurityError("BAD_PARAMS", "window_start_s must be lower than window_end_s")
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)

        has_window = "window_start_s" in params and "window_end_s" in params
        gate_params = {
            "format": "long",
            "aggregate": "window_mean" if has_window else "none",
            "window_declared": has_window,
        }
        gate, err = self._gate(
            [("export", gate_params)], p, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        if gate.blocked:
            return self._gate_blocked(gate)
        return self._run("export_long", path=p, params=params, gate=gate)

    # ================================================================ methodology
    def method_catalog(self, stage: str = "") -> dict:
        """List the method profiles (id, parameters, gates) in the knowledge base."""
        catalog = load_catalog()
        profiles = [
            p.to_dict() for p in sorted(catalog.profiles.values(), key=lambda x: x.id)
            if not stage or p.stage == stage
        ]
        if stage and not profiles:
            return self._fail(
                "BAD_PARAMS", f"No method profile for stage: {stage}",
                "Available stages: " + ", ".join(sorted({p.stage for p in catalog.profiles.values()})),
            )
        summary = catalog.summary()
        return self._static("method_catalog", {
            "catalog_version": summary["catalog_version"],
            "eeglab_baseline": summary["eeglab_baseline"],
            "claim_count": summary["claims"],
            "profile_count": summary["profiles"],
            "profiles_by_action": summary["profiles_by_action"],
            "profiles": profiles,
        })

    def official_claims(self, topic: str = "") -> dict:
        """List the official statements the gates cite, with source locators."""
        catalog = load_catalog()
        topics = {t.upper(): t for t in catalog.topics}
        wanted = topic.upper()
        if wanted and wanted not in topics:
            return self._fail(
                "BAD_PARAMS", f"Unknown topic: {topic}",
                "Available topics: " + ", ".join(sorted(catalog.topics)),
            )
        claims = [
            c.to_dict() for c in sorted(catalog.claims.values(), key=lambda x: x.id)
            if not wanted or c.topic == wanted
        ]
        return self._static("official_claims", {
            "catalog_version": catalog.version,
            "topics": catalog.topics,
            "count": len(claims),
            "claims": claims,
        })

    def method_preflight(
        self,
        file_path: str,
        action: str,
        params: dict | None = None,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Run the gates for an action without executing it (dry run)."""
        try:
            p = resolve_input(file_path, self.s)
            if action not in GATED_ACTIONS:
                raise SecurityError(
                    "BAD_PARAMS", f"Action has no method gates: {action}",
                    "Gated actions: " + ", ".join(sorted(GATED_ACTIONS)),
                )
        except SecurityError as e:
            return self._fail(e.code, e.message, e.hint)
        gate_action = GATED_ACTIONS[action]
        gate, err = self._gate(
            [(gate_action, dict(params or {}))], p, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )
        if err:
            return err
        data = gate.to_dict()
        out = self._static("method_preflight", {
            "file": str(p),
            "gated_action": gate_action,
            "gate_passed": not gate.blocked,
            **data,
        })
        out["provenance"] = {
            "catalog_version": gate.catalog_version,
            "method_id": gate.method_id,
        }
        out["interpretation_limits"] = [
            "A preflight only reads the file header and applies the knowledge base; "
            "it does not execute the analysis.",
            "Passing the gates does not make the analysis appropriate for your question.",
        ]
        return out

    def _static(self, action: str, result: dict) -> dict:
        return {
            "success": True,
            "job_id": None,
            "action": action,
            "result": result,
            "warnings": [],
            "errors": [],
            "artifacts": [],
            "provenance": {},
            "runtime": {"wall_seconds": 0.0, "job_dir": None},
            "interpretation_limits": [],
        }

    # ------------------------------------------------------------------
    def _pipeline_gate_jobs(self, pipeline: str, params: dict) -> list[tuple[str, dict]]:
        """Map a predefined pipeline onto the stages whose gates apply."""
        hp = params.get("highpass_hz", 1)
        filter_params: dict[str, Any] = {"highpass_hz": hp}
        if "lowpass_hz" in params:
            filter_params["lowpass_hz"] = params["lowpass_hz"]
        jobs: list[tuple[str, dict]] = [("filter", filter_params)]
        if pipeline == "erp_analysis":
            jobs.append(("epoch", {
                "event_types": params.get("event_types", []),
                "tmin_s": params.get("tmin_s", -0.2),
                "tmax_s": params.get("tmax_s", 0.8),
            }))
            jobs.append(("baseline", {
                "baseline_start_s": params.get("baseline_start_s", params.get("tmin_s", -0.2)),
                "baseline_end_s": params.get("baseline_end_s", 0.0),
            }))
        return jobs

    # ------------------------------------------------------------------
    def _check_window(self, tmin_s: float, tmax_s: float) -> tuple[float, float]:
        span = float(tmax_s) - float(tmin_s)
        sc = self.s.science
        if span <= 0:
            raise SecurityError("BAD_PARAMS", "tmax_s must be greater than tmin_s")
        if not (sc.min_epoch_span_s <= span <= sc.max_epoch_span_s):
            raise SecurityError(
                "BAD_PARAMS",
                f"Epoch span {span:.3f}s is outside [{sc.min_epoch_span_s}, {sc.max_epoch_span_s}]s",
            )
        return float(tmin_s), float(tmax_s)

    def _validate_params(self, pipeline: str, params: dict) -> dict:
        clean = {k: v for k, v in params.items() if v is not None}
        if "highpass_hz" in clean:
            clean["highpass_hz"] = require_range("highpass_hz", clean["highpass_hz"], 0.01, 500, " Hz")
        if "lowpass_hz" in clean:
            clean["lowpass_hz"] = require_range("lowpass_hz", clean["lowpass_hz"], 0.02, 5000, " Hz")
        if "tmin_s" in clean and "tmax_s" in clean:
            a, b = self._check_window(clean["tmin_s"], clean["tmax_s"])
            clean["tmin_s"], clean["tmax_s"] = a, b
        return clean


# ---------------------------------------------------------------- helpers
def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _ts(epoch: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def _tail(path: Path, n: int = 3000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-n:]
