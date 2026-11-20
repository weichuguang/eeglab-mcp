"""Path and parameter safety. Every input path must sit under an allowed root."""
from __future__ import annotations

import os
from pathlib import Path

from .config import Settings


class SecurityError(ValueError):
    """Raised when a request violates a safety constraint."""

    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


ANALYSIS_SUFFIXES = frozenset({".set"})
IMPORT_SUFFIXES = frozenset({".edf", ".bdf", ".cnt", ".vhdr", ".set"})


def resolve_input(
    path_str: str,
    settings: Settings,
    suffixes: frozenset[str] = ANALYSIS_SUFFIXES,
) -> Path:
    """Resolve an EEG input path and verify it is inside an allowed root.

    Rejects: empty input, non-existent files, directory traversal, symlink
    escapes and files outside the configured roots.
    """
    if not path_str or not str(path_str).strip():
        raise SecurityError("EMPTY_PATH", "file_path must not be empty")

    raw = Path(str(path_str)).expanduser()
    if not raw.is_absolute():
        raise SecurityError(
            "RELATIVE_PATH",
            f"file_path must be absolute: {path_str}",
            "Pass an absolute path under one of the configured allowed roots.",
        )

    # realpath resolves '..' and symlinks, so escapes are caught below
    resolved = Path(os.path.realpath(str(raw)))
    if not resolved.is_file():
        raise SecurityError("FILE_NOT_FOUND", f"Input file not found: {resolved}")

    # Server-produced artifacts live under output_root and are trusted as inputs,
    # so a filtered/epoch'ed .set can be fed into the next step.
    roots = [Path(os.path.realpath(str(r))) for r in settings.paths.allowed_input_roots]
    roots.append(Path(os.path.realpath(str(settings.paths.output_root))))
    for root in roots:
        if _is_within(resolved, root):
            break
    else:
        raise SecurityError(
            "PATH_NOT_ALLOWED",
            f"Path is outside the allowed input roots: {resolved}",
            "Allowed roots: " + "; ".join(str(r) for r in roots),
        )

    size_mb = resolved.stat().st_size / (1024 * 1024)
    if size_mb > settings.limits.max_input_mb:
        raise SecurityError(
            "FILE_TOO_LARGE",
            f"Input file is {size_mb:.1f} MB, above the {settings.limits.max_input_mb} MB limit",
        )

    if resolved.suffix.lower() not in suffixes:
        raise SecurityError(
            "UNSUPPORTED_FORMAT",
            f"Unsupported format: {resolved.suffix}. Allowed: {', '.join(sorted(suffixes))}",
        )

    # BrainVision needs its companion .eeg/.vmrk files next to the .vhdr
    if resolved.suffix.lower() == ".vhdr":
        for companion in (".eeg", ".vmrk"):
            if not resolved.with_suffix(companion).is_file():
                raise SecurityError(
                    "MISSING_COMPANION",
                    f"BrainVision dataset is incomplete: missing {resolved.with_suffix(companion).name}",
                )
    return resolved


def resolve_output_dir(path_str: str, settings: Settings) -> Path:
    """Output paths must stay under output_root."""
    raw = Path(str(path_str)).expanduser()
    if not raw.is_absolute():
        raise SecurityError("RELATIVE_PATH", f"output_dir must be absolute: {path_str}")
    resolved = Path(os.path.realpath(str(raw)))
    root = Path(os.path.realpath(str(settings.paths.output_root)))
    if not _is_within(resolved, root):
        raise SecurityError(
            "OUTPUT_NOT_ALLOWED",
            f"output_dir is outside output_root ({root}): {resolved}",
        )
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def require_range(name: str, value, lo, hi, unit: str = "") -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise SecurityError("BAD_PARAM", f"{name} must be a number, got {value!r}")
    if not (lo <= v <= hi):
        raise SecurityError(
            "BAD_PARAM",
            f"{name}={v}{unit} is outside the permitted range [{lo}, {hi}]{unit}",
        )
    return v
