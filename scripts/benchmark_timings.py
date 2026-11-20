"""Benchmark tool latency in cold-start and persistent-worker modes.

Cold-start mode : use_persistent_worker=false — every call spawns a fresh
                  `matlab -batch` process (includes MATLAB + EEGLAB start-up).
Persistent mode : use_persistent_worker=true — the first call starts the worker,
                  later calls only queue a job.

All numbers come from the real installation on the EEGLAB sample dataset. The
script prints a JSON summary and writes it to outputs/benchmarks/.

Usage:
    python scripts/benchmark_timings.py
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eeglab_mcp.config import load_settings  # noqa: E402
from eeglab_mcp.tools import Tools  # noqa: E402

S = load_settings()
SAMPLE = str(S.eeglab.root / "sample_data" / "eeglab_data.set")
COLD = replace(S, matlab=replace(S.matlab, use_persistent_worker=False))


def timed(fn):
    t0 = time.perf_counter()
    r = fn()
    dt = time.perf_counter() - t0
    if not r.get("success"):
        raise RuntimeError(f"call failed: {r.get('errors')}")
    return dt, r


def stats(xs, nd=2):
    return {
        "n": len(xs),
        "median_s": round(statistics.median(xs), nd),
        "min_s": round(min(xs), nd),
        "max_s": round(max(xs), nd),
    }


def staged_path(envelope):
    for a in envelope.get("artifacts", []):
        if a.get("kind") == "eeglab_set":
            return a["path"]
    raise RuntimeError("pipeline produced no .set artifact")


def chain7(T):
    """status -> inspect -> load -> pipeline -> erp -> plot -> qc"""
    t0 = time.perf_counter()
    steps = []
    steps.append(timed(lambda: T.get_status())[0])
    steps.append(timed(lambda: T.inspect_dataset(SAMPLE))[0])
    steps.append(timed(lambda: T.load_dataset(SAMPLE))[0])
    dt, pipe = timed(lambda: T.run_pipeline(SAMPLE, "erp_analysis",
                                            event_types=["square"]))
    steps.append(dt)
    st = staged_path(pipe)
    steps.append(timed(lambda: T.compute_erp(st))[0])
    steps.append(timed(lambda: T.plot_results(st, "erp_waveform"))[0])
    steps.append(timed(lambda: T.qc_report(SAMPLE))[0])
    return round(time.perf_counter() - t0, 1), [round(x, 1) for x in steps]


def bare_startup(n=3):
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        subprocess.run([str(S.matlab.executable), "-batch", "disp(1)"],
                       capture_output=True, timeout=S.matlab.timeout_seconds)
        xs.append(time.perf_counter() - t0)
    return stats(xs)


def bench_cold(n_status=4, n_inspect=2, n_pipe=2, n_plot=2):
    T = Tools(COLD)
    out = {
        "get_status": stats([timed(lambda: T.get_status())[0] for _ in range(n_status)]),
        "inspect_dataset": stats([timed(lambda: T.inspect_dataset(SAMPLE))[0]
                                  for _ in range(n_inspect)]),
    }
    staged = staged_path(timed(lambda: T.run_pipeline(SAMPLE, "erp_analysis",
                                                      event_types=["square"]))[1])
    out["run_pipeline_erp"] = stats([timed(lambda: T.run_pipeline(
        SAMPLE, "erp_analysis", event_types=["square"]))[0] for _ in range(n_pipe)])
    out["plot_results"] = stats([timed(lambda: T.plot_results(staged, "erp_waveform"))[0]
                                 for _ in range(n_plot)])
    total, steps = chain7(T)
    out["chain7_total"] = {"n": 1, "total_s": total, "steps_s": steps}
    return out


def bench_warm(n_status=5, n_inspect=5, n_pipe=3, n_plot=3, n_chain=3):
    T = Tools(S)
    first, _ = timed(lambda: T.get_status())
    out = {"worker_first_call": {"n": 1, "seconds": round(first, 2)}}
    out["get_status"] = stats([timed(lambda: T.get_status())[0] for _ in range(n_status)])
    out["inspect_dataset"] = stats([timed(lambda: T.inspect_dataset(SAMPLE))[0]
                                    for _ in range(n_inspect)])
    staged = staged_path(timed(lambda: T.run_pipeline(SAMPLE, "erp_analysis",
                                                      event_types=["square"]))[1])
    out["run_pipeline_erp"] = stats([timed(lambda: T.run_pipeline(
        SAMPLE, "erp_analysis", event_types=["square"]))[0] for _ in range(n_pipe)])
    out["plot_results"] = stats([timed(lambda: T.plot_results(staged, "erp_waveform"))[0]
                                 for _ in range(n_plot)])
    runs = [chain7(T) for _ in range(n_chain)]
    out["chain7_total"] = {
        "n": n_chain,
        "median_s": round(statistics.median([r[0] for r in runs]), 1),
        "runs_s": [r[0] for r in runs],
        "steps_s_last": runs[-1][1],
    }
    return out


def main() -> int:
    summary = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version.split()[0],
        "sample": SAMPLE,
        "bare_matlab_start": bare_startup(),
        "cold": bench_cold(),
        "warm": bench_warm(),
    }
    out_dir = ROOT / "outputs" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = out_dir / ("latency_" + time.strftime("%Y%m%d_%H%M%S") + ".json")
    fn.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("written:", fn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
