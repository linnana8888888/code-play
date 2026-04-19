---
name: Testing Patterns
description: Test philosophy, structure, and tooling conventions for the code-play studio
---

# Testing Patterns

## Philosophy
- Tests exist to catch regressions and to document intent. If a test can't fail for a real reason, delete it.
- Prefer **integration tests against real seams** over unit tests of trivial internals.
- A test that mocks the thing under test is not a test.
- Flaky tests are worse than no tests — quarantine or fix; never "re-run until green."

## Test Types (when to use which)

**Unit** — pure functions, algorithms, parsers. Fast, no IO, no network.
**Integration** — crosses a real boundary (DB, HTTP, filesystem, another service). Use a real dependency (test DB, httpx.MockTransport, temp dirs).
**E2E / Playtest** — drives the built artifact through its real UI. For web games: `playwright_browser` against `file://` or local server. For Roblox: Rojo test place + Studio automation.
**Smoke** — one cheap call per external integration to confirm credentials + connectivity. Run in CI, not on every keystroke.

Pick the *lowest* tier that can actually catch the bug you care about.

## Structure
- Mirror the source tree: `src/foo/bar.py` → `tests/foo/test_bar.py`.
- Test names are full sentences: `test_rate_limit_returns_structured_status_not_exception`.
- Arrange / Act / Assert blocks, separated by blank lines. No clever helpers that hide the *act*.
- One behavior per test. If the name contains "and", split it.

## Fixtures
- Factories over fixtures when the shape varies (e.g., `make_project(name="...", stage=...)`).
- Keep fixtures local first; promote to `conftest.py` only when reused 3+ times.
- Never share mutable state between tests; each test must pass in isolation *and* in any order.

## Mocking Rules
- Mock at the **boundary** (HTTP client, DB driver, LLM router), never the unit under test.
- Prefer `httpx.MockTransport` / `respx` over monkey-patching methods — asserts happen at the wire shape.
- Record real responses once (fixture JSON), replay deterministically. Don't hand-craft exotic payloads.
- **Never mock the database in integration tests.** Spin up a real test DB. Mock/prod divergence hides real bugs (this has bitten the studio before — it's why the rule exists).

## LLM / Agent Tests
- Use `LLMRequest` with a deterministic canned response; assert on the *tool calls the agent made*, not the model's prose.
- For flows with tool use, record the full `(request, response, tool_result)` tuple as a fixture and replay.
- Never assert on model output word-by-word; assert on structured fields (`status`, `citations`, `schema keys`).

## Playtest QA (web games)
- Load the real HTML via `playwright_browser`, not a rebuilt DOM.
- Assert on `window.__game` shape *and* on observable behavior (screenshots, console errors).
- Exercise the golden path end-to-end, then one failure-mode per core mechanic.
- Save screenshots + console log + network trace to `artifacts/` on every failure.

## CI Discipline
- Red main = everyone stops merging. Fix forward or revert within 1 hour.
- Slow tests (>5s) get a `@pytest.mark.slow` tag and run on nightly, not PR.
- Test output should be silent on success, loud on failure. No `print` debug shrapnel.

## Anti-Patterns (don't)
- `try/except: pass` around assertions
- `time.sleep(5)` instead of waiting for a condition
- Asserting on the count of items when the content matters
- "Tests pass locally" — if it's not in CI, it doesn't count
