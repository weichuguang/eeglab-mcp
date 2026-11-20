"""EEGLAB-MCP server entry point (MCP Python SDK 2.x / MCPServer)."""
from __future__ import annotations

import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from .config import ConfigError, load_settings
from .tools import Tools

INSTRUCTIONS = """EEGLAB-MCP drives a real MATLAB/EEGLAB installation.

Rules the caller must respect:
1. Always call `eeglab_get_status` first and report what it actually returns.
2. `success=true` only means the computation completed. It does NOT mean the
   scientific conclusion is valid. Read `warnings` and `interpretation_limits`.
3. Never present an unimplemented capability as working. If a tool returns an
   error, report the error code and message verbatim.
4. Epoching and ERP require matching event codes; inspect the dataset first.
5. Multi-step analyses should use `eeglab_run_pipeline` so MATLAB starts once.
6. ICA components are never rejected automatically — rejection requires explicit
   criteria and human confirmation.
7. Gated actions run method gates before any computation. If a call returns
   GATE_BLOCKED, nothing was computed: report the blocked checks, the claim each
   cites and the remedy. Do not silently retry with an override.
8. Override only when the user explicitly asks to proceed despite a blocked
   check, and always with a specific `override_reason` (20+ characters). The
   reason is recorded in the job directory; it is not a way to skip the gate.
9. Use `eeglab_method_preflight` to see what will be checked before running an
   analysis, and `eeglab_method_catalog` / `eeglab_official_claims` to explain
   why a check exists.
"""


def build_server() -> MCPServer:
    settings = load_settings()
    api = Tools(settings)
    srv = MCPServer(
        name="eeglab-mcp",
        title="EEGLAB-MCP — Professional EEG analysis over MCP",
        version="1.2.0",
        instructions=INSTRUCTIONS,
    )

    # ------------------------------------------------------------ P0
    @srv.tool()
    def eeglab_get_status() -> dict:
        """Check MATLAB, the EEGLAB root and the required functions. Run this first."""
        return api.get_status()

    @srv.tool()
    def eeglab_list_files(directory: str = "", pattern: str = "*.set") -> dict:
        """List EEG .set files under the configured allowed input roots."""
        return api.list_files(directory, pattern)

    @srv.tool()
    def eeglab_inspect_dataset(file_path: str) -> dict:
        """Report sampling rate, channels, duration, events, data size and integrity.

        Args:
            file_path: Absolute path to an EEGLAB .set file inside an allowed root.
        """
        return api.inspect_dataset(file_path)

    @srv.tool()
    def eeglab_load_dataset(file_path: str) -> dict:
        """Load, validate and stage a copy in the job directory. The original file is never modified."""
        return api.load_dataset(file_path)

    @srv.tool()
    def eeglab_run_pipeline(
        file_path: str,
        pipeline: str = "basic_preprocess",
        highpass_hz: float | None = None,
        lowpass_hz: float | None = None,
        event_types: list[str] | None = None,
        tmin_s: float | None = None,
        tmax_s: float | None = None,
        baseline_start_s: float | None = None,
        baseline_end_s: float | None = None,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Run a predefined, validated pipeline in a single MATLAB process.

        Method gates for each stage of the pipeline run first.

        Args:
            file_path: Absolute path to a .set file.
            pipeline: 'basic_preprocess' (filter + average reference) or
                'erp_analysis' (filter + reference + epoch + baseline + ERP summary).
            highpass_hz: High-pass cutoff in Hz.
            lowpass_hz: Low-pass cutoff in Hz (must be below Nyquist).
            event_types: Event codes to epoch on (required for erp_analysis).
            tmin_s: Epoch start in seconds.
            tmax_s: Epoch end in seconds.
            baseline_start_s: Baseline window start in seconds.
            baseline_end_s: Baseline window end in seconds.
            method: Optional method profile id from `eeglab_method_catalog`.
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        params: dict[str, Any] = {
            "highpass_hz": highpass_hz,
            "lowpass_hz": lowpass_hz,
            "event_types": event_types,
            "tmin_s": tmin_s,
            "tmax_s": tmax_s,
            "baseline_start_s": baseline_start_s,
            "baseline_end_s": baseline_end_s,
        }
        return api.run_pipeline(
            file_path, pipeline, method=method,
            override_gate=override_gate, override_reason=override_reason, **params,
        )

    @srv.tool()
    def eeglab_get_job_status(job_id: str) -> dict:
        """Read the recorded status, MATLAB log and artifacts of a previous job."""
        return api.get_job_status(job_id)

    @srv.tool()
    def eeglab_import_data(file_path: str) -> dict:
        """Convert an EDF, BDF, CNT or BrainVision dataset into an EEGLAB .set.

        Args:
            file_path: Absolute path to .edf, .bdf, .cnt or .vhdr inside an allowed root.
                BrainVision requires the companion .eeg and .vmrk files.
        """
        return api.import_data(file_path)

    @srv.tool()
    def eeglab_batch_process(
        files: list[str],
        mode: str = "inspect",
        pipeline: str = "basic_preprocess",
        pipeline_params: dict | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Process many .set files in one MATLAB process; one failure does not stop the batch.

        In pipeline mode the method gates are evaluated on the first file.

        Args:
            files: Absolute .set paths (all must be inside allowed roots).
            mode: 'inspect' (metadata only) or 'pipeline'.
            pipeline: Pipeline name when mode='pipeline'.
            pipeline_params: Optional pipeline parameters, e.g. {"event_types": ["square"]}.
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        return api.batch_process(
            files, mode, pipeline, pipeline_params,
            override_gate=override_gate, override_reason=override_reason,
        )

    @srv.tool()
    def eeglab_export_long_table(
        file_path: str,
        window_start_s: float | None = None,
        window_end_s: float | None = None,
        subject_id: str = "",
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Export epoched data as a long-format table for MNE-MCP / Pingouin-MCP.

        Columns: subject, condition, channel, mean_uv, trial — one row per observation.

        Args:
            file_path: Absolute path to an epoched .set file.
            window_start_s: Measurement window start in seconds (defaults to epoch start).
            window_end_s: Measurement window end in seconds (defaults to epoch end).
            subject_id: Subject identifier; defaults to the file stem.
            method: Optional method profile id from `eeglab_method_catalog`.
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        return api.export_long_table(
            file_path, window_start_s, window_end_s, subject_id,
            method=method, override_gate=override_gate, override_reason=override_reason,
        )

    # ------------------------------------------------------------ P1
    @srv.tool()
    def eeglab_filter_data(
        file_path: str,
        highpass_hz: float | None = None,
        lowpass_hz: float | None = None,
        notch_hz: float | None = None,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Apply zero-phase FIR high-pass, low-pass, band-pass and/or notch filtering.

        Args:
            file_path: Absolute path to a .set file.
            highpass_hz: High-pass cutoff in Hz.
            lowpass_hz: Low-pass cutoff in Hz (validated against Nyquist and method gates).
            notch_hz: Line-noise frequency to remove, e.g. 50 or 60.
            method: Optional method profile id, e.g. 'M-FILT-ERP-01'.
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        return api.filter_data(
            file_path, highpass_hz, lowpass_hz, notch_hz,
            method=method, override_gate=override_gate, override_reason=override_reason,
        )

    @srv.tool()
    def eeglab_rereference(
        file_path: str,
        method: str = "average",
        channels: list[str] | None = None,
        method_profile: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Re-reference to the average or to explicit channel(s).

        Args:
            file_path: Absolute path to a .set file.
            method: 'average' or 'channels'.
            channels: Channel labels when method='channels'.
            method_profile: Optional method profile id, e.g. 'M-REF-MAST-01'.
                (Named separately because `method` is the rereference mode.)
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        return api.rereference(
            file_path, method, channels, method_profile=method_profile,
            override_gate=override_gate, override_reason=override_reason,
        )

    @srv.tool()
    def eeglab_epoch_data(
        file_path: str,
        event_types: list[str],
        tmin_s: float = -0.2,
        tmax_s: float = 0.8,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Segment continuous data around event codes.

        Args:
            file_path: Absolute path to a continuous .set file.
            event_types: Event codes to epoch on, e.g. ['square'].
            tmin_s: Epoch start relative to the event, in seconds.
            tmax_s: Epoch end relative to the event, in seconds.
            method: Optional method profile id, e.g. 'M-EPOCH-STIM-01'.
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        return api.epoch_data(
            file_path, event_types, tmin_s, tmax_s,
            method=method, override_gate=override_gate, override_reason=override_reason,
        )

    @srv.tool()
    def eeglab_baseline_correct(
        file_path: str,
        baseline_start_s: float = -0.2,
        baseline_end_s: float = 0.0,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Subtract the mean of a baseline window from epoched data.

        Args:
            file_path: Absolute path to an epoched .set file.
            baseline_start_s: Baseline window start in seconds (must be <= 0).
            baseline_end_s: Baseline window end in seconds.
            method: Optional method profile id, e.g. 'M-BASE-PRE-01'.
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        return api.baseline_correct(
            file_path, baseline_start_s, baseline_end_s,
            method=method, override_gate=override_gate, override_reason=override_reason,
        )

    @srv.tool()
    def eeglab_run_ica(
        file_path: str,
        algorithm: str = "runica",
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Run ICA and save the unmixing weights. Components are never auto-rejected.

        Args:
            file_path: Absolute path to a .set file.
            algorithm: 'runica' (extended Infomax) or 'pca'.
            method: Optional method profile id, e.g. 'M-ICA-RUNICA-01'.
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        return api.run_ica(
            file_path, algorithm,
            method=method, override_gate=override_gate, override_reason=override_reason,
        )

    @srv.tool()
    def eeglab_compute_erp(file_path: str, channel: str = "") -> dict:
        """Average epoched data into an ERP; exports the full channel × time matrix as CSV.

        Args:
            file_path: Absolute path to an epoched .set file (trials >= 2).
            channel: Channel label for the returned waveform (defaults to the first channel).
        """
        return api.compute_erp(file_path, channel)

    @srv.tool()
    def eeglab_compute_psd(
        file_path: str,
        fmax_hz: float | None = None,
        fmin_hz: float | None = None,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Estimate a Welch power spectrum, per-channel spectra and band powers.

        Returns the channel-mean spectrum, per-channel CSV (`psd_channels.csv`)
        and delta/theta/alpha/beta/gamma band power in uV^2.  This is a
        time-averaged spectrum, not a time-frequency analysis: use MNE-MCP
        (`mne_tfr_morlet`) for ERSP/ITC.

        Args:
            file_path: Absolute path to a .set file.
            fmax_hz: Upper frequency in Hz; defaults to min(45, Nyquist-1) and
                must stay below 90% of Nyquist.
            fmin_hz: Lower frequency in Hz (default 0).
            method: Optional method profile id from `eeglab_method_catalog`.
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        return api.compute_psd(
            file_path, fmax_hz, fmin_hz, method=method,
            override_gate=override_gate, override_reason=override_reason,
        )

    @srv.tool()
    def eeglab_plot_results(
        file_path: str,
        kind: str = "erp_waveform",
        time_s: float = 0.3,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Render an ERP waveform, scalp topography or PSD figure and save it as PNG.

        Args:
            file_path: Absolute path to a .set file.
            kind: 'erp_waveform', 'topomap' or 'psd' ('psd' is legacy; prefer
                eeglab_compute_psd, which also returns numeric band powers).
            time_s: Time point in seconds for the topomap.
            method: Optional method profile id, e.g. 'M-PLOT-TOPO-01'.
            override_gate: Proceed despite blocked gate checks (requires a reason).
            override_reason: Why proceeding is acceptable; recorded in the job.
        """
        return api.plot_results(
            file_path, kind, time_s,
            method=method, override_gate=override_gate, override_reason=override_reason,
        )

    @srv.tool()
    def eeglab_qc_report(file_path: str) -> dict:
        """Compute amplitude statistics, flat channels, outlier channels and event quality metrics.

        Also lists the checks that were NOT performed, so the report is not over-read.
        """
        return api.qc_report(file_path)

    # ------------------------------------------------------------ methodology
    @srv.tool()
    def eeglab_method_catalog(stage: str = "") -> dict:
        """List the method profiles: id, parameters, gates and the claims they cite.

        Args:
            stage: Optional filter, e.g. 'filter', 'reref', 'ica', 'epoch',
                'baseline', 'asr', 'qc', 'stats', 'export', 'plot', 'psd'.
        """
        return api.method_catalog(stage)

    @srv.tool()
    def eeglab_official_claims(topic: str = "") -> dict:
        """List the official EEGLAB statements and literature the gates cite.

        Each claim carries an ID, a statement, the risk of ignoring it, and a
        source locator.

        Args:
            topic: Optional topic code: FILT, REF, ICA, EPOCH, ASR, STAT, QC, GEN.
        """
        return api.official_claims(topic)

    @srv.tool()
    def eeglab_method_preflight(
        file_path: str,
        action: str,
        params: dict | None = None,
        method: str | None = None,
        override_gate: bool = False,
        override_reason: str = "",
    ) -> dict:
        """Run the method gates for an action without executing it (dry run).

        Use this to see what would be checked before running an analysis.

        Args:
            file_path: Absolute path to a .set file.
            action: Gated action: filter, reref, epoch, baseline, ica, plot,
                export_long, psd.
            params: Parameters for that action, e.g. {"highpass_hz": 0.1, "lowpass_hz": 30}.
            method: Optional method profile id.
            override_gate: Evaluate the override path (requires a reason).
            override_reason: Why proceeding would be acceptable.
        """
        return api.method_preflight(
            file_path, action, params, method,
            override_gate=override_gate, override_reason=override_reason,
        )

    return srv


def main() -> int:
    try:
        load_settings()
    except ConfigError as exc:
        print(f"[eeglab-mcp] configuration error: {exc}", file=sys.stderr)
        return 2
    build_server().run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
