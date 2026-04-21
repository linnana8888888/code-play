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
    // ── GameAPI-aware default hook ───────────────────────────────────────────
    // Uses the standard GameAPI contract (iteration_contract.md §1a).
    // The QA engineer's generate-bot step will replace this with game-specific
    // logic after analyzing the game's genre and input scheme.

    // Mark as bot so the game doesn't trigger human telemetry downloads.
    await page.evaluate(() => { window.__playtestBot = true; });

    // Wait for GameAPI to exist (module load), then start through the contract.
    await page.waitForFunction(() => !!window.GameAPI?.start, { timeout: 10_000 });
    await page.evaluate(() => window.GameAPI.start({ seed: 0 }));
    await page.waitForFunction(
      () => window.GameAPI.getState() === 'play',
      { timeout: 10_000 }
    );

    const deadlineMs = Date.now() + seconds * 1000;
    botStartMs = Date.now();
    actionTimes.push(botStartMs);

    const VW = 1280, VH = 800;
    await page.mouse.move(VW / 2, VH / 2);
    const held = new Set();
    let shooting = false;
    let shootReleaseAt = 0;

    // Random-walk action loop (WASD + mouse). The QA engineer's generate-bot
    // step replaces this with game-specific targeting logic.
    while (Date.now() < deadlineMs) {
      const snap = await page.evaluate(() => {
        const api = window.GameAPI;
        if (!api?.getSnapshot) return { state: api?.getState?.() ?? 'title' };
        const s = api.getSnapshot();
        return { state: api.getState(), player: s.player, enemies: s.enemies, boss: s.boss, mag: s.mag };
      });

      const { state } = snap;
      if (state === 'gameover' || state === 'win') break;

      if (state === 'picker') {
        await sleep(300);
        await page.evaluate(() => {
          const n = document.querySelectorAll('#pickerCards button').length || 1;
          window.GameAPI.pickCard(Math.floor(Math.random() * n));
        });
        actionTimes.push(Date.now());
        await sleep(120);
        continue;
      }

      const now = Date.now();

      // If snapshot has entity positions, aim at nearest enemy
      let target = null;
      const px = snap.player?.sx ?? VW / 2;
      const py = snap.player?.sy ?? VH / 2;
      if (snap.boss) {
        target = { sx: snap.boss.sx, sy: snap.boss.sy };
      } else if (snap.enemies?.length) {
        let bestDist = Infinity;
        for (const e of snap.enemies) {
          if (e.sx < 0 || e.sx > VW || e.sy < 0 || e.sy > VH) continue;
          const dx = e.sx - px, dy = e.sy - py;
          const d = dx * dx + dy * dy;
          if (d < bestDist) { bestDist = d; target = { sx: e.sx, sy: e.sy }; }
        }
      }

      const hasTarget = target != null;
      const needsReload = snap.mag && snap.mag.cur === 0;
      if (needsReload) {
        await page.keyboard.press('KeyR');
        actionTimes.push(now);
        await sleep(100);
        continue;
      }

      const r = Math.random() * 100;
      if (hasTarget && r < 50) {
        // Aim + shoot at target
        const jx = Math.max(5, Math.min(VW - 5, target.sx + rand(-15, 15)));
        const jy = Math.max(5, Math.min(VH - 5, target.sy + rand(-15, 15)));
        await page.mouse.move(jx, jy);
        if (!shooting) {
          await page.mouse.down();
          shooting = true;
          shootReleaseAt = now + rand(200, 600);
        }
      } else if (r < 50 + 30) {
        // Move (WASD random)
        for (const k of held) await page.keyboard.up(k).catch(() => {});
        held.clear();
        const key = pick(['KeyW', 'KeyA', 'KeyS', 'KeyD']);
        await page.keyboard.down(key);
        held.add(key);
        if (hasTarget) {
          await page.mouse.move(
            Math.max(5, Math.min(VW - 5, target.sx + rand(-20, 20))),
            Math.max(5, Math.min(VH - 5, target.sy + rand(-20, 20))),
          );
        }
      } else if (r < 50 + 30 + 12) {
        // Shoot burst
        if (!shooting) {
          await page.mouse.down();
          shooting = true;
          shootReleaseAt = now + rand(100, 400);
        }
      } else {
        // Random aim (exploration)
        await page.mouse.move(rand(40, VW - 40), rand(40, VH - 40));
      }

      if (shooting && now >= shootReleaseAt) {
        await page.mouse.up();
        shooting = false;
      }

      actionTimes.push(now);
      await sleep(100);
    }

    for (const k of held) await page.keyboard.up(k).catch(() => {});
    if (shooting) await page.mouse.up().catch(() => {});"""


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
