// player.mjs — buildButt, movement, mag/reload, input helpers

export function buildButt(ctx) {
  const { THREE, C, toon, withOutline, blobShadow } = ctx;
  const g = new THREE.Group();

  // two cheek spheres
  for (const sx of [-0.38, 0.38]) {
    const cheek = new THREE.Mesh(
      new THREE.SphereGeometry(0.55, 18, 14),
      toon(C.peach)
    );
    cheek.scale.set(1, 0.95, 1.1);
    cheek.position.set(sx, 0.65, 0);
    withOutline(cheek, 0.06);
    g.add(cheek);
  }

  // cleft line (ink box between)
  const cleft = new THREE.Mesh(
    new THREE.BoxGeometry(0.05, 0.9, 0.6),
    toon(C.cleft)
  );
  cleft.position.set(0, 0.65, 0);
  g.add(cleft);

  // stubby legs
  for (const sx of [-0.25, 0.25]) {
    const leg = new THREE.Mesh(
      new THREE.CylinderGeometry(0.18, 0.2, 0.28, 8),
      toon(C.peach)
    );
    leg.position.set(sx, 0.15, 0);
    withOutline(leg, 0.05);
    g.add(leg);
  }

  // little feet
  for (const sx of [-0.25, 0.25]) {
    const foot = new THREE.Mesh(
      new THREE.BoxGeometry(0.3, 0.08, 0.35),
      toon(C.ink)
    );
    foot.position.set(sx, 0.04, 0.05);
    g.add(foot);
  }

  // facing arrow indicator (tiny triangle, front)
  const arrow = new THREE.Mesh(
    new THREE.ConeGeometry(0.14, 0.25, 3),
    toon(C.ink)
  );
  arrow.rotation.x = Math.PI / 2;
  arrow.position.set(0, 0.7, -0.7);
  g.add(arrow);

  g.add(blobShadow(0.7));
  return g;
}

export function makePlayer(obj) {
  return {
    obj,
    x: 0, z: 0,
    vx: 0, vz: 0,
    hp: 100, maxHp: 100,
    baseSpeed: 7.0,
    accel: 1.1,
    friction: 0.82,
    mag: { cur: 10, max: 10, reloading: false, reloadT: 0, reloadTime: 1.2 },
    iFrames: 0,
    recoil: { t: 0, dx: 0, dz: 0 },
    rot: 0,
    aimX: 0, aimZ: -1,
    toxTime: 0,
  };
}

// returns true if reload consumed. ammoDelta defaults 1 (single shot).
export function tryShoot(player, nowSec, minCadence) {
  if (player.mag.reloading) return false;
  if (player.mag.cur <= 0) {
    startReload(player);
    return false;
  }
  player.mag.cur -= 1;
  if (player.mag.cur <= 0) startReload(player);
  return true;
}

export function startReload(player, sfx) {
  if (player.mag.reloading) return false;
  if (player.mag.cur >= player.mag.max) return false;
  player.mag.reloading = true;
  player.mag.reloadT = player.mag.reloadTime;
  sfx?.reload?.();
  return true;
}

export function updateReload(player, dt) {
  if (!player.mag.reloading) return;
  player.mag.reloadT -= dt;
  if (player.mag.reloadT <= 0) {
    player.mag.cur = player.mag.max;
    player.mag.reloading = false;
    player.mag.reloadT = 0;
  }
}

// WASD/Arrow movement → returns {ix, iz} in [-1, 1]
export function readMoveInput(keys) {
  let ix = 0, iz = 0;
  if (keys['KeyW'] || keys['ArrowUp'])    iz -= 1;
  if (keys['KeyS'] || keys['ArrowDown'])  iz += 1;
  if (keys['KeyA'] || keys['ArrowLeft'])  ix -= 1;
  if (keys['KeyD'] || keys['ArrowRight']) ix += 1;
  const m = Math.hypot(ix, iz) || 1;
  return { ix: ix / m, iz: iz / m };
}

export function applyMove(player, ix, iz, speed, dt) {
  player.vx = player.vx * player.friction + ix * speed * player.accel * dt * 60 * 0.1;
  player.vz = player.vz * player.friction + iz * speed * player.accel * dt * 60 * 0.1;
  // cap
  const v = Math.hypot(player.vx, player.vz);
  const maxV = speed * 1.2;
  if (v > maxV) {
    player.vx = player.vx / v * maxV;
    player.vz = player.vz / v * maxV;
  }
  player.x += player.vx * dt;
  player.z += player.vz * dt;

  if (ix !== 0 || iz !== 0) {
    player.rot = Math.atan2(ix, iz);
  }

  // arena clamp (caller sets ARENA)
}
