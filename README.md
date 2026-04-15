# Code PLAY

Multi-agent game studio platform. Specialized AI agents collaborate autonomously to build web/3D games (Three.js, Roblox).

## Architecture

Centralized FastAPI orchestrator with:
- **Agent Registry** — 21 specialized agents from [agency-agents](https://github.com/msitarzewski/agency-agents)
- **Agent Runtime** — model-agnostic tool-use loop (like Claude Code, but for any LLM)
- **LLM Router** — OpenRouter, oMLX (local), Anthropic direct
- **Shared Tool Pool** — file I/O, bash, git, memory, communication
- **Tool Governance** — built-in tools auto-approved, new tools need human approval
- **Communication Bus** — project channels, @-mentions, human escalation
- **Project Memory** — per-game SQLite knowledge store
- **React Dashboard** — observability, lifecycle management, approvals

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in API keys
python -m src.main
```

## Design

See [docs/design.md](docs/design.md) for the full architecture spec.

## Status

Phase 1 (Foundation) — in progress.
