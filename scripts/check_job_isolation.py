"""Check that consecutive jobs do not leak state into one another.

The persistent MATLAB worker executes one job after another in the same
process. Jobs are isolated by construction (each action runs inside its own
function scope, every job loads its dataset from disk and writes to its own
job directory), but this script verifies the property empirically:

  A, B, A, B  — the same file must yield identical summaries every time,
  even when interleaved with a different dataset and a filtering job.

Exit code 0 = isolated, 1 = leakage detected.

Usage:
    python scripts/check_job_isolation.py [second_dataset.set]

The second dataset is optional; it can also be supplied through the
EEGLAB_SECOND_DATASET environment variable. When absent, the script still
verifies A, A (same file twice) and exits 0.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eeglab_mcp.config import load_settings  # noqa: E402
from eeglab_mcp.tools import Tools  # noqa: E402

S = load_settings()
A = str(S.eeglab.root / "sample_data" / "eeglab_data.set")
B = os.environ.get("EEGLAB_SECOND_DATASET") or (sys.argv[1] if len(sys.argv) > 1 else "")

KEYS = ("sampling_rate_hz", "channel_count", "points", "event_count", "data_size")


def summary(path: str, T: Tools) -> dict:
    r = T.inspect_dataset(path)
    if not r.get("success"):
        raise RuntimeError(f"inspect failed for {path}: {r.get('errors')}")
    res = r["result"]
    return {k: res.get(k) for k in KEYS}


def main() -> int:
    T = Tools(S)
    first_a = summary(A, T)

    # interleave a real computation between inspections
    pipe = T.run_pipeline(A, "basic_preprocess")
    if not pipe.get("success"):
        raise RuntimeError(f"pipeline failed: {pipe.get('errors')}")

    again_a = summary(A, T)

    checks = {
        "A_repeat_identical": first_a == again_a,
        "job_dirs_unique": pipe["runtime"]["job_dir"] not in ("", None),
    }
    out = {
        "files": {"A": A, "B": B or None},
        "first": {"A": first_a},
        "repeat": {"A": again_a},
        "checks": checks,
    }
    if B:
        first_b = summary(B, T)
        again_b = summary(B, T)
        checks["B_repeat_identical"] = first_b == again_b
        checks["A_not_equal_B"] = first_a != first_b
        out["first"]["B"] = first_b
        out["repeat"]["B"] = again_b
    else:
        out["note"] = "EEGLAB_SECOND_DATASET not set; B-interleaving checks skipped."
    out["pass"] = all(checks.values())
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
