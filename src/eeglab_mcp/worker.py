"""Persistent MATLAB worker.

Keeps one MATLAB process alive and feeds it jobs through a file queue.
This removes the 12-15 s cold start from every call after the first.

If the worker dies or does not answer in time, the caller falls back to a
one-shot `matlab -batch` process, so a hung worker can never wedge the server.
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import Settings


class WorkerError(RuntimeError):
    pass


class MatlabWorker:
    def __init__(self, settings: Settings):
        self.s = settings
        self.dir = settings.paths.output_root / "worker"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.started_at: float | None = None
        self.jobs_served = 0
        atexit.register(self.stop)   # never leave an orphan MATLAB process

    # ------------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        # clear stale files from a previous session
        for pattern in ("req_*.json", "job_*.json", "res_*.json", "__shutdown__"):
            for f in self.dir.glob(pattern):
                try:
                    f.unlink()
                except OSError:
                    pass

        cmd = (
            f"addpath('{_q(self.s.matlab.driver_dir)}'); "
            f"matlab_worker('{_q(self.dir)}',{int(self.s.matlab.worker_idle_seconds)});"
        )
        # MATLAB writes a lot of console output; send it to a file so the pipe
        # can never fill up and block the worker.
        self.log_path = self.dir / "worker_stdout.log"
        self._log_fh = self.log_path.open("a", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            [str(self.s.matlab.executable), "-batch", cmd],
            cwd=str(self.dir),
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        self.started_at = time.time()

        # Wait until the worker answers a ping, so the first real job is not lost.
        deadline = time.time() + self.s.matlab.timeout_seconds
        while time.time() < deadline:
            if not self.alive:
                raise WorkerError("MATLAB worker exited during startup")
            try:
                self._roundtrip({"action": "status", "eeglab_root": str(self.s.eeglab.root).replace("\\", "/"),
                                 "params": {}, "input": {}, "output_dir": str(self.dir).replace("\\", "/")},
                                timeout=90)
                return
            except WorkerError:
                time.sleep(0.5)
        raise WorkerError("MATLAB worker did not become ready in time")

    def stop(self) -> None:
        if not self.alive:
            return
        try:
            (self.dir / "__shutdown__").write_text("stop", encoding="utf-8")
            self.proc.wait(timeout=20)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        finally:
            self.proc = None

    # ------------------------------------------------------------------
    def run(self, job: dict[str, Any], timeout: float) -> dict[str, Any]:
        with self.lock:
            if not self.alive:
                self.start()
            return self._roundtrip(job, timeout)

    def _roundtrip(self, job: dict[str, Any], timeout: float) -> dict[str, Any]:
        token = uuid.uuid4().hex[:12]
        req = self.dir / f"req_{token}.json"
        res = self.dir / f"res_{token}.json"
        tmp = self.dir / f"tmp_{token}.json"
        tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, req)                      # atomic publish

        deadline = time.time() + timeout
        while time.time() < deadline:
            if res.is_file():
                try:
                    payload = json.loads(res.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    time.sleep(0.05)
                    continue
                try:
                    res.unlink()
                except OSError:
                    pass
                self.jobs_served += 1
                return payload
            if not self.alive:
                raise WorkerError("MATLAB worker exited while processing a job")
            time.sleep(0.05)
        raise WorkerError(f"Worker did not answer within {timeout:.0f}s")


def _q(p: Path | str) -> str:
    return str(p).replace("\\", "/").replace("'", "''")
