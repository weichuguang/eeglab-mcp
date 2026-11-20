"""Uniform response envelope shared by every tool.

Separates "the program ran" from "the science holds": `success` only means the
MATLAB job completed and returned a well-formed result.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .adapter import MatlabResult

MAX_DIGEST_BYTES = 256 * 1024 * 1024


def digest(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size > MAX_DIGEST_BYTES:
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(res: MatlabResult) -> dict[str, Any]:
    artifacts = []
    for a in res.artifacts:
        if not isinstance(a, dict) or not a.get("path"):
            continue
        p = Path(a["path"])
        artifacts.append(
            {
                "path": str(p),
                "kind": a.get("kind", "file"),
                "bytes": p.stat().st_size if p.is_file() else a.get("bytes", 0),
                "sha256": digest(p),
            }
        )

    out: dict[str, Any] = {
        "success": res.ok,
        "job_id": (res.provenance or {}).get("job_id"),
        "action": res.action,
        "result": res.data if res.ok else {},
        "warnings": res.warnings,
        "errors": [res.error] if res.error else [],
        "artifacts": artifacts,
        "provenance": res.provenance,
        "runtime": {
            "wall_seconds": round(res.wall_seconds, 1),
            "job_dir": str(res.job_dir) if res.job_dir else None,
        },
        "interpretation_limits": [
            "success=true means the computation completed; it does NOT mean the "
            "scientific conclusion is valid.",
            "Review warnings before using any result.",
        ],
    }
    return out
