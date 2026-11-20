# EEGLAB-MCP

[![CI](https://github.com/weichuguang/eeglab-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/weichuguang/eeglab-mcp/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/protocol-MCP-6f42c1.svg)](https://modelcontextprotocol.io)

An MCP (Model Context Protocol) server that lets an AI agent drive a **real MATLAB/EEGLAB**
installation for reproducible EEG analysis: inspection, preprocessing, ICA, epoching, ERP,
spectral analysis and quality control. Every result comes from an actual MATLAB run — there
is no simulation layer — and every call returns structured data, artifacts, parameter records
and logs that can be checked afterwards.

> 中文简介：本服务把 MCP 智能体接到真实的 MATLAB/EEGLAB 上，提供 21 个受控工具，
> 覆盖数据检查、预处理、ICA、分段、ERP、频谱、质控、批量处理与方法学门控。
> 所有计算由 MATLAB 执行，结果可复核。设计文档见 [`docs/`](docs/)。

---

## Why this exists

An LLM can plan an EEG analysis, but it cannot be trusted to run arbitrary MATLAB code on
research data. EEGLAB-MCP separates the two:

- **The agent** understands the request and chooses tools.
- **EEGLAB/MATLAB** performs the computation.
- **This server** validates parameters, enforces a path whitelist, runs methodology gates
  before computation, and records provenance.

The design is deliberately conservative: no tool accepts MATLAB code, no tool writes to the
original data, and no result is ever invented.

---

## Repository layout

| Path | Contents |
| --- | --- |
| `.github/` | CI workflow and issue / pull-request templates |
| `config/` | Example configuration (MATLAB and EEGLAB paths, input whitelist, limits) |
| `docs/` | Methodology, interoperability and a complete file inventory |
| `matlab/` | MATLAB entry point, persistent worker and native tests |
| `scripts/` | Benchmark, job-isolation and verification scripts |
| `src/eeglab_mcp/` | MCP server, tools, gates, security and the knowledge base |
| `tests/` | MATLAB-free unit tests and MATLAB integration tests |

A file-by-file inventory is in [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

---

## Requirements

| Component | Requirement | Notes |
| --- | --- | --- |
| Python | 3.12 | `requires-python = ">=3.12"` |
| MATLAB | R2023a (verified) | Newer releases are expected to work; older ones are untested |
| EEGLAB | 13.0.0b (verified) | Newer releases are not tested |
| OS | Windows, macOS, Linux | MATLAB must be on `PATH` or given as an absolute path |

The server starts a persistent MATLAB worker to avoid paying the 10–15 s startup cost on
every call. If the worker dies or stops responding, it falls back to a one-shot
`matlab -batch` process instead of hanging.

---

## Quick start

```bash
git clone https://github.com/weichuguang/eeglab-mcp.git
cd eeglab-mcp
python -m venv .venv

# Windows
.venv\Scripts\python -m pip install -e .
# macOS / Linux
.venv/bin/python -m pip install -e .

cp config/default.example.yaml config/default.yaml
```

Edit `config/default.yaml` and set at least:

```yaml
matlab:
  executable: "matlab"          # or an absolute path
  driver_dir: "../matlab"
eeglab:
  root: "/path/to/eeglab"
paths:
  allowed_input_roots:
    - "/path/to/eeg_data"
```

Relative paths are resolved against the `config/` directory. Then verify:

```bash
python -m eeglab_mcp.server    # starts the stdio server; Ctrl+C to stop
python -m pytest tests -q -m "not integration"
```

For a full capability check (requires MATLAB and EEGLAB):

```bash
python scripts/verify_e2e.py       # writes outputs/VERIFICATION_REPORT.md
python scripts/verify_stdio.py     # real MCP client over stdio
```

---

## Client configuration

The server is a standard stdio MCP server. Use the **absolute path** to the virtual
environment's Python so the client does not depend on `PATH`.

**Claude Code / Claude Desktop** (`.mcp.json` or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "eeglab": {
      "command": "/absolute/path/to/eeglab-mcp/.venv/bin/python",
      "args": ["-m", "eeglab_mcp.server"],
      "env": {
        "EEGLAB_MCP_CONFIG": "/absolute/path/to/eeglab-mcp/config/default.yaml"
      }
    }
  }
}
```

On Windows use `...\\.venv\\Scripts\\python.exe`.

**VS Code** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "eeglab": {
      "type": "stdio",
      "command": "/absolute/path/to/eeglab-mcp/.venv/bin/python",
      "args": ["-m", "eeglab_mcp.server"],
      "env": {
        "EEGLAB_MCP_CONFIG": "/absolute/path/to/eeglab-mcp/config/default.yaml"
      }
    }
  }
}
```

Restart the client and ask: *“List the EEGLAB tools you can use.”* A healthy server returns
tool names such as `eeglab_get_status` and `eeglab_inspect_dataset`.

---

## Tools (20)

### Data access and inspection

| Tool | Purpose |
| --- | --- |
| `eeglab_get_status` | MATLAB version, EEGLAB path, availability of core functions. Call this first. |
| `eeglab_list_files` | List `.set` files under the allowed roots. |
| `eeglab_inspect_dataset` | Sampling rate, channels, duration, events, `.fdt` integrity, non-finite values. |
| `eeglab_load_dataset` | Validate and stage a copy in a job directory; the original is never modified. |
| `eeglab_import_data` | EDF / BDF / CNT / BrainVision → `.set`, with SHA-256 of the source file. |
| `eeglab_get_job_status` | Logs, parameters and artifact checksums of a previous job. |

### Preprocessing and core analysis

| Tool | Purpose |
| --- | --- |
| `eeglab_filter_data` | Zero-phase FIR high/low/band-pass and notch; cutoff checked against Nyquist. |
| `eeglab_rereference` | Average or explicit channel reference. |
| `eeglab_epoch_data` | Epoch around event codes; window validated. |
| `eeglab_baseline_correct` | Baseline correction over a specified window. |
| `eeglab_run_ica` | `runica` or PCA; weights saved. Components are **never** rejected automatically. |
| `eeglab_compute_erp` | Condition average; exports the full channel × time matrix as CSV. |
| `eeglab_compute_psd` | Welch power spectrum, per-channel spectra and delta/theta/alpha/beta/gamma band power (µV²), with line-noise hints. |
| `eeglab_plot_results` | ERP waveform or scalp topography as PNG (`kind="psd"` is legacy; prefer `eeglab_compute_psd`). |
| `eeglab_qc_report` | Amplitude statistics, flat/outlier channels, event quality, and the checks **not** performed. |

### Batch and interoperability

| Tool | Purpose |
| --- | --- |
| `eeglab_batch_process` | Process many `.set` files in one MATLAB process; one failure does not stop the batch. |
| `eeglab_run_pipeline` | `basic_preprocess` or `erp_analysis` in a single call. |
| `eeglab_export_long_table` | Long table (`subject, condition, channel, mean_uv, trial`) for MNE-MCP / Pingouin-MCP. |

### Methodology layer

| Tool | Purpose |
| --- | --- |
| `eeglab_method_catalog` | List the 41 method profiles with parameters, citations, gates and executability. |
| `eeglab_official_claims` | Query the 49 curated claims with source locators and risk notes. |
| `eeglab_method_preflight` | Dry run: which gates would fire for a file and a parameter set, without computing. |

Preprocessing tools run their methodology gates before any computation. A blocked call
returns `GATE_BLOCKED` and produces no output. Overriding a block requires a written reason
(≥ 20 characters) that is stored with the original finding.

Frequency analysis in this server is a time-averaged Welch spectrum (`eeglab_compute_psd`).
Time-frequency analysis (ERSP/ITC) is deliberately out of scope; use MNE-MCP's
`mne_tfr_morlet`. See `docs/INTEROP.md`.

---

## Return envelope

```json
{
  "success": true,
  "job_id": "3f2a...",
  "action": "inspect",
  "result": {"...": "structured result"},
  "warnings": ["Channel locations are not defined ..."],
  "errors": [],
  "artifacts": [{"path": "...", "kind": "eeglab_set", "bytes": 153880, "sha256": "..."}],
  "provenance": {"matlab_version": "...", "eeglab_root": "...", "job_id": "..."},
  "runtime": {"wall_seconds": 14.5, "job_dir": "..."},
  "interpretation_limits": ["success=true means the computation completed; ..."]
}
```

> `success: true` means the program ran. It does **not** mean the scientific conclusion is
> valid. An ERP being computed is not evidence of a significant condition difference; a
> successful ICA decomposition is not evidence that artifacts were removed correctly.

---

## Safety model

1. **Path whitelist.** Inputs must be absolute paths that resolve (after `realpath`) inside
   `allowed_input_roots` or `output_root`. Traversal and symlink escapes are rejected.
2. **No arbitrary code execution.** No tool accepts a MATLAB code string; there is no `eval`
   or script concatenation. Every action is dispatched from `matlab/run_job.m`.
3. **Double validation.** Parameters are checked in Python and again in MATLAB.
4. **Read-only source data.** Writes go to per-job directories; `load_dataset` returns the
   source SHA-256.
5. **Timeouts and logs.** Each job keeps `job.json`, `matlab_result.json` and
   `matlab_stdout.log`.
6. **Methodology gates.** 49 claims and 41 method profiles are checked before computation.
7. **Facts from the file.** Gates read real header properties from the `.set` file, not
   caller claims.

---

## Testing

```bash
# Fast unit tests: no MATLAB needed (<1 s)
python -m pytest tests -q -m "not integration"

# Integration tests: start a real MATLAB process
python -m pytest tests -q

# Native MATLAB tests (36 checks): real EEGLAB functions and a known-answer ERP
python scripts/run_matlab_tests.py

# End-to-end verification and protocol-level check
python scripts/verify_e2e.py
python scripts/verify_stdio.py
```

CI runs the MATLAB-free unit tests on Ubuntu and Windows with Python 3.12. Integration and
end-to-end tests require a licensed MATLAB installation and are run locally.

---

## Performance (reference machine)

Measured with `scripts/benchmark_timings.py`; medians, not best-case values.

| Operation | Cold start (new process each call) | Persistent worker |
| --- | --- | --- |
| `get_status` | 12.2 s | **0.20 s** |
| `inspect_dataset` | 13.9 s | 0.81 s |
| `run_pipeline(erp_analysis)` | 14.9 s | 1.07 s |
| `plot_results(erp_waveform)` | 25.6 s | 1.43 s |
| Seven-step chain | 110.9 s | **5.6 s** |

Reference machine: Intel Xeon E-2388G, 64 GB RAM, Windows 11 22H2, MATLAB R2023a,
EEGLAB 13.0.0b, Python 3.12.10, EEGLAB sample dataset (32 channels, 128 Hz, 30 504 points,
154 events). The worker start-up itself takes about 5.6 s on the first call.

---

## Known limitations

- **BIOSIG dependency.** `.edf`/`.bdf` import goes through `pop_biosig`; a broken plugin fails
  loudly rather than silently degrading.
- **Sequential batch.** `batch_process` runs files one after another in one MATLAB session;
  the cap is `limits.max_batch_files`.
- **No channel locations, no topomap.** The EEGLAB sample dataset has no `chanlocs`; the
  topomap tool reports this explicitly instead of drawing a misleading map.
- **ICA components are never rejected automatically.** Rejection requires explicit criteria
  and human confirmation.
- **`pop_runica` workaround.** EEGLAB 13's `pop_runica` creates a GUI figure that fails on
  modern MATLAB. The server calls `runica` directly in `matlab/ica_decompose.m` and writes
  the decomposition back. This is documented in the results; equivalence with `pop_runica`
  has not been verified element by element.
- **Objects do not persist across calls.** The MATLAB process persists; workspace objects do
  not. Intermediate results are chained through artifact files.
- **No `run_code` escape hatch.** Capability is bounded by the 21 tools, by design.
- **Time-frequency is out of scope.** The server computes a time-averaged Welch spectrum;
  ERSP/ITC belong to MNE-MCP (`mne_tfr_morlet`). This is a deliberate boundary, not a
  missing feature.
- **Unit inference.** V vs µV is inferred from amplitude and reported as
  `input_unit_assumed`; unusual data can be misclassified.

---

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) | Knowledge base, gate engine and override policy |
| [`docs/INTEROP.md`](docs/INTEROP.md) | Hand-off contract with MNE-MCP / Pingouin-MCP |

---

## Contributing

Issues and pull requests are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) and
run the unit tests before submitting. Security reports should follow [`SECURITY.md`](SECURITY.md).

## License

MIT. See [`LICENSE`](LICENSE).
