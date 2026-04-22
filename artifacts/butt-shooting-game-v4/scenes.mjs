// scenes.mjs — levels, props, new enemies
// Agent B implementation — see CONTRACTS.md → scenes.mjs

// ─── Level configs ────────────────────────────────────────────────────────────

export const LEVELS = [
  {
    id: 0, name: 'Desert Dunes', kills: 20,
    sky: 0x7FC4E0, floor: 0xE8D7A8, ring: 0xC7B383,
    fog: [0x7FC4E0, 45, 85],
    hemiTop: 0xFFF4D6, hemiBot: 0xE8D7A8, hemiI: 0.55,
    sunColor: 0xFFFFFF, sunI: 0.95,
    props: ['cactus', 'rock'],
    propCount: 22,
    enemyMix: [
      { kind: 'flusher',  weight: 0.45 },
      { kind: 'buttling', weight: 0.40 },
      { kind: 'windy',    weight: 0.15 },
    ],
    musicIdx: 0,
  },
  {
    id: 1, name: 'Porcelain Lab', kills: 30,
    sky: 0xE8F4F8, floor: 0xF0EDE5, ring: 0xD8D2C8,
    fog: [0xE8F4F8, 40, 75],
    hemiTop: 0xFFFFFF, hemiBot: 0xE8F4F8, hemiI: 0.65,
    sunColor: 0xFFFFFF, sunI: 0.85,
    props: ['toilet', 'pipe', 'tile'],
    propCount: 28,
    enemyMix: [
      { kind: 'flusher',      weight: 0.35 },
      { kind: 'buttling',     weight: 0.35 },
      { kind: 'toiletGolem',  weight: 0.30 },
    ],
    musicIdx: 1,
  },
  {
    id: 2, name: 'Sewer Depths', kills: 40,
    sky: 0x2D4A3E, floor: 0x3A5548, ring: 0x223028,
    fog: [0x1A2E22, 30, 60],
    hemiTop: 0x6FA63E, hemiBot: 0x1A2E22, hemiI: 0.4,
    sunColor: 0x9DD96A, sunI: 0.5,
    props: ['pipe', 'grate', 'puddle'],
    propCount: 26,
    enemyMix: [
      { kind: 'buttling',  weight: 0.35 },
      { kind: 'windy',     weight: 0.25 },
      { kind: 'sewerRat',  weight: 0.40 },
    ],
    musicIdx: 2,
    boss: 'clog_king',
  },
];

// ─── Environment swap ─────────────────────────────────────────────────────────

export function applyLevel(scene, hemi, sun, cfg, ctx) {
  const { THREE, ARENA, toon } = ctx;

  // background + fog
  scene.background = new THREE.Color(cfg.sky);
  scene.fog = new THREE.Fog(cfg.fog[0], cfg.fog[1], cfg.fog[2]);

  // lights
  hemi.color.setHex(cfg.hemiTop);
  hemi.groundColor.setHex(cfg.hemiBot);
  hemi.intensity = cfg.hemiI;
  sun.color.setHex(cfg.sunColor);
  sun.intensity = cfg.sunI;

  // replace floor
  const oldFloor = scene.getObjectByName('floor');
  if (oldFloor) {
    oldFloor.geometry.dispose();
    oldFloor.material.dispose();
    scene.remove(oldFloor);
  }
  const floorGeo = new THREE.PlaneGeometry(ARENA * 2, ARENA * 2, 1, 1);
  floorGeo.rotateX(-Math.PI / 2);
  const floor = new THREE.Mesh(floorGeo, toon(cfg.floor));
  floor.name = 'floor';
  scene.add(floor);

  // replace ring
  const oldRing = scene.getObjectByName('ring');
  if (oldRing) {
    oldRing.geometry.dispose();
    oldRing.material.dispose();
    scene.remove(oldRing);
  }
  const ringGeo = new THREE.RingGeometry(ARENA - 0.2, ARENA, 64);
  ringGeo.rotateX(-Math.PI / 2);
  const ring = new THREE.Mesh(ringGeo, toon(cfg.ring));
  ring.name = 'ring';
  ring.position.y = 0.01;
  scene.add(ring);

  // scatter props
  const propRoot = new THREE.Group();
  propRoot.name = 'propRoot';
  scene.add(propRoot);

  for (let i = 0; i < cfg.propCount; i++) {
    const a = (i / cfg.propCount) * Math.PI * 2 + (Math.random() - 0.5) * 0.5;
    const r = ARENA - 2 - Math.random() * 4;
    const kind = cfg.props[Math.floor(Math.random() * cfg.props.length)];
    const p = buildProp(kind, Math.cos(a) * r, Math.sin(a) * r, ctx);
    propRoot.add(p);
  }

  return { propRoot };
}

// ─── Clear props ──────────────────────────────────────────────────────────────

export function clearPropRoot(scene, propRoot) {
  if (!propRoot) return;
  propRoot.traverse(obj => {
    if (obj.isMesh) {
      obj.geometry.dispose();
      if (Array.isArray(obj.material)) {
        obj.material.forEach(m => m.dispose());
      } else if (obj.material) {
        obj.material.dispose();
      }
    }
  });
  scene.remove(propRoot);
}

// ─── Prop builder ─────────────────────────────────────────────────────────────

export function buildProp(kind, x, z, ctx) {
  const { THREE, C, toon, withOutline, blobShadow } = ctx;
  const g = new THREE.Group();
  g.position.set(x, 0, z);

  if (kind === 'cactus') {
    const base = new THREE.Mesh(
      new THREE.CylinderGeometry(0.28, 0.32, 1.6, 8),
      toon(C.cactus)
    );
    base.position.y = 0.8;
    withOutline(base, 0.07);
    g.add(base);

    const armL = new THREE.Mesh(
      new THREE.CylinderGeometry(0.18, 0.2, 0.7, 6),
      toon(C.cactus)
    );
    armL.position.set(-0.3, 1.1, 0);
    armL.rotation.z = Math.PI / 2.6;
    withOutline(armL, 0.07);
    g.add(armL);

    const armR = new THREE.Mesh(
      new THREE.CylinderGeometry(0.18, 0.2, 0.6, 6),
      toon(C.cactus)
    );
    armR.position.set(0.3, 0.95, 0);
    armR.rotation.z = -Math.PI / 2.6;
    withOutline(armR, 0.07);
    g.add(armR);

  } else if (kind === 'rock') {
    const rock = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.9 + Math.random() * 0.4, 0),
      toon(C.rock)
    );
    rock.position.y = 0.4;
    rock.rotation.y = Math.random() * Math.PI;
    withOutline(rock, 0.07);
    g.add(rock);

  } else if (kind === 'toilet') {
    // bowl — flat-ish cylinder
    const bowl = new THREE.Mesh(
      new THREE.CylinderGeometry(0.5, 0.45, 0.55, 12),
      toon(C.porcelain)
    );
    bowl.position.y = 0.28;
    withOutline(bowl, 0.07);
    g.add(bowl);

    // tank behind
    const tank = new THREE.Mesh(
      new THREE.BoxGeometry(0.8, 1.0, 0.5),
      toon(C.porcelain)
    );
    tank.position.set(0, 0.9, 0.45);
    withOutline(tank, 0.07);
    g.add(tank);

    // lid on bowl
    const lid = new THREE.Mesh(
      new THREE.BoxGeometry(0.9, 0.07, 0.85),
      toon(C.porcelain)
    );
    lid.position.y = 0.59;
    withOutline(lid, 0.07);
    g.add(lid);

    // dark water disc
    const water = new THREE.Mesh(
      new THREE.CircleGeometry(0.38, 14),
      toon(C.water, { transparent: true, opacity: 0.8 })
    );
    water.rotation.x = -Math.PI / 2;
    water.position.y = 0.57;
    g.add(water);

  } else if (kind === 'pipe') {
    // horizontal pipe body
    const body = new THREE.Mesh(
      new THREE.CylinderGeometry(0.2, 0.2, 1.8, 10),
      toon(C.pipe)
    );
    body.rotation.z = Math.PI / 2;
    body.position.y = 0.3;
    withOutline(body, 0.07);
    g.add(body);

    // end flanges
    for (const sx of [-0.9, 0.9]) {
      const flange = new THREE.Mesh(
        new THREE.CylinderGeometry(0.28, 0.28, 0.1, 10),
        toon(C.chrome)
      );
      flange.rotation.z = Math.PI / 2;
      flange.position.set(sx, 0.3, 0);
      withOutline(flange, 0.07);
      g.add(flange);
    }

  } else if (kind === 'tile') {
    // shallow decorative floor tile, slightly raised
    const tile = new THREE.Mesh(
      new THREE.BoxGeometry(1.2, 0.06, 1.2),
      toon(C.tile)
    );
    tile.position.y = 0.03;
    withOutline(tile, 0.05);
    g.add(tile);

  } else if (kind === 'grate') {
    // flat metal grid — base plate + crossbars
    const base = new THREE.Mesh(
      new THREE.BoxGeometry(1.0, 0.06, 1.0),
      toon(C.chrome, { emissive: C.chrome, emissiveIntensity: 0.05 })
    );
    base.position.y = 0.03;
    withOutline(base, 0.06);
    g.add(base);

    // two crossbars along X
    for (const zOff of [-0.25, 0.25]) {
      const bar = new THREE.Mesh(
        new THREE.BoxGeometry(1.0, 0.1, 0.08),
        toon(C.chrome, { emissive: C.chrome, emissiveIntensity: 0.05 })
      );
      bar.position.set(0, 0.08, zOff);
      g.add(bar);
    }
    // two crossbars along Z
    for (const xOff of [-0.25, 0.25]) {
      const bar = new THREE.Mesh(
        new THREE.BoxGeometry(0.08, 0.1, 1.0),
        toon(C.chrome, { emissive: C.chrome, emissiveIntensity: 0.05 })
      );
      bar.position.set(xOff, 0.08, 0);
      g.add(bar);
    }

  } else if (kind === 'puddle') {
    const puddle = new THREE.Mesh(
      new THREE.CircleGeometry(0.7 + Math.random() * 0.3, 14),
      toon(C.slime, { transparent: true, opacity: 0.65 })
    );
    puddle.rotation.x = -Math.PI / 2;
    puddle.position.y = 0.01;
    g.add(puddle);
  }

  return g;
}

// ─── New enemies ──────────────────────────────────────────────────────────────

export function buildToiletGolem(ctx) {
  const { THREE, C, toon, withOutline, blobShadow } = ctx;
  const g = new THREE.Group();

  // chunky porcelain barrel body (2.2× flusher scale feel)
  const body = new THREE.Mesh(
    new THREE.CylinderGeometry(0.75, 0.85, 1.3, 12),
    toon(C.porcelain)
  );
  body.position.y = 0.9;
  withOutline(body, 0.07);
  g.add(body);

  // toilet tank as chest/head block
  const tank = new THREE.Mesh(
    new THREE.BoxGeometry(1.1, 1.1, 0.65),
    toon(C.porcelain)
  );
  tank.position.set(0, 2.2, 0.18);
  withOutline(tank, 0.07);
  g.add(tank);

  // bowl lip rim at waist
  const lip = new THREE.Mesh(
    new THREE.TorusGeometry(0.8, 0.13, 8, 18),
    toon(C.porcelain)
  );
  lip.rotation.x = Math.PI / 2;
  lip.position.y = 1.55;
  withOutline(lip, 0.06);
  g.add(lip);

  // angry eyes — small black domes on tank face
  for (const sx of [-0.22, 0.22]) {
    const eyeWhite = new THREE.Mesh(
      new THREE.SphereGeometry(0.1, 8, 6),
      toon(0xFFFFFF)
    );
    eyeWhite.position.set(sx, 2.32, -0.15);
    withOutline(eyeWhite, 0.1);
    g.add(eyeWhite);

    const pupil = new THREE.Mesh(
      new THREE.SphereGeometry(0.055, 7, 5),
      toon(C.ink)
    );
    pupil.position.set(sx, 2.32, -0.24);
    g.add(pupil);
  }

  // angry brow lines
  for (const sx of [-0.22, 0.22]) {
    const brow = new THREE.Mesh(
      new THREE.BoxGeometry(0.18, 0.06, 0.06),
      toon(C.ink)
    );
    brow.position.set(sx, 2.47, -0.15);
    brow.rotation.z = sx < 0 ? 0.35 : -0.35;
    g.add(brow);
  }

  // stubby legs
  for (const sx of [-0.3, 0.3]) {
    const leg = new THREE.Mesh(
      new THREE.CylinderGeometry(0.16, 0.19, 0.38, 8),
      toon(C.porcelain)
    );
    leg.position.set(sx, 0.19, 0);
    withOutline(leg, 0.07);
    g.add(leg);
  }

  // crown rim on top of tank
  const crownRim = new THREE.Mesh(
    new THREE.CylinderGeometry(0.62, 0.55, 0.2, 8),
    toon(C.porcelain)
  );
  crownRim.position.set(0, 2.82, 0.18);
  withOutline(crownRim, 0.06);
  g.add(crownRim);

  // gold studs on crown
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    const stud = new THREE.Mesh(
      new THREE.SphereGeometry(0.09, 6, 5),
      toon(C.gold, { emissive: C.gold, emissiveIntensity: 0.3 })
    );
    stud.position.set(
      Math.cos(a) * 0.58,
      2.96,
      Math.sin(a) * 0.58 + 0.18
    );
    withOutline(stud, 0.08);
    g.add(stud);
  }

  // blob shadow
  g.add(blobShadow(1.1));

  // stats used by game.mjs
  g.userData.stats = {
    hp: 8, speed: 1.4, radius: 1.1,
    score: 40, damage: 20, dropChance: 0.7,
    contactDmg: true,
  };

  return g;
}

export function buildSewerRat(ctx) {
  const { THREE, C, toon, withOutline, blobShadow } = ctx;
  const g = new THREE.Group();

  // low-slung body — wide flat box
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(0.9, 0.35, 0.55),
    toon(C.sewerDark)
  );
  body.position.y = 0.3;
  withOutline(body, 0.07);
  g.add(body);

  // snout — small protruding box
  const snout = new THREE.Mesh(
    new THREE.BoxGeometry(0.28, 0.22, 0.28),
    toon(C.sewerGreen)
  );
  snout.position.set(0, 0.3, -0.38);
  withOutline(snout, 0.06);
  g.add(snout);

  // glowing red eyes
  for (const sx of [-0.14, 0.14]) {
    const eye = new THREE.Mesh(
      new THREE.SphereGeometry(0.055, 7, 5),
      toon(C.rival, { emissive: C.rival, emissiveIntensity: 0.9 })
    );
    eye.position.set(sx, 0.38, -0.45);
    g.add(eye);
  }

  // 4 stubby legs
  const legPositions = [
    [-0.3, -0.18], [-0.3, 0.18],
    [ 0.3, -0.18], [ 0.3, 0.18],
  ];
  for (const [lx, lz] of legPositions) {
    const leg = new THREE.Mesh(
      new THREE.CylinderGeometry(0.07, 0.08, 0.22, 6),
      toon(C.sewerDark)
    );
    leg.position.set(lx, 0.11, lz);
    g.add(leg);
  }

  // long triangle tail (elongated cone)
  const tail = new THREE.Mesh(
    new THREE.CylinderGeometry(0.0, 0.09, 0.9, 6),
    toon(C.sewerGreen)
  );
  tail.rotation.z = -Math.PI / 2;
  tail.position.set(0.7, 0.28, 0);
  g.add(tail);

  // blob shadow
  g.add(blobShadow(0.5));

  // stats
  g.userData.stats = {
    hp: 1, speed: 5.0, radius: 0.5,
    score: 12, damage: 10, dropChance: 0.2,
  };

  return g;
}
