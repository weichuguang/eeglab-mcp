"""Configuration loading with real validation (no silent fallbacks)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    """Raised when configuration is missing or inconsistent."""


@dataclass(frozen=True)
class MatlabConfig:
    executable: Path
    timeout_seconds: int
    driver_dir: Path
    use_persistent_worker: bool
    worker_idle_seconds: int


@dataclass(frozen=True)
class EeglabConfig:
    root: Path


@dataclass(frozen=True)
class PathsConfig:
    allowed_input_roots: tuple[Path, ...]
    output_root: Path
    log_root: Path


@dataclass(frozen=True)
class LimitsConfig:
    max_input_mb: int
    max_array_points: int
    max_batch_files: int


@dataclass(frozen=True)
class ScienceConfig:
    max_lowpass_ratio: float
    min_epoch_span_s: float
    max_epoch_span_s: float
    min_trials_for_erp: int


@dataclass(frozen=True)
class Settings:
    matlab: MatlabConfig
    eeglab: EeglabConfig
    paths: PathsConfig
    limits: LimitsConfig
    science: ScienceConfig
    config_path: Path


def _resolve(value: Any, base: Path) -> Path:
    """Resolve a path from the config file relative to the config directory.

    Absolute paths are kept as-is; relative paths let the repository be cloned
    anywhere without editing machine-specific paths.
    """
    p = Path(value).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def _req(d: dict, key: str, where: str) -> Any:
    if not isinstance(d, dict) or key not in d or d[key] in (None, ""):
        raise ConfigError(f"Missing required config key: {where}.{key}")
    return d[key]


def load_settings(config_path: str | os.PathLike | None = None) -> Settings:
    """Load and validate settings. Raises ConfigError rather than guessing."""
    if config_path is None:
        config_path = os.environ.get("EEGLAB_MCP_CONFIG")
    if config_path is None:
        here = Path(__file__).resolve()
        candidate = here.parents[2] / "config" / "default.yaml"
        config_path = candidate
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    matlab = raw.get("matlab") or {}
    eeglab = raw.get("eeglab") or {}
    paths = raw.get("paths") or {}
    limits = raw.get("limits") or {}
    science = raw.get("science") or {}

    base = path.parent
    exe = Path(_req(matlab, "executable", "matlab")).expanduser()
    driver = _resolve(_req(matlab, "driver_dir", "matlab"), base)
    root = _resolve(_req(eeglab, "root", "eeglab"), base)
    roots = tuple(_resolve(p, base) for p in _req(paths, "allowed_input_roots", "paths"))

    return Settings(
        matlab=MatlabConfig(
            executable=exe,
            timeout_seconds=int(matlab.get("timeout_seconds", 900)),
            driver_dir=driver,
            use_persistent_worker=bool(matlab.get("use_persistent_worker", True)),
            worker_idle_seconds=int(matlab.get("worker_idle_seconds", 900)),
        ),
        eeglab=EeglabConfig(root=root),
        paths=PathsConfig(
            allowed_input_roots=roots,
            output_root=_resolve(_req(paths, "output_root", "paths"), base),
            log_root=_resolve(_req(paths, "log_root", "paths"), base),
        ),
        limits=LimitsConfig(
            max_input_mb=int(limits.get("max_input_mb", 4096)),
            max_array_points=int(limits.get("max_array_points", 300)),
            max_batch_files=int(limits.get("max_batch_files", 50)),
        ),
        science=ScienceConfig(
            max_lowpass_ratio=float(science.get("max_lowpass_ratio", 0.95)),
            min_epoch_span_s=float(science.get("min_epoch_span_s", 0.01)),
            max_epoch_span_s=float(science.get("max_epoch_span_s", 120.0)),
            min_trials_for_erp=int(science.get("min_trials_for_erp", 2)),
        ),
        config_path=path,
    )
