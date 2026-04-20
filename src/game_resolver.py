"""Clone/pull game repos so they're available locally for iteration.

External games live in their own git repos. This module ensures a local clone
exists under ``projects/.game-repos/{slug}/`` and is checked out at the active
version's ref. Internal games just resolve to a path inside code-play.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.game_registry import GameEntry, get_active_version

logger = logging.getLogger(__name__)

CLONE_ROOT = Path("projects/.game-repos")


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)


def _clone_or_pull(repo_url: str, dest: Path, ref: str | None, branch: str | None) -> None:
    if not dest.exists():
        dest.mkdir(parents=True, exist_ok=True)
        branch_arg = branch or "main"
        r = _run(["git", "clone", "--depth", "1", "--branch", branch_arg, repo_url, str(dest)])
        if r.returncode != 0:
            r = _run(["git", "clone", repo_url, str(dest)])
            if r.returncode != 0:
                raise RuntimeError(f"git clone failed: {r.stderr.strip()}")
    else:
        _run(["git", "fetch", "origin"], cwd=dest)

    if branch:
        r = _run(["git", "checkout", branch], cwd=dest)
        if r.returncode != 0:
            _run(["git", "checkout", "-b", branch, f"origin/{branch}"], cwd=dest)
        _run(["git", "pull", "--ff-only", "origin", branch], cwd=dest)
    elif ref:
        _run(["git", "checkout", ref], cwd=dest)


def resolve_game_repo(game: GameEntry) -> Path:
    """Ensure game repo is locally available and up-to-date. Returns local path."""
    version = get_active_version(game)

    if game.source.kind == "internal":
        local = Path(game.source.path or "")
        if not local.is_absolute():
            local = Path.cwd() / local
        if not local.is_dir():
            raise FileNotFoundError(f"Internal game path not found: {local}")
        return local

    # external or rojo — need a git clone
    if not game.source.repo:
        raise ValueError(f"Game {game.slug} has kind={game.source.kind} but no source.repo")

    dest = CLONE_ROOT / game.slug
    ref = version.ref if version else None
    branch = version.branch if version else None
    _clone_or_pull(game.source.repo, dest, ref, branch)

    logger.info("Resolved %s → %s (ref=%s, branch=%s)", game.slug, dest, ref, branch)
    return dest
