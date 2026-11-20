"""Unit tests for the methodology layer: claims, method profiles and gates.

These tests never start MATLAB.  The rule engine runs in Python against facts
(as reported by MATLAB), so the whole knowledge base can be checked in
milliseconds and any change to a profile is immediately testable.
"""
from __future__ import annotations

import pytest

from eeglab_mcp.gates import (
    ADVISORY,
    BLOCKED,
    OVERRIDE,
    PASS,
    Facts,
    GateError,
    evaluate,
    merge_results,
    resolve_profile,
    validate_catalog,
)
from eeglab_mcp.methodology import load_catalog

CATALOG = load_catalog()


def facts(**overrides) -> Facts:
    """A healthy 32-channel continuous recording, unless overridden."""
    payload = {
        "nbchan": 32,
        "srate": 128.0,
        "pnts": 30504,
        "trials": 1,
        "duration_s": 238.3,
        "nevents": 154,
        "chanlocs": 32,
        "is_continuous": True,
        "is_epoched": False,
        "reference": "common",
        "units": "uV",
        "max_abs": 80.0,
        "rank": 32,
        "event_types": ["square"],
        "channel_names": ["Cz", "Pz", "M1", "M2"],
        "plugins": {"clean_rawdata": True, "ICLabel": True},
        "history": [],
    }
    payload.update(overrides)
    return Facts.from_payload(payload)


def statuses(result) -> dict[str, str]:
    return {item.check: item.status for item in result.items}


# --------------------------------------------------------------------- catalog
def test_catalog_has_47_claims_and_39_profiles():
    assert len(CATALOG.claims) == 47
    assert len(CATALOG.profiles) == 39
    assert CATALOG.claims["EEGLAB-FILT-001"].topic == "FILT"


def test_catalog_is_internally_consistent():
    # Every gate check is registered, every claim reference resolves, and every
    # claim is used by at least one profile.
    assert validate_catalog(CATALOG) == []


def test_every_gate_declares_a_valid_outcome():
    legal = {"pass", "advisory", "blocked", "override_accepted"}
    for prof in CATALOG.profiles.values():
        assert prof.gates, f"{prof.id} 没有任何门控"
        for gate in prof.gates:
            assert gate.on_fail in legal, f"{prof.id}/{gate.check}: {gate.on_fail}"
            assert gate.claim in CATALOG.claims, f"{prof.id}/{gate.check}: {gate.claim}"


def test_claims_cite_a_source():
    for claim in CATALOG.claims.values():
        assert claim.source_title and claim.source_locator, claim.id
        assert claim.statement.strip()


# ------------------------------------------------------------------- resolving
def test_rereference_method_average_is_not_mistaken_for_a_profile_id():
    # ``method`` is a real parameter of pop_reref, so "average" must not be
    # rejected as an unknown method profile.
    prof, matched = resolve_profile("reref", {"method": "average"}, CATALOG)
    assert prof is not None and prof.id == "M-REF-AVG-01" and matched


def test_rereference_rest_profile_is_found_and_marked_not_executable():
    prof, matched = resolve_profile("reref", {"method": "REST"}, CATALOG)
    assert matched and prof.id == "M-REF-REST-01"
    assert prof.executable is False


def test_runica_is_preferred_over_the_iclabel_profile():
    prof, matched = resolve_profile("ica", {"algorithm": "runica"}, CATALOG)
    assert matched and prof.id == "M-ICA-RUNICA-01"


def test_unknown_parameters_fall_back_to_an_adhoc_profile():
    prof, matched = resolve_profile(
        "filter", {"highpass_hz": 2.0, "lowpass_hz": 25.0}, CATALOG
    )
    assert matched is False
    assert prof.id == "M-ADHOC-FILTER"
    assert prof.gates  # the action's checks still apply


def test_unknown_method_id_raises():
    with pytest.raises(GateError) as exc:
        evaluate("filter", {"highpass_hz": 1.0}, facts(), method_id="M-DOES-NOT-EXIST")
    assert exc.value.code == "METHOD_NOT_FOUND"


# ---------------------------------------------------------------------- gates
def test_lowpass_above_nyquist_is_blocked_even_without_a_matching_profile():
    # 128 Hz data: a 100 Hz lowpass is impossible. M-FILT-SPEC-01 matches these
    # parameters exactly, so this also proves the safety gate is appended.
    result = evaluate(
        "filter", {"highpass_hz": 0.5, "lowpass_hz": 100.0}, facts(srate=128.0)
    )
    assert result.status == BLOCKED
    assert statuses(result)["nyquist_lowpass"] == BLOCKED
    blocked = [i for i in result.items if i.status == BLOCKED][0]
    assert "奈奎斯特" in blocked.observed
    assert any(c["id"] == "EEGLAB-FILT-003" for c in result.claims)


def test_notch_above_nyquist_is_blocked():
    result = evaluate("filter", {"notch_hz": 100.0}, facts(srate=128.0))
    assert result.status == BLOCKED
    assert statuses(result)["nyquist_notch"] == BLOCKED


def test_ica_on_epoched_data_is_blocked():
    f = facts(is_continuous=False, is_epoched=True, trials=80,
              tmin_s=-0.2, tmax_s=0.8, rank=32)
    result = evaluate("ica", {"algorithm": "runica"}, f)
    assert result.status == BLOCKED
    assert statuses(result)["ica_input_continuous"] == BLOCKED


def test_ica_with_too_little_data_is_blocked():
    result = evaluate("ica", {"algorithm": "runica"},
                      facts(nbchan=32, pnts=400, trials=1, duration_s=3.1))
    assert result.status == BLOCKED
    assert statuses(result)["ica_sample_sufficiency"] == BLOCKED


def test_epoch_span_shorter_than_200_ms_is_flagged():
    # A 100 ms window is a methodological risk, not an impossibility: EEGLAB
    # will segment it. The gate therefore advises rather than blocks.
    result = evaluate("epoch", {"tmin_s": -0.05, "tmax_s": 0.05}, facts())
    assert result.status == ADVISORY
    assert statuses(result)["epoch_span"] == ADVISORY


def test_baseline_starting_before_the_epoch_is_blocked():
    f = facts(is_continuous=False, is_epoched=True, trials=80,
              tmin_s=-0.2, tmax_s=0.8)
    result = evaluate("baseline",
                      {"baseline_start_s": -0.5, "baseline_end_s": 0.0}, f)
    assert result.status == BLOCKED
    assert statuses(result)["baseline_within_epoch"] == BLOCKED


def test_baseline_ending_after_the_stimulus_is_blocked():
    f = facts(is_continuous=False, is_epoched=True, trials=80,
              tmin_s=-0.2, tmax_s=0.8)
    result = evaluate("baseline",
                      {"baseline_start_s": -0.2, "baseline_end_s": 0.2}, f)
    assert result.status == BLOCKED
    assert statuses(result)["baseline_before_stimulus"] == BLOCKED


def test_asr_is_blocked_when_the_plugin_is_missing():
    result = evaluate("asr", {"asr_cutoff": 20}, facts(plugins={}))
    assert result.status == BLOCKED
    blocked = [i for i in result.items if i.check == "plugin_available"][0]
    assert blocked.status == BLOCKED
    assert "clean_rawdata" in blocked.observed


def test_asr_is_blocked_even_with_the_plugin_until_it_is_implemented():
    result = evaluate("asr", {"asr_cutoff": 20},
                      facts(plugins={"clean_rawdata": True}))
    assert result.status == BLOCKED
    assert statuses(result)["capability_available"] == BLOCKED


def test_statistics_profile_is_not_executable():
    f = facts(is_continuous=False, is_epoched=True, trials=40,
              tmin_s=-0.2, tmax_s=0.8)
    result = evaluate("stats", {"test": "paired_t"}, f)
    assert result.status == BLOCKED
    assert result.executable is False
    assert statuses(result)["capability_available"] == BLOCKED


def test_advisory_only_result_does_not_block():
    # A 0.1 Hz highpass on a 2 s recording gives a boundary transient longer
    # than the data: a real risk, surfaced as advice rather than a refusal.
    result = evaluate("filter", {"highpass_hz": 0.1, "lowpass_hz": 30.0},
                      facts(duration_s=2.0))
    assert result.status == ADVISORY
    assert statuses(result)["filter_order_vs_length"] == ADVISORY
    assert result.blocked is False
    assert "EEGLAB-FILT-004" in {c["id"] for c in result.claims}


def test_clean_parameters_pass():
    result = evaluate("filter", {"highpass_hz": 0.1, "lowpass_hz": 30.0}, facts())
    assert result.status == PASS
    assert result.blocked is False
    assert all(i.status == PASS for i in result.items)


# -------------------------------------------------------------------- override
def test_override_without_a_reason_is_rejected():
    with pytest.raises(GateError) as exc:
        evaluate("filter", {"notch_hz": 100.0}, facts(srate=128.0),
                 override_gate=True, override_reason="继续")
    assert exc.value.code == "GATE_OVERRIDE_REASON_REQUIRED"


def test_override_records_the_reason_and_keeps_the_blocked_items():
    result = evaluate(
        "filter", {"notch_hz": 100.0}, facts(srate=128.0),
        override_gate=True,
        override_reason="该数据由采集系统上采样至 128 Hz，陷波在采集端完成，此处仅记录。",
    )
    assert result.status == OVERRIDE
    assert result.override["accepted"] is True
    assert "nyquist_notch" in result.override["overridden_checks"]
    # The evidence is not erased: the blocked item is still in the result.
    assert statuses(result)["nyquist_notch"] == BLOCKED


def test_override_has_no_effect_when_nothing_is_blocked():
    result = evaluate("filter", {"highpass_hz": 0.1, "lowpass_hz": 30.0},
                      facts(), override_gate=True, override_reason="x" * 25)
    assert result.status == PASS
    assert result.override["accepted"] is False


# ----------------------------------------------------------------------- merge
def test_merge_of_pipeline_stages_keeps_the_worst_status():
    blocked = evaluate("filter", {"notch_hz": 100.0}, facts(srate=128.0))
    clean = evaluate("epoch", {"tmin_s": -0.2, "tmax_s": 0.8}, facts())
    merged = merge_results("erp_analysis", [blocked, clean])
    assert merged.status == BLOCKED
    assert len(merged.items) == len(blocked.items) + len(clean.items)
    assert merged.method_id == f"{blocked.method_id} + {clean.method_id}"


def test_merge_deduplicates_claims():
    a = evaluate("filter", {"highpass_hz": 0.1, "lowpass_hz": 30.0}, facts())
    b = evaluate("filter", {"highpass_hz": 0.1, "lowpass_hz": 30.0}, facts())
    merged = merge_results("pipeline", [a, b])
    ids = [c["id"] for c in merged.claims]
    assert len(ids) == len(set(ids))
