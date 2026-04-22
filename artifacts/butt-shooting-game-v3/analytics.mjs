// analytics.mjs — local event log + dev panel + localStorage rollup

const LS_SESSIONS = 'bsg_sessions';
const LS_HI       = 'bsg_hiscore';
const MAX_SESSIONS = 50;

export function createAnalytics(panelEl, statsEl, eventsEl) {
  const startedAt = Date.now();
  const events = [];
  const counters = {
    shots: 0, hits: 0, kills: 0, deaths: 0, levelUps: 0,
    dashes: 0, reloads: 0, pickups: 0, bossHits: 0, bossKills: 0,
  };
  let lastScore = 0, lastLevel = 0;

  function emit(type, data = {}) {
    const e = { t: (Date.now() - startedAt) / 1000, type, ...data };
    events.push(e);
    if (events.length > 400) events.shift();
    if (counters[type + 's'] != null) counters[type + 's'] += 1;
    if (type === 'kill') counters.kills += 1;
    if (type === 'hit') counters.hits += 1;
    if (type === 'shot') counters.shots += 1;
    if (type === 'dash') counters.dashes += 1;
    if (type === 'reload') counters.reloads += 1;
    if (type === 'pickup') counters.pickups += 1;
    if (type === 'levelUp') counters.levelUps += 1;
    if (type === 'death') counters.deaths += 1;
    if (type === 'bossHit') counters.bossHits += 1;
    if (type === 'bossKill') counters.bossKills += 1;
    if (data.score != null) lastScore = data.score;
    if (data.level != null) lastLevel = data.level;
    if (panelEl && panelEl.classList.contains('show')) renderPanel();
  }

  function saveSession(outcome) {
    try {
      const raw = localStorage.getItem(LS_SESSIONS);
      const arr = raw ? JSON.parse(raw) : [];
      const sess = {
        ts: Date.now(),
        durationSec: Math.round((Date.now() - startedAt) / 1000),
        outcome, // 'win' | 'death' | 'quit'
        score: lastScore,
        level: lastLevel,
        counters: { ...counters },
      };
      arr.push(sess);
      while (arr.length > MAX_SESSIONS) arr.shift();
      localStorage.setItem(LS_SESSIONS, JSON.stringify(arr));
    } catch (err) { console.warn('analytics save fail', err); }
  }

  function loadHiScore() {
    try { return parseInt(localStorage.getItem(LS_HI) || '0', 10) || 0; }
    catch { return 0; }
  }

  function setHiScore(n) {
    try { localStorage.setItem(LS_HI, String(n | 0)); } catch {}
  }

  function sessionRollup() {
    return {
      durationSec: Math.round((Date.now() - startedAt) / 1000),
      score: lastScore,
      level: lastLevel,
      counters: { ...counters },
    };
  }

  function allSessions() {
    try {
      const raw = localStorage.getItem(LS_SESSIONS);
      return raw ? JSON.parse(raw) : [];
    } catch { return []; }
  }

  // ─── Dev panel rendering ──────────────────────────────────────────────────
  function renderPanel() {
    if (!statsEl || !eventsEl) return;
    const r = sessionRollup();
    const accuracy = r.counters.shots > 0
      ? ((r.counters.hits / r.counters.shots) * 100).toFixed(1) + '%'
      : '—';
    const kpm = r.durationSec > 0
      ? (r.counters.kills / (r.durationSec / 60)).toFixed(1)
      : '0.0';
    statsEl.innerHTML = [
      `<div class="row">Duration: ${r.durationSec}s</div>`,
      `<div class="row">Score: ${r.score} · Level: ${r.level + 1}</div>`,
      `<div class="row">Shots: ${r.counters.shots} · Hits: ${r.counters.hits} · Acc: ${accuracy}</div>`,
      `<div class="row">Kills: ${r.counters.kills} · KPM: ${kpm}</div>`,
      `<div class="row">Dashes: ${r.counters.dashes} · Reloads: ${r.counters.reloads}</div>`,
      `<div class="row">Pickups: ${r.counters.pickups} · LevelUps: ${r.counters.levelUps}</div>`,
      `<div class="row">Boss hits: ${r.counters.bossHits} · kills: ${r.counters.bossKills}</div>`,
    ].join('');
    // last 12 events
    const tail = events.slice(-12).reverse();
    eventsEl.innerHTML = tail.map(e => {
      const extras = Object.entries(e)
        .filter(([k]) => k !== 't' && k !== 'type')
        .map(([k, v]) => `${k}=${v}`)
        .join(' ');
      return `<div class="row">[${e.t.toFixed(1)}s] <b>${e.type}</b> ${extras}</div>`;
    }).join('');
  }

  function togglePanel() {
    if (!panelEl) return;
    panelEl.classList.toggle('show');
    if (panelEl.classList.contains('show')) renderPanel();
  }

  function showPanel(show) {
    if (!panelEl) return;
    panelEl.classList.toggle('show', !!show);
    if (show) renderPanel();
  }

  function exportJson() {
    const blob = new Blob([JSON.stringify({
      session: sessionRollup(),
      events,
      allSessions: allSessions(),
    }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `bsg-analytics-${Date.now()}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function clearStored() {
    try { localStorage.removeItem(LS_SESSIONS); } catch {}
    renderPanel();
  }

  return {
    emit, saveSession,
    loadHiScore, setHiScore,
    sessionRollup, allSessions,
    togglePanel, showPanel, renderPanel,
    exportJson, clearStored,
    get events() { return events; },
    get counters() { return counters; },
  };
}
