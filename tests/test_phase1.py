"""Phase 1 QA tests:
- validate_artifact_content schema rules
- _check_playtest_thresholds quality gate
- _CD_VERDICT_RE parser behaviour
"""
from __future__ import annotations

import re

import pytest

from src.runtime.task_validator import validate_artifact_content
from src.iteration.iterate_runner import _check_playtest_thresholds


# ── validate_artifact_content ────────────────────────────────────────────────


def test_mechanics_v1_valid_has_no_errors():
    value = {
        "player_verbs": ["run", "jump"],
        "progression": "3 levels of rising intensity",
        "win_condition": "reach the flag",
        "lose_condition": "fall off map",
        "signature_systems": ["coyote-time", "double-jump"],
    }
    assert validate_artifact_content("mechanics_v1", value) == []


def test_mechanics_v1_missing_win_condition_reports_error():
    value = {
        "player_verbs": ["run", "jump"],
        "progression": "levels",
        "lose_condition": "die",
        "signature_systems": ["a", "b"],
    }
    errors = validate_artifact_content("mechanics_v1", value)
    assert any("win_condition" in e for e in errors)


def test_mechanics_v1_player_verbs_string_reports_type_error():
    value = {
        "player_verbs": "run, jump",  # should be list
        "progression": "x",
        "win_condition": "y",
        "lose_condition": "z",
        "signature_systems": ["a", "b"],
    }
    errors = validate_artifact_content("mechanics_v1", value)
    assert any("player_verbs" in e and "expected list" in e for e in errors)


def test_concept_options_v1_two_directions_fails_min_items():
    value = {
        "directions": [
            {"pitch": "a", "core_loop": "b", "target_feel": "c"},
            {"pitch": "a", "core_loop": "b", "target_feel": "c"},
        ]
    }
    errors = validate_artifact_content("concept_options_v1", value)
    assert any("at least 3" in e for e in errors)


def test_concept_options_v1_direction_missing_pitch_reports_error():
    value = {
        "directions": [
            {"pitch": "a", "core_loop": "b", "target_feel": "c"},
            {"core_loop": "b", "target_feel": "c"},  # missing pitch
            {"pitch": "a", "core_loop": "b", "target_feel": "c"},
        ]
    }
    errors = validate_artifact_content("concept_options_v1", value)
    assert any("pitch" in e and "[1]" in e for e in errors)


def test_game_html_v1_short_string_fails_min_bytes():
    errors = validate_artifact_content("game_html_v1", "<html></html>")
    assert any("too short" in e for e in errors)


def test_game_html_v1_long_string_passes():
    big = "<html>" + ("x" * 2000) + "</html>"
    assert validate_artifact_content("game_html_v1", big) == []


def test_unknown_artifact_key_is_graceful():
    assert validate_artifact_content("totally_fake_key_v9", {"foo": "bar"}) == []


def test_artifact_value_none_does_not_crash():
    # Must not raise; returns [] since dict-path skipped
    assert validate_artifact_content("mechanics_v1", None) == []


def test_artifact_value_empty_dict_reports_missing_required():
    errors = validate_artifact_content("mechanics_v1", {})
    # All 5 required fields should be flagged as missing
    assert len([e for e in errors if "missing required field" in e]) == 5


# ── _check_playtest_thresholds ────────────────────────────────────────────────


def _session(duration_s, deaths=0, level=1):
    return {
        "duration_seconds": duration_s,
        "events": [{"type": "death", "level": level} for _ in range(deaths)],
    }


def test_playtest_passes_with_good_session_and_low_deaths():
    data = {"sessions": [_session(120, deaths=3), _session(120, deaths=3)]}
    # 3 deaths per 2 minutes = 1.5/min
    passes, reason = _check_playtest_thresholds(data)
    assert passes, reason


def test_playtest_fails_short_session():
    data = {"sessions": [_session(60), _session(60)]}
    passes, reason = _check_playtest_thresholds(data)
    assert not passes
    assert "Session too short" in reason


def test_playtest_fails_high_death_rate():
    # 120s session with 8 deaths = 4/min
    data = {"sessions": [_session(120, deaths=8)]}
    passes, reason = _check_playtest_thresholds(data)
    assert not passes
    assert "Death rate too high" in reason


def test_playtest_empty_sessions_fails():
    passes, reason = _check_playtest_thresholds({"sessions": []})
    assert not passes
    assert "No playtest sessions recorded" in reason


def test_playtest_missing_sessions_key_fails_gracefully():
    passes, reason = _check_playtest_thresholds({})
    assert not passes
    assert "No playtest sessions" in reason


def test_playtest_sessions_missing_events_no_crash():
    # No 'events' key -> should default to [] and death-rate 0
    data = {"sessions": [{"duration_seconds": 120}, {"duration_seconds": 150}]}
    passes, reason = _check_playtest_thresholds(data)
    assert passes, reason


# ── CD verdict parser ────────────────────────────────────────────────────────

# Import the regex from main.py; main.py has FastAPI side effects at import
# time, but we only need the compiled pattern. Re-define the same regex here
# (parity with main.py `_CD_VERDICT_RE`) to avoid import cost. If these ever
# diverge, the test intentionally locks down the expected shape.

_CD_VERDICT_RE = re.compile(
    r"\[CD-[A-Z]+\]:\s*(APPROVE|CONCERNS|REJECT)(.*?)(?=\n|$)",
    re.IGNORECASE,
)


def _parse(text):
    m = _CD_VERDICT_RE.search(text)
    if not m:
        return None, ""
    verdict = m.group(1).upper()
    reason = m.group(2).strip().lstrip(":").strip()
    return verdict, reason


def test_cd_reject_with_reason():
    v, r = _parse("[CD-CONCEPT]: REJECT — missing core fantasy")
    assert v == "REJECT"
    assert "missing core fantasy" in r


def test_cd_approve_no_reason():
    v, r = _parse("[CD-MECHANICS]: APPROVE")
    assert v == "APPROVE"
    assert r == ""


def test_cd_concerns_with_reason():
    v, r = _parse("[CD-LAF]: CONCERNS — palette too dark")
    assert v == "CONCERNS"
    assert "palette too dark" in r


def test_cd_regex_also_matches_main_module_constant():
    """Sanity: main.py's _CD_VERDICT_RE produces the same match behaviour."""
    import importlib
    try:
        main_mod = importlib.import_module("src.main")
    except Exception:
        pytest.skip("src.main not importable in test env")
    m = main_mod._CD_VERDICT_RE.search("[CD-CONCEPT]: REJECT — reason")
    assert m and m.group(1).upper() == "REJECT"
