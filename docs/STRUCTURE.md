# Repository structure

A complete inventory of tracked files. Descriptions state what each file does in the
current code, not what it is intended to become.

## Top level

| Path | Description |
| --- | --- |
| `README.md` | Project overview, requirements, installation, client configuration, tool reference, safety model, testing and known limitations. |
| `LICENSE` | MIT licence. |
| `pyproject.toml` | Packaging metadata, runtime dependencies (`mcp`, `PyYAML`), console entry point `eeglab-mcp`, package data and pytest markers. |
| `CHANGELOG.md` | Version history in Keep a Changelog format. |
| `CONTRIBUTING.md` | Development setup, required tests, code style and pull-request rules. |
| `SECURITY.md` | Private vulnerability reporting and the security properties this project guarantees. |
| `CITATION.cff` | Citation metadata (CFF 1.2) for research use. |
| `.gitignore` | Excludes virtual environments, caches, local configuration, outputs, logs, EEG data formats and office documents. |
| `.gitattributes` | Normalises line endings (LF) and keeps `.bat` files CRLF. |

## `.github/`

| Path | Description |
| --- | --- |
| `workflows/ci.yml` | GitHub Actions: unit tests on Ubuntu and Windows with Python 3.12, plus a wheel build. |
| `ISSUE_TEMPLATE/bug_report.yml` | Bug report form (tool, environment, returned errors, logs). |
| `ISSUE_TEMPLATE/feature_request.yml` | Feature request form, including the no-arbitrary-code constraint. |
| `PULL_REQUEST_TEMPLATE.md` | Pull-request checklist (tests, safety properties, documentation). |

## `config/`

| Path | Description |
| --- | --- |
| `default.example.yaml` | Configuration template: MATLAB executable and driver directory, EEGLAB root, allowed input roots, output/log roots, size and science limits. Copy to `config/default.yaml` (ignored by git). |

## `docs/`

| Path | Description |
| --- | --- |
| `README.md` | Documentation index. |
| `METHODOLOGY.md` | Knowledge base and gate engine: 49 claims, 41 method profiles, blocking/override policy. |
| `INTEROP.md` | Hand-off contract with MNE-MCP and Pingouin-MCP: long-table schema, unit conventions, provenance fields. |
| `STRUCTURE.md` | This file inventory. |

## `matlab/`

| Path | Description |
| --- | --- |
| `run_job.m` | The only MATLAB entry point. Reads a job description, dispatches a fixed `action`, validates parameters again, calls EEGLAB and writes a JSON result. It accepts no MATLAB code from callers. |
| `matlab_worker.m` | Persistent worker loop: waits for request files, executes `run_job`, writes response files, exits after an idle timeout. |
| `ica_decompose.m` | Calls `runica` directly and writes `icaweights`, `icasphere`, `icachansind` and `icawinv`, avoiding EEGLAB 13's GUI-bound `pop_runica` path on modern MATLAB. |
| `detect_units.m` | Infers whether `EEG.data` is in volts or microvolts and returns the scale factor and unit label used in the result metadata. |
| `compute_psd_metrics.m` | Converts `spectopo` dB spectra to µV²/Hz, integrates standard band power and flags line-noise peaks. |
| `tests/make_synthetic_eeg.m` | Builds a synthetic EEG structure with a known embedded ERP, used by the native tests. |
| `tests/mcp_check.m` | Small assertion helper that records `name`, `passed` and `detail` for the MATLAB test runner. |
| `tests/run_all_tests.m` | Runs the MATLAB test suites, prints a summary and writes a JSON result file. Requires `EEGLAB_ROOT`. |
| `tests/test_core_functions.m` | Checks that the EEGLAB functions the server depends on are present and behave as expected. |
| `tests/test_plugin_presence.m` | Checks optional plugin availability (for example BIOSIG for EDF/BDF import). |
| `tests/test_sample_dataset.m` | Loads the EEGLAB sample dataset and verifies channel count, sampling rate, events, epoching and ERP. |
| `tests/test_synthetic_erp.m` | Known-answer test: recovers the embedded ERP from synthetic data. |
| `tests/test_spectral.m` | Known-answer checks for dB semantics, band integration, unit scaling, `fmax` cropping and line-noise detection. |
| `tests/test_unit_detection.m` | Verifies volt/microvolt inference, including the fallback for ambiguous amplitudes. |

## `scripts/`

| Path | Description |
| --- | --- |
| `benchmark_timings.py` | Measures cold-start versus persistent-worker latency for representative tools and writes JSON under `outputs/benchmarks/`. |
| `check_job_isolation.py` | Checks that repeated and interleaved inspections return identical summaries; optionally uses a second dataset via `EEGLAB_SECOND_DATASET`. |
| `run_matlab_tests.py` | Invokes the MATLAB native suite and parses its JSON summary. |
| `verify_e2e.py` | End-to-end run on the EEGLAB sample dataset; writes `outputs/VERIFICATION_REPORT.md` from actual returned values. |
| `verify_stdio.py` | Connects a real MCP client over stdio, lists tools and performs a path-rejection check. |

## `src/eeglab_mcp/`

| Path | Description |
| --- | --- |
| `__init__.py` | Package docstring and `__version__`. |
| `server.py` | MCP server entry point (`mcp.server.mcpserver.MCPServer`) and the 21 tool definitions with their descriptions. |
| `tools.py` | Tool implementations: input validation, gate invocation, MATLAB delegation and envelope construction. |
| `adapter.py` | One-shot `matlab -batch` adapter: builds the job file, runs MATLAB, parses the result and enforces timeouts. |
| `worker.py` | Client for the persistent MATLAB worker, including fallback to the one-shot adapter when the worker dies or times out. |
| `config.py` | Loads and validates YAML configuration; resolves relative paths against the configuration directory. |
| `security.py` | Path containment (absolute paths, `realpath`, allowed roots), size and format checks, numeric range validation. |
| `gates.py` | Gate engine: evaluates the checks attached to a method profile against facts reported by MATLAB and the requested parameters. |
| `methodology.py` | Loads and validates the knowledge base (`claims.json`, `methods/*.json`) and exposes claim/profile lookup. |
| `envelope.py` | Uniform response envelope: success flag, job id, result, warnings, errors, artifacts with SHA-256, provenance, runtime and interpretation limits. |

### `src/eeglab_mcp/data/`

| Path | Description |
| --- | --- |
| `claims.json` | 49 curated claims with topic, statement, risk, source locator and applicable actions. |
| `methods/asr.json` | Method profiles for automatic subspace reconstruction / artifact handling. |
| `methods/baseline.json` | Baseline-correction profiles. |
| `methods/epoch.json` | Epoching profiles (event selection, window limits). |
| `methods/export.json` | Long-table export profiles. |
| `methods/filter.json` | Filtering profiles (high-pass, low-pass, notch, Nyquist limits). |
| `methods/ica.json` | ICA profiles (algorithm, rank, component handling). |
| `methods/plot.json` | Plotting profiles (ERP waveform, topography, PSD). |
| `methods/psd.json` | Power-spectrum profiles (Welch spectrum, band power, Nyquist and record-length gates). |
| `methods/qc.json` | Quality-control profiles. |
| `methods/reref.json` | Re-referencing profiles. |
| `methods/stats.json` | Statistical-summary profiles. |

## `tests/`

| Path | Description |
| --- | --- |
| `test_gates.py` | Knowledge-base integrity and gate behaviour; runs without MATLAB. |
| `test_security.py` | Path containment, traversal, missing files, format and numeric-range validation; uses temporary directories, no local configuration. |
| `test_integration.py` | Real MATLAB/EEGLAB integration tests (marked `integration`); skipped automatically when no local configuration is present. |
