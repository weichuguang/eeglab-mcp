"""Run the MATLAB-native test suites against the configured EEGLAB install.

The suites call real EEGLAB functions (pop_epoch, pop_reref, runica, spectopo …)
and check properties we can verify independently, such as a known injected ERP
peak, rather than merely "it did not crash".

Exit code is nonzero when any check fails, so it can be used in CI.

    python scripts/run_matlab_tests.py
    python scripts/run_matlab_tests.py --out outputs/matlab_tests.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eeglab_mcp.config import load_settings  # noqa: E402


def _matlab_str(p: Path | str) -> str:
    """Quote a path for a MATLAB command string (forward slashes, single quotes)."""
    return str(p).replace("\\", "/").replace("'", "''")


def main() -> int:
    # 详情里可能含 µ 等字符；Windows 控制台默认是 GBK，直接打印会抛 UnicodeEncodeError。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "outputs" / "matlab_tests.json"),
                    help="where to write the JSON summary")
    ap.add_argument("--eeglab-root", default=None,
                    help="override the EEGLAB root from config/default.yaml")
    args = ap.parse_args()

    settings = load_settings()
    root = Path(args.eeglab_root).resolve() if args.eeglab_root else settings.eeglab.root
    matlab = settings.matlab.executable
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if not matlab.exists():
        print(f"MATLAB not found: {matlab}", file=sys.stderr)
        return 2
    if not (root / "functions").is_dir():
        print(f"EEGLAB root has no functions/ directory: {root}", file=sys.stderr)
        return 2

    batch = (
        f"setenv('EEGLAB_ROOT','{_matlab_str(root)}'); "
        f"addpath('{_matlab_str(ROOT / 'matlab')}'); "
        f"addpath('{_matlab_str(ROOT / 'matlab' / 'tests')}'); "
        f"run_all_tests('{_matlab_str(out)}')"
    )

    print(f"MATLAB  : {matlab}")
    print(f"EEGLAB  : {root}")
    print(f"summary : {out}")
    t0 = time.perf_counter()
    proc = subprocess.run([str(matlab), "-batch", batch], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=settings.matlab.timeout_seconds)
    elapsed = time.perf_counter() - t0

    if not out.is_file():
        print("MATLAB did not write a summary; stderr follows:", file=sys.stderr)
        print(proc.stderr[-4000:], file=sys.stderr)
        return 1

    data = json.loads(out.read_text(encoding="utf-8"))
    for t in data.get("tests", []):
        print(f"{'PASS' if t['passed'] else 'FAIL'}  {t['name']:<38} {t['detail']}")

    print("-" * 72)
    print(f"{data['passed']}/{data['total']} passed in {elapsed:.1f}s "
          f"(EEGLAB {data.get('eeglab_root')})")
    if data.get("failed"):
        print(f"{data['failed']} failed; MATLAB exited with {proc.returncode}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
