# Security policy

## Supported versions

The `main` branch and the latest tagged release receive security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Use GitHub's private vulnerability reporting: go to the repository's **Security** tab and
choose **Report a vulnerability**. If that is unavailable, contact the maintainer through the
address listed on the GitHub profile.

Include:

- affected version or commit,
- a minimal reproduction (tool name, arguments, configuration shape),
- the impact you believe it has,
- any suggested fix.

You can expect an acknowledgement within a few working days. Please allow time for a fix and
a release before public disclosure.

## Scope

Security-relevant properties of this project include:

- **Path containment** — inputs must resolve inside the configured allowed roots; traversal
  and symlink escapes must be rejected.
- **No arbitrary code execution** — no tool may accept a MATLAB code string; all behaviour is
  dispatched by `matlab/run_job.m`.
- **Read-only source data** — analysis must not modify input datasets.
- **Gate ordering** — methodology gates must run before any computation and must not be
  bypassed without a recorded reason.
- **Credential handling** — the project stores no credentials; configuration must not be
  committed.

Issues outside this scope (for example, a deliberately hostile local MATLAB installation or a
user editing `run_job.m` to execute arbitrary code) are not treated as vulnerabilities, though
reports are still welcome.
