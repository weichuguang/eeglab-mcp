# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-11-20

### Added

- `eeglab_compute_psd`: Welch power spectrum, full-resolution per-channel CSV
  (`psd_channels.csv`), delta/theta/alpha/beta/gamma band power in µV² and line-noise hints.
- `M-SPEC-PSD-01` / `M-SPEC-PSD-40-01` method profiles, `fmax_below_nyquist` (blocked) and
  `psd_record_length_sufficient` (advisory) checks, and claims `EEGLAB-QC-006` / `QC-007`.
- MATLAB-native `compute_psd_metrics.m` and the `test_spectral` suite (36 checks total).

### Changed

- `op_psd` rewritten: column-vector alignment fix, `spectopo` channel-drop validation and
  full-resolution per-channel export. `eeglab_plot_results(kind="psd")` is kept for
  backward compatibility.
- Catalog now has 49 claims, 41 method profiles and 41 checks.
- `verify_e2e.py` includes the PSD step (8/8); unit tests are 54/54.

### Fixed

- `.gitignore` no longer excludes the packaged methodology data directory.

## [1.1.0] - 2026-11-20

### Added

- Methodology layer: 47 curated claims, 39 method profiles and a pre-computation gate engine
  (`eeglab_method_catalog`, `eeglab_official_claims`, `eeglab_method_preflight`).
- Batch processing with per-file isolation (`eeglab_batch_process`).
- Long-table export for MNE-MCP / Pingouin-MCP (`eeglab_export_long_table`).
- Persistent MATLAB worker with automatic fallback to one-shot `matlab -batch`.
- Structured return envelope with artifacts, SHA-256 provenance and interpretation limits.

### Changed

- Configuration paths may now be relative to `config/`, so the repository can be cloned
  anywhere without editing absolute paths.
- MCP SDK dependency widened to `mcp>=2.3.0,<3`.
- Unit tests no longer require a local MATLAB/EEGLAB configuration.

### Fixed

- ICA decomposition bypasses EEGLAB 13's GUI-bound `pop_runica` path on modern MATLAB.

## [1.0.0] - 2025-10-21

### Added

- Initial public structure: 17 analysis tools covering inspection, filtering, re-referencing,
  epoching, baseline correction, ICA, ERP, plotting, QC, import and job status.
- Path whitelist, parameter validation, read-only source data and per-job logging.
