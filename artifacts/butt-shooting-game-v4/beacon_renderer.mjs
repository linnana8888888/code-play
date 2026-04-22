// beacon_renderer.mjs — offscreen arrow pointing at active health kits
//
// Idea: healthkit_breadcrumb_beacon
// When a health kit spawns off-screen we want a subtle DOM arrow on the edge
// of the viewport pointing toward it, so the player knows relief is out there
// without us teleporting or auto-grabbing. The arrow fades when the pickup
// enters the camera frustum.
//
// createBeaconRenderer(hudRoot, camera)
//   .track({ id, getPos })     // register a target
//   .untrack(id)               // remove
//   .update()                  // call each frame after camera.lookAt

export function createBeaconRenderer(hudRoot, camera) {
  if (!hudRoot) {
    return { track() {}, untrack() {}, update() {}, clear() {} };
  }

  const targets = new Map(); // id → { getPos, el }
  const tmpVec = { x: 0, y: 0, z: 0 };

  function makeEl() {
    const el = document.createElement('div');
    el.className = 'healthkit-beacon';
    el.style.cssText = [
      'position:absolute',
      'left:0',
      'top:0',
      'width:28px',
      'height:28px',
      'pointer-events:none',
      'transform-origin:center',
      'font-size:22px',
      'text-align:center',
      'line-height:28px',
      'color:#FF5F5F',
      'text-shadow:0 0 6px rgba(255,95,95,0.7), 0 2px 0 #000',
      'font-weight:900',
      'user-select:none',
      'z-index:40',
      'transition:opacity 180ms linear',
    ].join(';');
    el.textContent = '➤';
    hudRoot.appendChild(el);
    return el;
  }

  function track(id, getPos) {
    if (targets.has(id)) return;
    targets.set(id, { getPos, el: makeEl() });
  }

  function untrack(id) {
    const rec = targets.get(id);
    if (!rec) return;
    if (rec.el && rec.el.parentNode) rec.el.parentNode.removeChild(rec.el);
    targets.delete(id);
  }

  function clear() {
    for (const id of Array.from(targets.keys())) untrack(id);
  }

  function project(px, py, pz) {
    // three's Vector3.project is cleaner but we avoid allocations per frame.
    const v = camera.worldToScreen || null;
    // Fallback: use three's matrix math via a tiny adapter.
    if (camera.matrixWorldInverse && camera.projectionMatrix) {
      const tmp = { x: px, y: py, z: pz, w: 1 };
      const mve = camera.matrixWorldInverse.elements;
      const x1 = mve[0]*tmp.x + mve[4]*tmp.y + mve[8]*tmp.z  + mve[12];
      const y1 = mve[1]*tmp.x + mve[5]*tmp.y + mve[9]*tmp.z  + mve[13];
      const z1 = mve[2]*tmp.x + mve[6]*tmp.y + mve[10]*tmp.z + mve[14];
      const w1 = mve[3]*tmp.x + mve[7]*tmp.y + mve[11]*tmp.z + mve[15];
      const pe = camera.projectionMatrix.elements;
      const x2 = pe[0]*x1 + pe[4]*y1 + pe[8]*z1  + pe[12]*w1;
      const y2 = pe[1]*x1 + pe[5]*y1 + pe[9]*z1  + pe[13]*w1;
      const z2 = pe[2]*x1 + pe[6]*y1 + pe[10]*z1 + pe[14]*w1;
      const w2 = pe[3]*x1 + pe[7]*y1 + pe[11]*z1 + pe[15]*w1;
      if (!w2) return null;
      return { x: x2 / w2, y: y2 / w2, z: z2 / w2 };
    }
    return null;
  }

  function update() {
    if (!targets.size) return;
    const cw = window.innerWidth;
    const ch = window.innerHeight;
    for (const [, rec] of targets) {
      const p = rec.getPos(tmpVec);
      if (!p) { rec.el.style.opacity = '0'; continue; }
      const proj = project(p.x, p.y ?? 0.6, p.z);
      if (!proj) { rec.el.style.opacity = '0'; continue; }

      // Convert NDC → pixel.
      const sx = (proj.x * 0.5 + 0.5) * cw;
      const sy = (1 - (proj.y * 0.5 + 0.5)) * ch;
      const onScreen = sx >= 40 && sx <= cw - 40 && sy >= 40 && sy <= ch - 40 && proj.z < 1;
      if (onScreen) { rec.el.style.opacity = '0'; continue; }

      // Clamp to screen edge + point arrow.
      const cx = cw * 0.5;
      const cy = ch * 0.5;
      const dx = sx - cx;
      const dy = sy - cy;
      const angle = Math.atan2(dy, dx);
      const pad = 36;
      const maxX = cw * 0.5 - pad;
      const maxY = ch * 0.5 - pad;
      const t = Math.min(maxX / Math.abs(Math.cos(angle) || 1e-3), maxY / Math.abs(Math.sin(angle) || 1e-3));
      const ex = cx + Math.cos(angle) * t;
      const ey = cy + Math.sin(angle) * t;
      rec.el.style.transform = `translate(${ex - 14}px, ${ey - 14}px) rotate(${angle}rad)`;
      rec.el.style.opacity = '1';
    }
  }

  return { track, untrack, update, clear };
}
