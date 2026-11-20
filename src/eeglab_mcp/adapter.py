"""MATLAB process adapter.

One MATLAB process per job (`matlab -batch`). This keeps every analysis
isolated, avoids shared-session state bugs, and works on MATLAB R2023a whose
Python Engine does not support Python 3.12. Multi-step work should use the
predefined `pipeline` action so MATLAB startup is paid once.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .worker import MatlabWorker, WorkerError


@dataclass
class MatlabResult:
    ok: bool
    action: str
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    stdout: str = ""
    stderr: str = ""
    wall_seconds: float = 0.0
    job_dir: Path | None = None


class MatlabAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._worker: MatlabWorker | None = None

    @property
    def worker(self) -> MatlabWorker:
        if self._worker is None:
            self._worker = MatlabWorker(self.settings)
        return self._worker

    def close(self) -> None:
        if self._worker is not None:
            self._worker.stop()

    # ------------------------------------------------------------------
    def run(
        self,
        action: str,
        *,
        input: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        job_id: str | None = None,
        output_dir: Path | None = None,
    ) -> MatlabResult:
        job_id = job_id or uuid.uuid4().hex[:12]
        out_root = self.settings.paths.output_root
        job_dir = (output_dir or (out_root / "jobs" / job_id))
        job_dir.mkdir(parents=True, exist_ok=True)

        job = {
            "action": action,
            "job_id": job_id,
            "eeglab_root": str(self.settings.eeglab.root).replace("\\", "/"),
            "input": input or {},
            "params": params or {},
            "output_dir": str(job_dir).replace("\\", "/"),
        }
        job_file = job_dir / "job.json"
        result_file = job_dir / "matlab_result.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        if result_file.exists():
            result_file.unlink()

        driver = self.settings.matlab.driver_dir
        cmd = (
            f"addpath('{_q(driver)}'); "
            f"run_job('{_q(job_file)}','{_q(result_file)}');"
        )

        # ---- fast path: persistent worker (no MATLAB cold start) ----
        if self.settings.matlab.use_persistent_worker:
            t0 = time.perf_counter()
            try:
                payload = self.worker.run(job, self.settings.matlab.timeout_seconds)
                wall = time.perf_counter() - t0
                (job_dir / "matlab_stdout.log").write_text(
                    "mode=persistent_worker\nwall_seconds=%.1f\n" % wall, encoding="utf-8")
                # 常驻 worker 把结果直接回传；落盘一份，get_job_status 才能事后复读
                (job_dir / "matlab_result.json").write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                return self._payload_to_result(payload, action, job_id, job_dir, wall, "", "")
            except WorkerError as exc:
                # never wedge the server on a dead worker — fall back to one-shot
                (job_dir / "worker_fallback.txt").write_text(str(exc), encoding="utf-8")

        t0 = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(
                [str(self.settings.matlab.executable), "-batch", cmd],
                cwd=str(job_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.matlab.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = _decode(exc.stdout)
            stderr = _decode(exc.stderr)
            rc = -1
        wall = time.perf_counter() - t0

        (job_dir / "matlab_stdout.log").write_text(
            f"exit_code={rc}\ntimed_out={timed_out}\nwall_seconds={wall:.1f}\n"
            f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n",
            encoding="utf-8",
        )

        if timed_out:
            return MatlabResult(
                ok=False, action=action, job_dir=job_dir, stdout=stdout, stderr=stderr,
                wall_seconds=wall,
                error={
                    "code": "MATLAB_TIMEOUT",
                    "message": f"MATLAB did not finish within {self.settings.matlab.timeout_seconds}s",
                    "hint": "Reduce the data size or raise matlab.timeout_seconds in config.",
                },
                provenance=self._provenance(job_id, wall),
            )

        if not result_file.is_file():
            return MatlabResult(
                ok=False, action=action, job_dir=job_dir, stdout=stdout, stderr=stderr,
                wall_seconds=wall,
                error={
                    "code": "MATLAB_NO_RESULT",
                    "message": "MATLAB exited without writing a result file.",
                    "hint": _tail(stderr) or _tail(stdout) or "See matlab_stdout.log",
                    "exit_code": rc,
                },
                provenance=self._provenance(job_id, wall),
            )

        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return MatlabResult(
                ok=False, action=action, job_dir=job_dir, stdout=stdout, stderr=stderr,
                wall_seconds=wall,
                error={"code": "MALFORMED_RESULT", "message": str(exc)},
                provenance=self._provenance(job_id, wall),
            )

        return self._payload_to_result(payload, action, job_id, job_dir, wall, stdout, stderr)

    # ------------------------------------------------------------------
    def _payload_to_result(self, payload, action, job_id, job_dir, wall, stdout, stderr) -> MatlabResult:
        # EE 结果为空字符串时 matlab 的 jsondecode 会给出 []，这里做归一化
        w = payload.get("warnings") or []
        if isinstance(w, str):
            w = [w]
        a = payload.get("artifacts") or []
        if isinstance(a, dict):
            a = [a]
        return MatlabResult(
            ok=bool(payload.get("ok")),
            action=payload.get("action", action),
            data=payload.get("data") or {},
            warnings=list(w),
            artifacts=list(a),
            log=list(payload.get("log") or []),
            provenance=payload.get("provenance") or self._provenance(job_id, wall),
            error=payload.get("error"),
            stdout=stdout,
            stderr=stderr,
            wall_seconds=wall,
            job_dir=job_dir,
        )

    # ------------------------------------------------------------------
    def _provenance(self, job_id: str, wall: float) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "matlab_executable": str(self.settings.matlab.executable),
            "eeglab_root": str(self.settings.eeglab.root),
            "wall_seconds": round(wall, 1),
        }


def _q(p: Path | str) -> str:
    """Quote a path for a MATLAB single-quoted string."""
    return str(p).replace("\\", "/").replace("'", "''")


def _decode(b) -> str:
    if b is None:
        return ""
    if isinstance(b, bytes):
        return b.decode("utf-8", "replace")
    return str(b)


def _tail(s: str, n: int = 800) -> str:
    s = (s or "").strip()
    return s[-n:] if len(s) > n else s
