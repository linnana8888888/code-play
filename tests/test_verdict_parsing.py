"""Tests for src.main._parse_verdict.

The code-reviewer emits a `VERDICT:` line on the final line of its review.
The orchestrator greps for it to drive the review↔implementer fix-loop. Any
non-matching shape must fall back to REVISE — silent APPROVE on malformed
reviews is exactly the failure mode the loop is built to prevent.
"""
from __future__ import annotations

from src.main import _parse_verdict


def test_empty_text_returns_revise():
    assert _parse_verdict("") == "REVISE"
    assert _parse_verdict(None) == "REVISE"


def test_plain_approve():
    assert _parse_verdict("all good\n\nVERDICT: APPROVE") == "APPROVE"


def test_plain_revise():
    assert _parse_verdict("see issues\n\nVERDICT: REVISE") == "REVISE"


def test_approve_with_fixes_normalizes():
    assert _parse_verdict("ok\n\nVERDICT: APPROVE WITH FIXES") == "APPROVE_WITH_FIXES"


def test_extra_whitespace_in_keyword_still_parsed():
    assert _parse_verdict("ok\nVERDICT:   APPROVE   WITH   FIXES\n") == "APPROVE_WITH_FIXES"


def test_case_insensitive():
    assert _parse_verdict("\nverdict: approve\n") == "APPROVE"
    assert _parse_verdict("Verdict: Revise") == "REVISE"


def test_last_verdict_wins():
    """Drafts / examples earlier in the review shouldn't mislead the parser."""
    txt = "template:\nVERDICT: APPROVE\nactual review:\n...\nVERDICT: REVISE"
    assert _parse_verdict(txt) == "REVISE"


def test_no_verdict_line_returns_revise():
    """Missing verdict = malformed review = treat as REVISE (never silent APPROVE)."""
    assert _parse_verdict("long review with no verdict line at all") == "REVISE"


def test_trailing_period_tolerated():
    assert _parse_verdict("VERDICT: APPROVE.") == "APPROVE"


def test_verdict_not_on_own_line_rejected():
    """Parser requires a line whose trimmed content starts with VERDICT:.
    Inline mentions like 'final VERDICT: APPROVE was skipped' must NOT count."""
    inline = "the final VERDICT: APPROVE was skipped in favor of extended review"
    assert _parse_verdict(inline) == "REVISE"


def test_parenthetical_suffix_after_keyword_is_not_matched():
    """Diff-aware suffix on the SAME line isn't parsed — only the bare keyword.
    Authoring guidance (in code-reviewer.md) permits the suffix, so a reviewer
    who writes `VERDICT: REVISE (1 of 2 resolved)` should still be read as REVISE.

    Current parser is strict: anything after the keyword except a trailing
    period breaks the match, so such lines fall back to REVISE. For REVISE
    that's benign; for APPROVE with a suffix it would be a false REVISE.
    Lock the conservative behavior here so the author knows.
    """
    assert _parse_verdict("VERDICT: REVISE (1 of 2 resolved)") == "REVISE"
    # APPROVE with suffix would ALSO be demoted to REVISE — safe side.
    assert _parse_verdict("VERDICT: APPROVE (all blockers fixed)") == "REVISE"


def test_unknown_keyword_returns_revise():
    assert _parse_verdict("VERDICT: LGTM") == "REVISE"
    assert _parse_verdict("VERDICT: APPROVED") == "REVISE"
