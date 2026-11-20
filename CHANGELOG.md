# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/).

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
