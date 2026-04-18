"""One-off demo: run mechanic-researcher against a tight Roblox obby prompt.

Uses Sonnet 4.6 (fallback) for budget control. Streams turns to stdout.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.orchestrator.agent_registry import registry
from src.runtime.agent_runtime import agent_runtime
from src.runtime.skill_registry import skill_registry
from src.runtime.tool_executor import tool_executor


PROMPT = """You are being invoked as an ideation-phase researcher. The producer is
considering a new Roblox obby experience targeted at kids aged 7-12. Before any
concept brief is written, give us an `ideation_input_v1` teardown.

Constraints to honor:
- Pick 3 currently popular Roblox obby experiences with verifiable traction
  signals (CCU, visit count, rating) — don't guess.
- For each: tick-by-tick core loop in <=60 seconds of play.
- Session shape (avg run, failure state, retry friction) + retention hooks ranked.
- Steal list: 3-5 concrete mechanics with how-to-port notes a Roblox dev could scope.
- Anti-steal list: things that work there but would fight a kids-focused concept.
- 2-3 mash-up hypotheses.
- 3 open questions for the designer.

Keep the total output under ~1500 words. Use web_search and web_fetch freely.
Do NOT attempt to write to project memory — this is a dry run without a project.
Just produce the brief inline as your final message.
"""


async def main():
    registry.load_config()
    registry.load_agents()
    skill_registry.load_skills()
    skill_registry.load_governance()
    tool_executor.load_governance()

    # Force the cheap model
    instance = registry.spawn(
        agent_type="mechanic-researcher",
        project_id=None,
        model_override="anthropic/anthropic.claude-sonnet-4-6",
    )
    # Budget: 250k — perplexity tool results are chunky (full article text),
    # so an obby brief with 5-6 research calls + final synthesis needs headroom.
    instance.budget_max_tokens = 250000

    print(f"# Spawned {instance.id} on {instance.model}\n", flush=True)

    out_file = ROOT / "artifacts" / "mechanic-researcher-demo.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with out_file.open("w", encoding="utf-8") as f:
        f.write(f"# Mechanic Researcher Demo Run\n\nInstance: `{instance.id}` · Model: `{instance.model}`\n\n---\n\n")
        turn_count = 0
        async for turn in agent_runtime.run(instance, PROMPT):
            turn_count += 1
            header = f"## Turn {turn_count} — {turn.role}"
            print(header)
            f.write(f"\n{header}\n\n")
            if turn.tool_calls:
                for tc in turn.tool_calls:
                    line = f"- tool: **{tc.name}** args={str(tc.arguments)[:200]}"
                    print(line)
                    f.write(line + "\n")
            if turn.content:
                # Full body to file; trim stdout to keep the terminal readable.
                print(turn.content[:3000])
                if len(turn.content) > 3000:
                    print(f"[… +{len(turn.content)-3000} chars truncated in stdout; full content in artifact]")
                f.write(turn.content + "\n")
            if turn_count >= 25:
                print("# [turn cap hit — stopping]")
                break

    print(f"\n# Tokens used: {instance.tokens_used}/{instance.budget_max_tokens}")
    print(f"# Output saved → {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
