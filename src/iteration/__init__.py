"""Iteration-loop machinery shared by Mode A (build) and Mode B (iterate).

See docs/iteration_contract.md for the canonical doctrine. Public surface:

- contract: metric vocabulary, aggregate whitelist, validate_goals_md()
- cycle_state: per-project cycle counter + halt flag helpers
- iterate_runner: playtest batch runner (headless Chromium + telemetry rollup)
"""
