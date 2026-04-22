// juice.mjs — floaters, combo, powerups, boss, bean-rain

// ─── 1. FLOATERS ────────────────────────────────────────────────────────────

export function createFloaters(containerEl, camera) {
  const MAX = 50;
  const LIFE = 0.9;
  const RISE = 60; // px
  let pool = []; // { el, worldPos, t0, basePx: {x,y} }
  const now = () => performance.now() / 1000;

  function spawn(worldPos, text, color, big = false) {
    // evict oldest if at cap
    if (pool.length >= MAX) {
      const old = pool.shift();
      old.el.remove();
    }
    const el = document.createElement('div');
    const sz = big ? 44 : 22;
    el.style.cssText = [
      'position:absolute',
      'pointer-events:none',
      `font-family:"Fredoka One",Fredoka,sans-serif`,
      `font-size:${sz}px`,
      `font-weight:700`,
      `color:${color}`,
      `text-shadow:-2px -2px 0 #000,2px -2px 0 #000,-2px 2px 0 #000,2px 2px 0 #000`,
      'white-space:nowrap',
      'transform:translate(-50%,-50%)',
      'will-change:transform,opacity',
    ].join(';');
    el.textContent = text;
    containerEl.appendChild(el);
    // project immediately so it appears at the right spot
    const proj = _project(worldPos);
    el.style.left = proj.x + 'px';
    el.style.top  = proj.y + 'px';
    pool.push({ el, worldPos: worldPos.clone(), t0: now(), basePx: { x: proj.x, y: proj.y } });
  }

  function _project(v) {
    const ndc = v.clone().project(camera);
    const w = containerEl.offsetWidth  || window.innerWidth;
    const h = containerEl.offsetHeight || window.innerHeight;
    return { x: (ndc.x * 0.5 + 0.5) * w, y: (-ndc.y * 0.5 + 0.5) * h };
  }

  function update() {
    const t = now();
    pool = pool.filter(f => {
      const age = t - f.t0;
      if (age >= LIFE) { f.el.remove(); return false; }
      const frac = age / LIFE;
      const proj = _project(f.worldPos);
      f.el.style.left    = proj.x + 'px';
      f.el.style.top     = (proj.y - frac * RISE) + 'px';
      f.el.style.opacity = 1 - frac;
      return true;
    });
  }

  return { spawn, update };
}

// ─── 2. COMBO ────────────────────────────────────────────────────────────────

export function createCombo(opts = {}) {
  const WIN = opts.windowSec ?? 2.0;
  const TIERS = [
    { at: 40, tier: 4, mult: 5 },
    { at: 20, tier: 3, mult: 4 },
    { at: 10, tier: 2, mult: 3 },
    { at:  5, tier: 1, mult: 2 },
  ];

  let count = 0, tier = 0, mult = 1, timer = 0;

  function _recompute() {
    for (const t of TIERS) {
      if (count >= t.at) return { tier: t.tier, mult: t.mult };
    }
    return { tier: 0, mult: 1 };
  }

  function hit() {
    timer = WIN;
    count++;
    const prev = tier;
    const r = _recompute();
    tier = r.tier; mult = r.mult;
    return { count, tier, mult, tierChanged: tier > prev };
  }

  function decay(dt) {
    if (timer <= 0) return;
    timer -= dt;
    if (timer <= 0) reset();
  }

  function reset() { count = 0; tier = 0; mult = 1; timer = 0; }

  function snapshot() { return { count, tier, mult, timer }; }

  return { hit, decay, reset, snapshot };
}

// ─── 3. POWERUPS ─────────────────────────────────────────────────────────────

export function createPowerups(player, hudEl) {
  // active: Map<kind, { kind, timer?, left?, origVal? }>
  const active = new Map();

  const DEFS = {
    triple: { timed: true,  dur: 8  },
    rapid:  { timed: true,  dur: 10 },
    speed:  { timed: true,  dur: 10 },
    mega:   { timed: false, shots: 5 },
  };

  const ICONS = { triple: '🔱', rapid: '⚡', speed: '💨', mega: '💥' };

  function apply(kind) {
    const def = DEFS[kind];
    if (!def) return;

    if (def.timed) {
      if (active.has(kind)) {
        // refresh timer
        active.get(kind).timer = Math.max(active.get(kind).timer, def.dur);
      } else {
        const entry = { kind, timer: def.dur };
        // mutate player fields; remember originals
        if (kind === 'rapid') {
          entry.origReloadTime = player.mag.reloadTime;
          player.mag.reloadTime = player.mag.reloadTime * 0.33;
        }
        if (kind === 'speed') {
          entry.origSpeed = player.baseSpeed;
          player.baseSpeed = player.baseSpeed * 1.5;
        }
        active.set(kind, entry);
      }
    } else {
      // mega: stack or set
      if (active.has(kind)) {
        active.get(kind).left = (active.get(kind).left || 0) + def.shots;
      } else {
        active.set(kind, { kind, left: def.shots });
      }
    }
    renderHud();
  }

  function update(dt) {
    for (const [kind, entry] of active) {
      if (DEFS[kind].timed) {
        entry.timer -= dt;
        if (entry.timer <= 0) {
          // restore
          if (kind === 'rapid' && entry.origReloadTime != null)
            player.mag.reloadTime = entry.origReloadTime;
          if (kind === 'speed' && entry.origSpeed != null)
            player.baseSpeed = entry.origSpeed;
          active.delete(kind);
        }
      }
    }
    renderHud();
  }

  function isActive(kind) { return active.has(kind); }

  function megaShotsLeft() {
    return active.has('mega') ? (active.get('mega').left || 0) : 0;
  }

  function consumeMega() {
    if (!active.has('mega')) return 0;
    const e = active.get('mega');
    e.left = Math.max(0, (e.left || 0) - 1);
    if (e.left <= 0) active.delete('mega');
    renderHud();
    return e.left;
  }

  function renderHud() {
    if (!hudEl) return;
    const parts = [];
    for (const [kind, entry] of active) {
      const icon = ICONS[kind] || '?';
      if (DEFS[kind].timed) {
        const pct = Math.max(0, Math.min(100, (entry.timer / DEFS[kind].dur) * 100));
        parts.push(
          `<span style="display:inline-flex;align-items:center;gap:4px;margin:0 6px;font-family:sans-serif;font-size:13px;color:#fff;text-shadow:1px 1px 0 #000">` +
          `${icon} <b>${kind}</b> · ${entry.timer.toFixed(1)}s ` +
          `<span style="display:inline-block;width:40px;height:6px;background:#333;border-radius:3px;overflow:hidden">` +
          `<span style="display:block;width:${pct}%;height:100%;background:#ffe040"></span></span>` +
          `</span>`
        );
      } else {
        parts.push(
          `<span style="display:inline-flex;align-items:center;gap:4px;margin:0 6px;font-family:sans-serif;font-size:13px;color:#fff;text-shadow:1px 1px 0 #000">` +
          `${icon} <b>mega</b> · ${entry.left} shots</span>`
        );
      }
    }
    hudEl.innerHTML = parts.join('');
  }

  function snapshot() {
    const out = {};
    for (const [k, v] of active) out[k] = { ...v };
    return out;
  }

  return { apply, update, isActive, megaShotsLeft, consumeMega, renderHud, snapshot };
}

// ─── 4. CLOG KING ─────────────────────────────────────────────────────────────

export function buildClogKing(ctx) {
  const { THREE, C, toon, withOutline, blobShadow } = ctx;
  const g = new THREE.Group();
  g.name = 'clogKing';

  // porcelain body — big bowl (3× flusher scale feel)
  const bodyGeo = new THREE.CylinderGeometry(1.6, 1.9, 2.6, 16);
  const body = new THREE.Mesh(bodyGeo, toon(C.porcelain));
  body.position.y = 1.3;
  withOutline(body, 0.06);
  g.add(body);

  // tank on back
  const tank = new THREE.Mesh(
    new THREE.BoxGeometry(2.0, 2.0, 1.0),
    toon(C.porcelain)
  );
  tank.position.set(0, 3.0, 1.0);
  withOutline(tank, 0.06);
  g.add(tank);

  // dark water disc on top of bowl
  const waterDisc = new THREE.Mesh(
    new THREE.CircleGeometry(1.25, 20),
    toon(C.sewerDark, { emissive: C.sewerDark, emissiveIntensity: 0.3 })
  );
  waterDisc.rotation.x = -Math.PI / 2;
  waterDisc.position.y = 2.62;
  g.add(waterDisc);

  // seat ring / torus
  const seat = new THREE.Mesh(
    new THREE.TorusGeometry(1.45, 0.25, 8, 24),
    toon(C.ink)
  );
  seat.rotation.x = Math.PI / 2;
  seat.position.y = 2.62;
  g.add(seat);

  // gold crown rim — 8 spike studs around bowl top
  const crownRad = 1.65;
  for (let i = 0; i < 8; i++) {
    const angle = (i / 8) * Math.PI * 2;
    const spike = new THREE.Mesh(
      new THREE.ConeGeometry(0.18, 0.55, 6),
      toon(C.gold, { emissive: C.gold, emissiveIntensity: 0.4 })
    );
    spike.position.set(
      Math.cos(angle) * crownRad,
      2.95,
      Math.sin(angle) * crownRad
    );
    withOutline(spike, 0.08);
    g.add(spike);
  }

  // angry eye domes on tank front
  for (const sx of [-0.5, 0.5]) {
    const eyeWhite = new THREE.Mesh(
      new THREE.SphereGeometry(0.3, 10, 8),
      toon(C.porcelain)
    );
    eyeWhite.position.set(sx, 3.2, 0.52);
    g.add(eyeWhite);

    const pupil = new THREE.Mesh(
      new THREE.SphereGeometry(0.16, 8, 6),
      new THREE.MeshBasicMaterial({ color: C.ink })
    );
    pupil.position.set(sx, 3.2, 0.72);
    g.add(pupil);

    // angry eyebrow
    const brow = new THREE.Mesh(
      new THREE.BoxGeometry(0.38, 0.1, 0.08),
      new THREE.MeshBasicMaterial({ color: C.ink })
    );
    const side = sx > 0 ? 1 : -1;
    brow.position.set(sx, 3.52, 0.54);
    brow.rotation.z = side * 0.35;
    g.add(brow);
  }

  // cheek side bulges — bossRed to evoke demon tint
  for (const sx of [-1.7, 1.7]) {
    const bulge = new THREE.Mesh(
      new THREE.SphereGeometry(0.7, 10, 8),
      toon(C.bossRed)
    );
    bulge.scale.set(1, 0.85, 1);
    bulge.position.set(sx, 1.6, 0);
    withOutline(bulge, 0.06);
    g.add(bulge);
  }

  // legs
  for (const sx of [-0.7, 0.7]) {
    const leg = new THREE.Mesh(
      new THREE.CylinderGeometry(0.25, 0.3, 0.7, 8),
      toon(C.ink)
    );
    leg.position.set(sx, 0.35, 0);
    g.add(leg);
  }

  g.add(blobShadow(2.2));

  // boss metadata
  g.userData.boss = {
    hp: 80, maxHp: 80, phase: 0,
    chargeCd: 2.5, ringCd: 4.5,
    chargeVx: 0, chargeVz: 0, chargeT: 0,
    _ringTimer: 0, _chargeTimer: 0,
  };

  return g;
}

// ─── 5. CLOG KING AI ──────────────────────────────────────────────────────────

export function clogKingAI(boss, player, dt, api) {
  const b = boss.userData.boss;
  if (!b) return;

  // determine phase
  const hpPct = b.hp / b.maxHp;
  let prevPhase = b.phase;
  if (hpPct > 0.6)      b.phase = 0;
  else if (hpPct > 0.3) b.phase = 1;
  else                   b.phase = 2;

  if (b.phase !== prevPhase) {
    api.sfx?.hurt?.();
    api.spawnPoof(boss.position.x, boss.position.z, 0xA63E3E, 14);
  }

  // phase params
  const phases = [
    { drift: 1.2, ringInterval: 4.5, ringCount: 16, ringSpeed: 10, ringDmg: 5,  chargeInterval: 2.5, chargeSpeed: 14, chargeDmg: 18 },
    { drift: 1.6, ringInterval: 3.5, ringCount: 20, ringSpeed: 12, ringDmg: 7,  chargeInterval: 1.8, chargeSpeed: 18, chargeDmg: 18 },
    { drift: 2.2, ringInterval: 2.5, ringCount: 24, ringSpeed: 14, ringDmg: 8,  chargeInterval: 1.3, chargeSpeed: 22, chargeDmg: 18 },
  ];
  const p = phases[b.phase];

  const dx = player.x - boss.position.x;
  const dz = player.z - boss.position.z;
  const dist = Math.sqrt(dx * dx + dz * dz) || 1;

  // ── charging movement
  if (b.chargeT > 0) {
    b.chargeT -= dt;
    boss.position.x += b.chargeVx * dt;
    boss.position.z += b.chargeVz * dt;
    // collision with player
    const cx = player.x - boss.position.x;
    const cz = player.z - boss.position.z;
    if (cx * cx + cz * cz < 4) {
      api.damagePlayer(p.chargeDmg);
      api.spawnPoof(player.x, player.z, 0xFF5FA2, 8);
      b.chargeT = 0; // stop charge after hit
    }
    if (b.chargeT <= 0) {
      b.chargeVx = 0; b.chargeVz = 0;
    }
  } else {
    // slow drift toward player
    boss.position.x += (dx / dist) * p.drift * dt;
    boss.position.z += (dz / dist) * p.drift * dt;
  }

  // face player
  boss.rotation.y = Math.atan2(dx, dz);

  // ── charge cooldown
  b._chargeTimer -= dt;
  if (b._chargeTimer <= 0) {
    b._chargeTimer = p.chargeInterval;
    if (b.chargeT <= 0) {
      const speed = p.chargeSpeed;
      b.chargeVx = (dx / dist) * speed;
      b.chargeVz = (dz / dist) * speed;
      b.chargeT  = 0.8;
    }
  }

  // ── ring burst cooldown
  b._ringTimer -= dt;
  if (b._ringTimer <= 0) {
    b._ringTimer = p.ringInterval;
    const n = p.ringCount;
    // phase 2: alternate offset for spiral variety
    const offset = b.phase === 2 ? (Math.PI / n) * ((Date.now() % 2)) : 0;
    for (let i = 0; i < n; i++) {
      const angle = offset + (i / n) * Math.PI * 2;
      const ax = Math.cos(angle);
      const az = Math.sin(angle);
      api.spawnEnemyBean(
        boss.position.x + ax * 1.8,
        boss.position.z + az * 1.8,
        ax, az,
        p.ringSpeed,
        p.ringDmg
      );
    }
    api.sfx?.shot?.();
  }
}

// ─── 6. BEAN RAIN ─────────────────────────────────────────────────────────────

export function beanRainTick(game, dt, dropBeanPickupFn) {
  if (game.state !== 'play') return;
  if (!game.player) return;
  if (!game.rain) game.rain = { timer: 30 };

  game.rain.timer -= dt;
  if (game.rain.timer > 0) return;
  game.rain.timer = 30;

  for (let i = 0; i < 5; i++) {
    const angle  = Math.random() * Math.PI * 2;
    const radius = 2 + Math.random() * 2; // 2–4 m
    const x = game.player.x + Math.cos(angle) * radius;
    const z = game.player.z + Math.sin(angle) * radius;
    dropBeanPickupFn(x, z, 2);
  }
}
