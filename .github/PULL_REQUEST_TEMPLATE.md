## What changed

<!-- One or two sentences. Link the issue if one exists. -->

## Why

<!-- The problem this solves, and why the chosen approach is appropriate. -->

## Checks

- [ ] `python -m pytest tests -q -m "not integration"` passes
- [ ] MATLAB tests run if `matlab/` or the adapter changed
- [ ] No data files, logs, `.docx`, `.pdf` or local configuration included
- [ ] New or changed tools are documented in the README tool table
- [ ] Safety properties preserved (path whitelist, no arbitrary code, read-only inputs, gates first)
