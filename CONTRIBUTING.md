# Contributing to EEGLAB-MCP

Thanks for taking the time to contribute. This project values correctness over surface area:
a tool that refuses an invalid parameter is better than one that silently produces a number.

## Development setup

```bash
git clone https://github.com/weichuguang/eeglab-mcp.git
cd eeglab-mcp
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"     # Windows: .venv\Scripts\python
cp config/default.example.yaml config/default.yaml
```

Edit `config/default.yaml` for your MATLAB and EEGLAB installation. The file is ignored by
git and must never be committed.

## Before opening a pull request

1. **Run the MATLAB-free tests.** They must pass on your machine:
   ```bash
   python -m pytest tests -q -m "not integration"
   ```
2. **Run the MATLAB tests** if your change touches `matlab/` or the adapter:
   ```bash
   python -m pytest tests -q
   python scripts/run_matlab_tests.py
   ```
3. **Keep the methodology layer consistent.** If you add or change a method profile, run
   `eeglab_method_catalog` and check that every referenced claim exists. The unit tests
   validate the catalog automatically.
4. **Do not weaken safety checks.** Path validation, the no-`eval` rule, read-only inputs and
   the gate-before-compute ordering are design constraints, not implementation details.
5. **Document behaviour that a user can observe.** New tools need a docstring (it becomes the
   MCP tool description) and an entry in the README tool table.

## Code style

- Python 3.12, standard library where practical.
- Type hints on public functions; dataclasses for structured results.
- User-facing errors carry a stable code (`PATH_NOT_ALLOWED`, `GATE_BLOCKED`, ...) and a
  concrete remedy.
- MATLAB code stays inside `matlab/`; no MATLAB code strings may be accepted from callers.

## Commit messages

Use a short imperative subject and explain the reason in the body. Reference issues where
relevant. Do not commit data files, MATLAB output, `.docx`, `.pdf` or local configuration.

## Reporting bugs

Open an issue with:

- the tool name and the exact arguments,
- the returned `errors` / `warnings` and `job_id`,
- MATLAB release, EEGLAB version, Python version and OS,
- the smallest dataset that reproduces the problem (or a description of it).

Security issues should follow [SECURITY.md](SECURITY.md), not the public issue tracker.
