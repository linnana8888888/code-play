# Iteration Contract (pointer)

This artifact follows the canonical code-play iteration contract:

→ **`code-play/docs/iteration_contract.md`**
   (https://github.com/linnana8888888/code-play/blob/main/docs/iteration_contract.md)

The telemetry schema, the 16-name metric vocabulary that `GOALS.md` may reference,
and the aggregate-function whitelist (`median`, `p25`, `p75`, `rate`) are defined
there. The runtime validator `src/iteration/contract.py` and the test
`tests/test_iteration_contract.py` in code-play lock the vocabulary.

### File paths in this repo

| Artifact | Path |
|---|---|
| Goals doc | `GOALS.md` |
| Bot script | `playtest_bot.mjs` |
| Telemetry dir | `telemetry/` |

### How this artifact is iterated

Run the code-play dashboard's `iterate_artifact` pipeline against this repo.
Each cycle: `playtest → postmortem → propose × 4 → synthesis_gate → implement`,
up to the cycle budget (default 5). See `code-play/docs/phases/iterate_artifact.md`.
