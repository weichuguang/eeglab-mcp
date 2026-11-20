"""Unit tests for path and parameter safety (no MATLAB required)."""
from __future__ import annotations

from pathlib import Path

import pytest

from eeglab_mcp.config import (
    EeglabConfig,
    LimitsConfig,
    MatlabConfig,
    PathsConfig,
    ScienceConfig,
    Settings,
)
from eeglab_mcp.security import SecurityError, require_range, resolve_input


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    (data / "eeglab_data.set").write_bytes(b"")
    out = tmp_path / "outputs"
    out.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    return Settings(
        matlab=MatlabConfig(
            executable=Path("matlab"),
            timeout_seconds=60,
            driver_dir=tmp_path / "matlab",
            use_persistent_worker=False,
            worker_idle_seconds=60,
        ),
        eeglab=EeglabConfig(root=tmp_path / "eeglab"),
        paths=PathsConfig(
            allowed_input_roots=(data,),
            output_root=out,
            log_root=logs,
        ),
        limits=LimitsConfig(max_input_mb=16, max_array_points=300, max_batch_files=10),
        science=ScienceConfig(
            max_lowpass_ratio=0.95,
            min_epoch_span_s=0.01,
            max_epoch_span_s=120.0,
            min_trials_for_erp=2,
        ),
        config_path=tmp_path / "config.yaml",
    )


def test_dataset_inside_an_allowed_root(settings: Settings):
    sample = settings.paths.allowed_input_roots[0] / "eeglab_data.set"
    p = resolve_input(str(sample), settings)
    assert p.is_file()
    assert p.suffix == ".set"


@pytest.mark.parametrize(
    "value,code",
    [
        ("", "EMPTY_PATH"),
        ("relative/path.set", "RELATIVE_PATH"),
    ],
)
def test_rejects_bad_paths(settings: Settings, value: str, code: str):
    with pytest.raises(SecurityError) as exc:
        resolve_input(value, settings)
    assert exc.value.code == code


def test_rejects_file_outside_allowed_roots(settings: Settings, tmp_path: Path):
    outside = tmp_path / "outside.set"
    outside.write_bytes(b"")
    with pytest.raises(SecurityError) as exc:
        resolve_input(str(outside), settings)
    assert exc.value.code == "PATH_NOT_ALLOWED"


def test_rejects_directory_traversal(settings: Settings, tmp_path: Path):
    outside = tmp_path / "escape.set"
    outside.write_bytes(b"")
    sneaky = str(settings.paths.allowed_input_roots[0] / ".." / "escape.set")
    with pytest.raises(SecurityError) as exc:
        resolve_input(sneaky, settings)
    assert exc.value.code == "PATH_NOT_ALLOWED"


def test_rejects_missing_file(settings: Settings):
    missing = settings.paths.allowed_input_roots[0] / "does_not_exist.set"
    with pytest.raises(SecurityError) as exc:
        resolve_input(str(missing), settings)
    assert exc.value.code == "FILE_NOT_FOUND"


def test_rejects_non_set_format(settings: Settings):
    f = settings.paths.allowed_input_roots[0] / "x.txt"
    f.write_text("hi")
    with pytest.raises(SecurityError) as exc:
        resolve_input(str(f), settings)
    assert exc.value.code == "UNSUPPORTED_FORMAT"


def test_require_range_accepts_and_rejects():
    assert require_range("x", 10, 0, 20) == 10.0
    with pytest.raises(SecurityError):
        require_range("x", 25, 0, 20)
    with pytest.raises(SecurityError):
        require_range("x", "abc", 0, 20)
