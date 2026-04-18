"""Iteration artifact scaffolder.

Emits the four-file iteration kit into a newly-built game's artifact repo:

  - ITERATION_CONTRACT.md : pointer back to code-play doctrine
  - GOALS.md              : placeholder targets from template
  - playtest_bot.mjs      : parameterized bot from template
  - telemetry/.gitkeep    : so cycle 1 has an empty dir to write into
  - .codeplay/config.yaml : per-repo iteration settings

Memory hooks: writes `iteration_contract_path`, `goals_path`,
`playtest_bot_path`, and `scaffolded_at` keys (type="iteration") so the
iterate_runner / postmortem agents can find them without re-deriving paths.

Called from the `scaffold-iteration` tail step of phased-producer pipelines
(see config/pipelines.yaml). Also directly invokable in tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.memory.project_memory import project_memory


TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "iteration"

DEFAULT_GAME_HOOK = """\
    // ── Default hook (customize per game) ────────────────────────────────────
    // 1. Click the game's start button (adjust selector).
    await page.click('#startBtn').catch(() => {});

    // 2. Wait for the game to enter play state. Adjust accessor.
    await page.waitForFunction(
      () => window.__game?.game?.state === 'play',
      { timeout: 10_000 }
    ).catch(() => {});

    const deadlineMs = Date.now() + seconds * 1000;
    botStartMs = Date.now();
    actionTimes.push(botStartMs);

    const VW = 1280, VH = 800;
    await page.mouse.move(VW / 2, VH / 2);
    const held = new Set();

    // 3. Random-walk action loop (WASD + mouse). Replace with game-specific
    //    inputs if your game doesn't respond to WASD.
    while (Date.now() < deadlineMs) {
      const st = await page.evaluate(() =>
        window.__game?.game?.state || 'unknown'
      ).catch(() => 'unknown');
      if (st === 'gameover' || st === 'win') break;

      const r = Math.random() * 100;
      if (r < 45) {
        for (const k of held) await page.keyboard.up(k).catch(() => {});
        held.clear();
        const key = pick(['KeyW', 'KeyA', 'KeyS', 'KeyD']);
        await page.keyboard.down(key).catch(() => {});
        held.add(key);
        await sleep(rand(200, 800));
      } else if (r < 75) {
        await page.mouse.move(rand(40, VW - 40), rand(40, VH - 40)).catch(() => {});
      } else if (r < 92) {
        await page.mouse.down().catch(() => {});
        await sleep(rand(100, 400));
        await page.mouse.up().catch(() => {});
      } else {
        await page.keyboard.press('Space').catch(() => {});
      }
      actionTimes.push(Date.now());
      await sleep(100);
    }

    for (const k of held) await page.keyboard.up(k).catch(() => {});

    // 4. Snapshot for telemetry. Populate window.__snapshot with counters/events.
    await page.evaluate(() => {
      const g = window.__game?.game;
      if (!g) { window.__snapshot = null; return; }
      const a = g.analytics || { counters: {}, events: [] };
      window.__snapshot = {
        outcome: g.state === 'win' ? 'win' : g.state === 'gameover' ? 'death' : 'timeout',
        score: g.score | 0,
        levelIdx: g.levelIdx | 0,
        hi_score_beaten: (g.score | 0) > (g.hiScore | 0),
        xp: g.xp?.snapshot?.() || null,
        counters: { ...(a.counters || {}) },
        events: (a.events || []).slice(-400),
      };
    }).catch(() => {});"""


def _render(
    template_name: str,
    substitutions: dict[str, str],
) -> str:
    """Load a template file and substitute {{placeholders}} with values."""
    tpl_path = TEMPLATE_DIR / template_name
    text = tpl_path.read_text(encoding="utf-8")
    for key, val in substitutions.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def scaffold_iteration_artifacts(
    project_id: str,
    artifact_dir: str | Path,
    *,
    project_title: str = "code-play game",
    game_url: str = "http://localhost:8765/index.html",
    game_hook: str | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    """Emit the iteration kit into `artifact_dir`.

    Returns a dict of artifact_name -> absolute file path for files written.
    Idempotent when `overwrite=False`: existing files are preserved and their
    paths are returned unchanged (so calling this on an artifact that was
    partially scaffolded does not clobber agent edits).
    """

    repo = Path(artifact_dir).resolve()
    repo.mkdir(parents=True, exist_ok=True)

    subs = {
        "PROJECT_TITLE": project_title,
        "REPO_PATH": str(repo),
        "GAME_URL": game_url,
        "GAME_HOOK": game_hook if game_hook is not None else DEFAULT_GAME_HOOK,
        "SCAFFOLD_ISO": datetime.now(timezone.utc).isoformat(),
    }

    paths = {
        "iteration_contract_path": repo / "ITERATION_CONTRACT.md",
        "goals_path": repo / "GOALS.md",
        "playtest_bot_path": repo / "playtest_bot.mjs",
    }

    writes = {
        "iteration_contract_path": (
            paths["iteration_contract_path"],
            _render("ITERATION_CONTRACT.md.tmpl", subs),
        ),
        "goals_path": (
            paths["goals_path"],
            _render("GOALS.md.tmpl", subs),
        ),
        "playtest_bot_path": (
            paths["playtest_bot_path"],
            _render("playtest_bot.mjs.tmpl", subs),
        ),
    }

    written: dict[str, str] = {}
    for key, (fpath, content) in writes.items():
        if fpath.exists() and not overwrite:
            written[key] = str(fpath)
            continue
        fpath.write_text(content, encoding="utf-8")
        written[key] = str(fpath)

    # telemetry dir + gitkeep so cycle 1 has somewhere to write
    tel_dir = repo / "telemetry"
    tel_dir.mkdir(exist_ok=True)
    gitkeep = tel_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")
    written["telemetry_dir"] = str(tel_dir)

    # .codeplay/config.yaml — per-repo knobs (budget override, scaffolded-at)
    cfg_dir = repo / ".codeplay"
    cfg_dir.mkdir(exist_ok=True)
    cfg_path = cfg_dir / "config.yaml"
    if not cfg_path.exists() or overwrite:
        cfg_path.write_text(
            (
                f"# code-play per-repo iteration config\n"
                f"# Scaffolded by src/iteration/scaffolder.py at {subs['SCAFFOLD_ISO']}\n"
                f"project_id: {project_id}\n"
                f"project_title: {project_title}\n"
                f"game_url: {game_url}\n"
                f"# Override cycle budget (default 5) by setting this to an int:\n"
                f"# budget: 3\n"
            ),
            encoding="utf-8",
        )
    written["codeplay_config_path"] = str(cfg_path)

    # Register paths in project memory so downstream agents can find them.
    for key, fpath in paths.items():
        project_memory.write(
            project_id,
            mem_type="iteration",
            key=key,
            content=str(fpath),
            created_by="scaffolder",
        )
    project_memory.write(
        project_id,
        mem_type="iteration",
        key="scaffolded_at",
        content=subs["SCAFFOLD_ISO"],
        created_by="scaffolder",
    )

    return written
