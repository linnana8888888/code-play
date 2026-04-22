// camera.mjs — topdown → chase → fps cycling + pointer lock

const MODES = ['topdown', 'chase', 'fps'];

export function createCamera(cameraObj, canvasEl) {
  let modeIdx = 0;
  // FPS look state (yaw/pitch in radians)
  let yaw = 0, pitch = 0;
  const yawMin = -Infinity, yawMax = Infinity;
  const pitchMin = -0.9, pitchMax = 0.5;

  // FPS mouse sensitivity (radians per px). Default roughly 2.5× the old value
  // — old 0.002 was too slow for tracking enemies. Bracket keys adjust live.
  const SENS_MIN = 0.002, SENS_MAX = 0.012, SENS_STEP = 0.0008;
  let fpsSens = 0.0052;
  try {
    const s = parseFloat(localStorage.getItem('bsg_fps_sens') || '');
    if (Number.isFinite(s) && s >= SENS_MIN && s <= SENS_MAX) fpsSens = s;
  } catch {}

  // restore saved mode
  try {
    const saved = localStorage.getItem('bsg_cam');
    if (saved) {
      const i = MODES.indexOf(saved);
      if (i >= 0) modeIdx = i;
    }
  } catch {}

  function mode() { return MODES[modeIdx]; }

  function cycle() {
    modeIdx = (modeIdx + 1) % MODES.length;
    try { localStorage.setItem('bsg_cam', MODES[modeIdx]); } catch {}
    if (MODES[modeIdx] === 'fps') {
      enterPointerLock();
    } else {
      exitPointerLock();
    }
    document.body.classList.toggle('fps-mode', MODES[modeIdx] === 'fps');
    return MODES[modeIdx];
  }

  function enterPointerLock() {
    if (document.pointerLockElement === canvasEl) return;
    try { canvasEl.requestPointerLock(); } catch {}
  }

  function exitPointerLock() {
    if (document.pointerLockElement === canvasEl) {
      try { document.exitPointerLock(); } catch {}
    }
  }

  function onMouseMove(e) {
    if (MODES[modeIdx] !== 'fps') return;
    if (document.pointerLockElement !== canvasEl) return;
    yaw   -= e.movementX * fpsSens;
    pitch -= e.movementY * fpsSens;
    if (pitch < pitchMin) pitch = pitchMin;
    if (pitch > pitchMax) pitch = pitchMax;
  }

  function adjustSens(delta) {
    fpsSens = Math.max(SENS_MIN, Math.min(SENS_MAX, fpsSens + delta));
    try { localStorage.setItem('bsg_fps_sens', String(fpsSens)); } catch {}
    return fpsSens;
  }

  // Returns {aimX, aimZ} unit vector in world XZ based on current camera mode.
  // For topdown/chase, uses player rotation. For fps, uses yaw.
  function update(player, mouseWorld) {
    const m = MODES[modeIdx];
    if (m === 'topdown') {
      cameraObj.position.set(player.x, 18, player.z + 0.01);
      cameraObj.up.set(0, 0, -1);
      cameraObj.lookAt(player.x, 0, player.z);
      // aim follows mouseWorld (XZ pointer projection)
      if (mouseWorld) {
        const dx = mouseWorld.x - player.x;
        const dz = mouseWorld.z - player.z;
        const mm = Math.hypot(dx, dz) || 1;
        player.aimX = dx / mm;
        player.aimZ = dz / mm;
      }
    } else if (m === 'chase') {
      // behind player based on aim direction
      const ax = player.aimX, az = player.aimZ;
      const dist = 7, height = 5;
      cameraObj.up.set(0, 1, 0);
      cameraObj.position.set(
        player.x - ax * dist,
        height,
        player.z - az * dist
      );
      cameraObj.lookAt(player.x, 1.5, player.z);
      // aim follows mouseWorld too
      if (mouseWorld) {
        const dx = mouseWorld.x - player.x;
        const dz = mouseWorld.z - player.z;
        const mm = Math.hypot(dx, dz) || 1;
        player.aimX = dx / mm;
        player.aimZ = dz / mm;
      }
    } else if (m === 'fps') {
      // camera at butt eye-level, look along yaw/pitch
      cameraObj.up.set(0, 1, 0);
      cameraObj.position.set(player.x, 1.4, player.z);
      const lx = Math.sin(yaw) * Math.cos(pitch);
      const ly = Math.sin(pitch);
      const lz = -Math.cos(yaw) * Math.cos(pitch);
      cameraObj.lookAt(
        player.x + lx,
        1.4 + ly,
        player.z + lz
      );
      // aim is XZ projection of look
      const ax = Math.sin(yaw);
      const az = -Math.cos(yaw);
      const am = Math.hypot(ax, az) || 1;
      player.aimX = ax / am;
      player.aimZ = az / am;
    }
  }

  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('pointerlockchange', () => {
    if (document.pointerLockElement !== canvasEl && MODES[modeIdx] === 'fps') {
      // user exited fps accidentally — drop back to chase
      modeIdx = 1;
      document.body.classList.remove('fps-mode');
      try { localStorage.setItem('bsg_cam', 'chase'); } catch {}
    }
  });

  // if already in fps mode from storage, toggle body class + request lock after first gesture
  if (MODES[modeIdx] === 'fps') {
    document.body.classList.add('fps-mode');
  }

  return {
    mode, cycle, update,
    enterPointerLock, exitPointerLock,
    getYaw: () => yaw,
    getPitch: () => pitch,
    getSens: () => fpsSens,
    sensUp: () => adjustSens(SENS_STEP),
    sensDown: () => adjustSens(-SENS_STEP),
    SENS_STEP,
  };
}
