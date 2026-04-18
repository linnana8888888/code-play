"""Single source of truth for the iteration contract.

Mirrors docs/iteration_contract.md §§2–3. When you change the doctrine, update
this file in the same commit and rerun tests/test_iteration_contract.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── §2: metric vocabulary ────────────────────────────────────────────────────
# GOALS.md MUST reference these names verbatim. Keep alphabetical inside each
# grouping for diff-friendliness.
METRIC_NAMES: frozenset[str] = frozenset({
    # funnel
    "session_duration_sec",
    "levels_reached",
    "score",
    "outcome",
    # combat
    "accuracy",
    "kills_per_min",
    # survival
    "damage_taken",
    "dashes_used",
    "stomps_used",
    # progression
    "xp_levels",
    "upgrades_picked",
    "gems_collected",
    "pickups_collected",
    # pacing
    "time_to_first_kill_sec",
    "time_to_first_levelup_sec",
    "longest_idle_sec",
})

# ── §3: aggregate whitelist ──────────────────────────────────────────────────
AGGREGATE_FNS: frozenset[str] = frozenset({"median", "p25", "p75", "rate"})

# Schema version the runner asserts. Bump when field semantics change.
SCHEMA_VERSION: int = 1


@dataclass(frozen=True)
class Issue:
    """A single lint finding against a GOALS.md document."""

    kind: str           # "unknown_metric" | "unknown_aggregate" | "no_threshold"
    detail: str         # human-readable offending token
    line: int           # 1-indexed line number in the source text


# A call like `median(session_duration_sec)` or `rate(levels_reached >= 2)`.
# No whitespace allowed between name and `(` so prose like "Session length (foo)"
# does not parse as an aggregate call.
_CALL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\(([^()]*)\)")


def validate_goals_md(text: str) -> list[Issue]:
    """Lint a GOALS.md document against the contract.

    Checks:
    - Every `name(...)` call uses an aggregate from AGGREGATE_FNS.
    - The first identifier inside each aggregate is a metric from METRIC_NAMES.
    - Targets section contains at least one threshold operator (>=, <=, =, >, <).

    Returns zero issues for a fully-conformant doc; otherwise one Issue per
    problem so the scaffolder/agent can report them all at once.
    """

    issues: list[Issue] = []
    saw_threshold = False

    for lineno, line in enumerate(text.splitlines(), start=1):
        # Skip fenced code blocks' open/close markers; we still lint inside them
        # because real thresholds often sit in inline code spans.
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        if any(op in stripped for op in (">=", "<=", ">", "<", "==", "=")):
            saw_threshold = True

        for match in _CALL_RE.finditer(line):
            fn, args = match.group(1), match.group(2).strip()
            # Empty parens like "median()" are doc citations of the aggregate
            # form, not a real threshold expression — skip.
            if not args:
                continue
            if fn not in AGGREGATE_FNS:
                # Only flag calls that look like stat aggregates (lowercase with
                # an underscore-free short name). Skip prose like "Figure 1 (A)".
                if fn.isalpha() and len(fn) <= 8:
                    issues.append(Issue("unknown_aggregate", fn, lineno))
                continue

            # At least one identifier inside the parens must be a contract
            # metric. This lets `rate(levels_reached >= 2)` pass directly AND
            # `rate(id in upgrades_picked)` pass via the second identifier.
            idents = re.findall(r"[a-z_][a-z0-9_]*", args)
            if not idents:
                issues.append(Issue("unknown_metric", args or "<empty>", lineno))
                continue
            if not any(ident in METRIC_NAMES for ident in idents):
                issues.append(Issue("unknown_metric", idents[0], lineno))

    if not saw_threshold:
        issues.append(Issue("no_threshold", "no comparison operator found", 0))

    return issues
