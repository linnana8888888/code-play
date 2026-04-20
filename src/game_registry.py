"""Typed loader for the games/*.yaml catalog.

Each YAML file describes a game title, its source location, and version history.
This module reads them into dataclasses so the rest of the codebase can reference
games programmatically instead of via agent-prompt file reads.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.settings import settings

logger = logging.getLogger(__name__)

GAMES_DIR = Path(settings.config_dir).parent / "games"


@dataclass
class GameSource:
    kind: str  # external | internal | rojo
    repo: str | None = None
    path: str | None = None
    project: str | None = None  # rojo only


@dataclass
class GameVersion:
    label: str
    ref: str
    status: str
    branch: str | None = None
    entry: str | None = None
    rojo_entry: str | None = None
    released_at: str | None = None
    shipped_as: str | None = None
    notes: str = ""
    published: dict[str, str | None] = field(default_factory=dict)


@dataclass
class GameEntry:
    slug: str
    title: str
    status: str
    source: GameSource
    versions: list[GameVersion] = field(default_factory=list)


def _parse_version(raw: dict) -> GameVersion:
    return GameVersion(
        label=raw.get("label", ""),
        ref=str(raw.get("ref", "")),
        status=raw.get("status", "draft"),
        branch=raw.get("branch"),
        entry=raw.get("entry"),
        rojo_entry=raw.get("rojo_entry"),
        released_at=str(raw["released_at"]) if raw.get("released_at") else None,
        shipped_as=raw.get("shipped_as"),
        notes=raw.get("notes", ""),
        published=raw.get("published") or {},
    )


def _parse_game(path: Path) -> GameEntry | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to parse %s", path)
        return None
    if not isinstance(data, dict) or "slug" not in data:
        return None

    src = data.get("source", {})
    source = GameSource(
        kind=src.get("kind", "external"),
        repo=src.get("repo"),
        path=src.get("path"),
        project=src.get("project"),
    )

    versions = [_parse_version(v) for v in data.get("versions", [])]

    return GameEntry(
        slug=data["slug"],
        title=data.get("title", data["slug"]),
        status=data.get("status", "active"),
        source=source,
        versions=versions,
    )


def list_games() -> list[GameEntry]:
    if not GAMES_DIR.is_dir():
        return []
    entries: list[GameEntry] = []
    for p in sorted(GAMES_DIR.glob("*.yaml")):
        entry = _parse_game(p)
        if entry:
            entries.append(entry)
    return entries


def get_game(slug: str) -> GameEntry | None:
    path = GAMES_DIR / f"{slug}.yaml"
    if not path.is_file():
        return None
    return _parse_game(path)


def get_active_version(game: GameEntry) -> GameVersion | None:
    for v in reversed(game.versions):
        if v.status in ("active", "shipped", "qa-passing"):
            return v
    return game.versions[-1] if game.versions else None
