"""Integration tests: these start a real MATLAB/EEGLAB process (~30-60 s each).

Run with:  pytest -m integration
"""
from __future__ import annotations

import pytest

from eeglab_mcp.config import ConfigError, load_settings
from eeglab_mcp.tools import Tools

pytestmark = pytest.mark.integration

try:
    SETTINGS = load_settings()
except ConfigError as exc:  # no local config: keep collection working in CI
    pytest.skip(f"MATLAB integration tests need a local config: {exc}",
                allow_module_level=True)
SAMPLE = str(SETTINGS.eeglab.root / "sample_data" / "eeglab_data.set")
T = Tools(SETTINGS)


def test_status_reports_real_versions():
    r = T.get_status()
    assert r["success"] is True
    d = r["result"]
    assert d["matlab_release"].startswith("2023")
    assert d["all_core_available"] is True
    names = d["functions"]["name"]
    assert "pop_loadset" in names
    assert all(d["functions"]["available"])


def test_inspect_returns_measured_values():
    r = T.inspect_dataset(SAMPLE)
    assert r["success"] is True, r["errors"]
    d = r["result"]
    # Values verified independently in MATLAB against this dataset
    assert d["sampling_rate_hz"] == 128
    assert d["channel_count"] == 32
    assert d["points"] == 30504
    assert d["event_count"] == 154
    assert d["all_finite"] is True
    # This dataset genuinely has no channel locations; the tool must say so.
    assert d["chanlocs_count"] == 0
    assert any("Channel locations" in w for w in r["warnings"])


def test_erp_pipeline_end_to_end():
    r = T.run_pipeline(SAMPLE, "erp_analysis", event_types=["square"])
    assert r["success"] is True, r["errors"]
    d = r["result"]
    assert d["trials"] >= 2
    assert d["channel_count"] == 32
    assert len(d["erp_times_s"]) == len(d["erp_gfp_uv"])
    assert any(a["kind"] == "eeglab_set" for a in r["artifacts"])
    assert all(a["sha256"] for a in r["artifacts"])


def test_rejects_unknown_pipeline():
    r = T.run_pipeline(SAMPLE, "run_anything")
    assert r["success"] is False
    assert r["errors"][0]["code"] == "BAD_PARAMS"


def test_rejects_outside_path():
    r = T.inspect_dataset("C:/Windows/notepad.exe")
    assert r["success"] is False
    assert r["errors"][0]["code"] in ("PATH_NOT_ALLOWED", "UNSUPPORTED_FORMAT")


# ---------------------------------------------------------------- P2 tools
EDF = str(SETTINGS.paths.allowed_input_roots[1] / "test_raw.edf") if len(
    SETTINGS.paths.allowed_input_roots) > 1 else ""


def test_import_edf_converts_to_set():
    import os

    if not EDF or not os.path.isfile(EDF):
        pytest.skip("test_raw.edf not present")
    r = T.import_data(EDF)
    assert r["success"] is True, r["errors"]
    d = r["result"]
    assert d["source_format"] == ".edf"
    assert d["channel_count"] == 8
    assert d["sampling_rate_hz"] == 256
    assert d["original_untouched"] is True
    assert len(d["original_sha256"]) == 64


def test_batch_inspect_multiple_files():
    files = [SAMPLE, SAMPLE]
    r = T.batch_process(files, mode="inspect")
    assert r["success"] is True, r["errors"]
    d = r["result"]
    assert d["total"] == 2
    assert d["succeeded"] == 2
    assert d["failed"] == 0
    assert all(it["ok"] for it in d["items"])


def test_batch_rejects_unknown_pipeline():
    r = T.batch_process([SAMPLE], mode="pipeline", pipeline="nope")
    assert r["success"] is False
    assert r["errors"][0]["code"] == "BAD_PARAMS"


def test_export_long_table_schema():
    pipe = T.run_pipeline(SAMPLE, "erp_analysis", event_types=["square"])
    assert pipe["success"] is True
    epoched = [a["path"] for a in pipe["artifacts"] if a["kind"] == "eeglab_set"][0]
    r = T.export_long_table(epoched, 0.25, 0.45, subject_id="sub-test")
    assert r["success"] is True, r["errors"]
    d = r["result"]
    assert d["schema"] == "subject,condition,channel,mean_uv,trial"
    assert d["rows"] == d["channels"] * d["trials"]
    csv = [a for a in r["artifacts"] if a["kind"] == "long_table_csv"][0]
    header = open(csv["path"], encoding="utf-8").readline().strip()
    assert header == d["schema"]
