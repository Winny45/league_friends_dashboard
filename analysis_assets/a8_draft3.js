/* ---- Fill the draft from a screenshot of champion select ---------------------------
   Paste (Ctrl+V), drop or choose a screenshot on the Draft tab. Everything
   happens in this browser: nothing is uploaded anywhere.

   How it reads one:
     1. Every champion's square icon is boiled down to a tiny colour
        fingerprint (a few dozen pixels inside a circle, so round portraits
        and square ban icons both match), once, the first time it is used.
     2. The screenshot is searched at a range of icon sizes for windows whose
        fingerprint is close to some champion's: a quick pass on a shrunken
        copy, then a careful re-check of the promising spots at full size,
        nudging the window a little in place and size.
     3. Where a match sits says what it is. The client always shows your
        team down the left and the enemy down the right, top to bottom in
        pick order, and the bans along the top; the champion grid in the
        middle is ignored.
   The result is shown for checking before it fills the board. */

/* Off until it has been tuned against real champion select screenshots. */
const SHOT_READY = false;
const SHOT_SM = 6, SHOT_LG = 12, SHOT_P = 24;
/* Where things are, as shares of the screenshot's width and height. */
const SHOT_LAYOUT = { pickLeft: 0.24, pickRight: 0.76, banTop: 0.13, minIcon: 0.028, maxIcon: 0.12 };
const SHOT = { lib: null, busy: false };
function shotMask(n) {
  const m = [], c = (n - 1) / 2, r = (n / 2) * 0.92;
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if ((x - c) ** 2 + (y - c) ** 2 <= r * r) m.push(y * n + x);
  return m;
}
const MASK_SM = shotMask(SHOT_SM), MASK_LG = shotMask(SHOT_LG);
/* A window's fingerprint: its masked RGB, centred and scaled to length one.
   Returns false for a flat window, which cannot be a champion. */
function shotDesc(px, w, x0, y0, n, mask, out) {
  let k = 0, mean = 0;
  for (let j = 0; j < mask.length; j++) {
    const i = mask[j], p = ((y0 + ((i / n) | 0)) * w + x0 + (i % n)) * 4;
    out[k++] = px[p]; out[k++] = px[p + 1]; out[k++] = px[p + 2];
  }
  for (let i = 0; i < k; i++) mean += out[i];
  mean /= k;
  let ss = 0;
  for (let i = 0; i < k; i++) { out[i] -= mean; ss += out[i] * out[i]; }
  if (ss < k * 64) return false;
  const nrm = 1 / Math.sqrt(ss);
  for (let i = 0; i < k; i++) out[i] *= nrm;
  return true;
}
/* A fixed random projection to a short vector for the quick pass. */
let SHOT_PROJ = null;
function shotProj() {
  if (SHOT_PROJ) return SHOT_PROJ;
  let seed = 7;
  const rnd = () => { seed = (seed * 1103515245 + 12345) >>> 0; return seed / 4294967296 - 0.5; };
  const d = MASK_SM.length * 3;
  SHOT_PROJ = new Float32Array(SHOT_P * d).map(() => rnd());
  return SHOT_PROJ;
}
function project(v, out) {
  const P = shotProj(), d = v.length;
  let ss = 0;
  for (let r = 0; r < SHOT_P; r++) { let s = 0; for (let i = 0; i < d; i++) s += P[r * d + i] * v[i]; out[r] = s; ss += s * s; }
  const nrm = 1 / Math.sqrt(ss || 1);
  for (let r = 0; r < SHOT_P; r++) out[r] *= nrm;
}
const loadImg = src => new Promise((res, rej) => { const im = new Image(); im.crossOrigin = 'anonymous'; im.onload = () => res(im); im.onerror = rej; im.src = src; });
/* Every champion's fingerprints, at two crops: the whole icon (bans) and
   the middle of it (round portraits are zoomed in a little). */
async function shotLibrary(progress) {
  if (SHOT.lib) return SHOT.lib;
  const slugs = D.champIndex.slice(), crops = [1, 0.84];
  const n = slugs.length * crops.length, dS = MASK_SM.length * 3, dL = MASK_LG.length * 3;
  const sm = new Float32Array(n * SHOT_P), lg = new Float32Array(n * dL), who = new Int16Array(n), ok = new Uint8Array(n);
  const cS = document.createElement('canvas'), cL = document.createElement('canvas');
  cS.width = cS.height = SHOT_SM; cL.width = cL.height = SHOT_LG;
  const xS = cS.getContext('2d', { willReadFrequently: true }), xL = cL.getContext('2d', { willReadFrequently: true });
  const tS = new Float32Array(dS), tP = new Float32Array(SHOT_P), tL = new Float32Array(dL);
  let done = 0;
  await Promise.all(slugs.map(async (slug, ci) => {
    let im;
    try { im = await loadImg(champUrl(slug)); } catch (e) { done++; return; }
    crops.forEach((cr, k) => {
      const row = ci * crops.length + k, s = im.naturalWidth * cr, o = (im.naturalWidth - s) / 2;
      who[row] = ci;
      xS.clearRect(0, 0, SHOT_SM, SHOT_SM); xS.drawImage(im, o, o, s, s, 0, 0, SHOT_SM, SHOT_SM);
      xL.clearRect(0, 0, SHOT_LG, SHOT_LG); xL.drawImage(im, o, o, s, s, 0, 0, SHOT_LG, SHOT_LG);
      if (shotDesc(xS.getImageData(0, 0, SHOT_SM, SHOT_SM).data, SHOT_SM, 0, 0, SHOT_SM, MASK_SM, tS) &&
        shotDesc(xL.getImageData(0, 0, SHOT_LG, SHOT_LG).data, SHOT_LG, 0, 0, SHOT_LG, MASK_LG, tL)) {
        project(tS, tP); sm.set(tP, row * SHOT_P); lg.set(tL, row * dL); ok[row] = 1;
      }
    });
    if (++done % 20 === 0 && progress) progress(`Learning the champions… ${done} of ${slugs.length}`);
  }));
  SHOT.lib = { n, sm, lg, who, ok, dL };
  return SHOT.lib;
}
const tick = () => new Promise(r => setTimeout(r, 0));
/* Every place in the screenshot that looks like a champion icon:
   [{x, y, s, ci, score}] in the screenshot's own pixels, best first.
   A match must be close (0.8 of a perfect fingerprint) and clearly better
   than the next champion (by 0.12): background art can look a bit like
   anything, but never a lot like one champion and not the others. */
async function shotFind(img, progress) {
  const L = await shotLibrary(progress);
  const W = img.naturalWidth, H = img.naturalHeight;
  const full = document.createElement('canvas');
  full.width = W; full.height = H;
  full.getContext('2d').drawImage(img, 0, 0);
  const work = document.createElement('canvas'), wx = work.getContext('2d', { willReadFrequently: true });
  const d = new Float32Array(MASK_SM.length * 3), p = new Float32Array(SHOT_P);
  const rough = [];
  const base = Math.min(W, H * 16 / 9) / (16 / 9);    // the client's height, if it fills the width
  for (let S = SHOT_LAYOUT.minIcon * base; S <= SHOT_LAYOUT.maxIcon * base; S *= 1.16) {
    const f = SHOT_SM / S, w = Math.max(SHOT_SM, Math.round(W * f)), h = Math.max(SHOT_SM, Math.round(H * f));
    work.width = w; work.height = h;
    wx.imageSmoothingQuality = 'high';
    wx.drawImage(img, 0, 0, w, h);
    const px = wx.getImageData(0, 0, w, h).data, gw = w - SHOT_SM + 1, gh = h - SHOT_SM + 1;
    const score = new Float32Array(gw * gh).fill(-1);
    for (let y = 0; y < gh; y++) {
      for (let x = 0; x < gw; x++) {
        if (!shotDesc(px, w, x, y, SHOT_SM, MASK_SM, d)) continue;
        project(d, p);
        let best = -1;
        for (let r = 0; r < L.n; r++) {
          if (!L.ok[r]) continue;
          let s = 0;
          const o = r * SHOT_P;
          for (let i = 0; i < SHOT_P; i++) s += p[i] * L.sm[o + i];
          if (s > best) best = s;
        }
        score[y * gw + x] = best;
      }
      if (y % 40 === 39) await tick();
    }
    /* Only the best spot in each neighbourhood goes on to the careful pass. */
    for (let y = 0; y < gh; y++) for (let x = 0; x < gw; x++) {
      const v = score[y * gw + x];
      if (v < 0.75) continue;
      let top = true;
      for (let dy = -2; dy <= 2 && top; dy++) for (let dx = -2; dx <= 2; dx++) {
        const yy = y + dy, xx = x + dx;
        if ((dx || dy) && yy >= 0 && xx >= 0 && yy < gh && xx < gw && score[yy * gw + xx] > v) { top = false; break; }
      }
      if (top) rough.push({ x: x / f, y: y / f, s: S, score: v });
    }
    if (progress) progress(`Searching at icon size ${Math.round(S)}px…`);
    await tick();
  }
  rough.sort((a, b) => b.score - a.score);
  const cL = document.createElement('canvas');
  cL.width = cL.height = SHOT_LG;
  const xL = cL.getContext('2d', { willReadFrequently: true });
  const t = new Float32Array(L.dL), found = [];
  const fine = (x, y, s) => {
    xL.clearRect(0, 0, SHOT_LG, SHOT_LG);
    xL.drawImage(full, x, y, s, s, 0, 0, SHOT_LG, SHOT_LG);
    return shotDesc(xL.getImageData(0, 0, SHOT_LG, SHOT_LG).data, SHOT_LG, 0, 0, SHOT_LG, MASK_LG, t);
  };
  const dot = r => { let sc = 0; const o = r * L.dL; for (let i = 0; i < L.dL; i++) sc += t[i] * L.lg[o + i]; return sc; };
  /* Best and runner-up champion for the window in t. */
  const rank = rows => {
    const per = new Map();
    for (const r of rows) { if (!L.ok[r]) continue; const sc = dot(r), ci = L.who[r]; if (!per.has(ci) || sc > per.get(ci)) per.set(ci, sc); }
    const top = [...per.entries()].sort((a, b) => b[1] - a[1]);
    return { ci: top[0] ? top[0][0] : -1, best: top[0] ? top[0][1] : -1, second: top[1] ? top[1][1] : -1, top };
  };
  const ALL = [...Array(L.n).keys()];
  const near = (a, b) => Math.abs(a.x + a.s / 2 - b.x - b.s / 2) < Math.max(a.s, b.s) * 0.5 && Math.abs(a.y + a.s / 2 - b.y - b.s / 2) < Math.max(a.s, b.s) * 0.5;
  let k = 0;
  for (const c of rough.slice(0, 500)) {
    if (found.some(f => near(f, c))) continue;
    if (++k % 40 === 0) { if (progress) progress(`Checking likely icons… ${found.length} found`); await tick(); }
    if (!fine(c.x, c.y, c.s)) continue;
    /* The few likeliest champions here, then the window nudged for them. */
    const shortlist = rank(ALL).top.slice(0, 4).map(e => e[0]);
    const rows = ALL.filter(r => shortlist.includes(L.who[r]));
    let best = { score: -1 };
    for (const ds of [0.88, 1, 1.12]) for (const dx of [-0.12, 0, 0.12]) for (const dy of [-0.12, 0, 0.12]) {
      const s = c.s * ds, x = c.x + (c.s - s) / 2 + dx * c.s, y = c.y + (c.s - s) / 2 + dy * c.s;
      if (x < 0 || y < 0 || x + s > W || y + s > H || !fine(x, y, s)) continue;
      const R = rank(rows);
      if (R.best > best.score) best = { x, y, s, score: R.best, ci: R.ci };
    }
    if (best.score < 0.8 || !fine(best.x, best.y, best.s)) continue;
    const R = rank(ALL);
    if (R.ci === best.ci && R.best - R.second >= 0.12) found.push(Object.assign(best, { margin: R.best - R.second }));
  }
  return found.sort((a, b) => b.score - a.score);
}
/* Which match is which: picks down each side in order, bans along the top. */
function shotAssign(found, W, H) {
  const cx = f => (f.x + f.s / 2) / W, cy = f => (f.y + f.s / 2) / H;
  const used = new Set(), take = list => list.filter(f => !used.has(f.ci) && used.add(f.ci));
  const bans = found.filter(f => cy(f) < SHOT_LAYOUT.banTop);
  const left = found.filter(f => cy(f) >= SHOT_LAYOUT.banTop && cx(f) < SHOT_LAYOUT.pickLeft);
  const right = found.filter(f => cy(f) >= SHOT_LAYOUT.banTop && cx(f) > SHOT_LAYOUT.pickRight);
  /* Five at most a side: the best-scoring five, then put back in screen order. */
  const top5 = (list, key) => take(list.slice().sort((a, b) => b.score - a.score)).slice(0, 5).sort((a, b) => key(a) - key(b));
  return {
    us: top5(left, f => f.y), them: top5(right, f => f.y),
    bansUs: top5(bans.filter(f => cx(f) < 0.5), f => f.x), bansThem: top5(bans.filter(f => cx(f) >= 0.5), f => f.x),
  };
}
/* A small copy of the screenshot with every match boxed, for checking. */
function shotPreview(img, found, A) {
  const c = document.createElement('canvas'), k = Math.min(1, 900 / img.naturalWidth);
  c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
  const x = c.getContext('2d');
  x.drawImage(img, 0, 0, c.width, c.height);
  const kind = new Map();
  A.us.forEach(f => kind.set(f, '#4c8dff')); A.them.forEach(f => kind.set(f, '#ff5f5f'));
  A.bansUs.forEach(f => kind.set(f, '#8fb6ff')); A.bansThem.forEach(f => kind.set(f, '#ff9a9a'));
  x.lineWidth = 2; x.font = '11px Inter, sans-serif';
  found.forEach(f => {
    const col = kind.get(f) || 'rgba(255,255,255,0.35)';
    x.strokeStyle = col; x.strokeRect(f.x * k, f.y * k, f.s * k, f.s * k);
    if (kind.has(f)) { x.fillStyle = col; x.fillText(C(D.champIndex[f.ci]).n, f.x * k, f.y * k - 3); }
  });
  return c.toDataURL('image/jpeg', 0.8);
}
async function readScreenshot(file) {
  if (SHOT.busy || !file || !/^image\//.test(file.type)) return;
  SHOT.busy = true;
  UI.shot = { msg: 'Reading the screenshot…' };
  drawShot();
  try {
    const url = URL.createObjectURL(file), img = await loadImg(url);
    const found = await shotFind(img, m => { UI.shot = { msg: m }; drawShot(); });
    const A = shotAssign(found, img.naturalWidth, img.naturalHeight);
    UI.shot = { A, preview: shotPreview(img, found, A), n: found.length };
    URL.revokeObjectURL(url);
  } catch (e) {
    UI.shot = { msg: 'That screenshot could not be read: ' + (e.message || e) };
  }
  SHOT.busy = false;
  drawShot();
}
function applyShot() {
  const st = draftState(), A = (UI.shot || {}).A;
  if (!A) return;
  A.us.forEach((f, i) => { st.us[i].c = D.champIndex[f.ci]; });
  A.them.forEach((f, i) => { st.them[i].c = D.champIndex[f.ci]; });
  A.bansUs.forEach((f, i) => { st.bans.us[i] = D.champIndex[f.ci]; });
  A.bansThem.forEach((f, i) => { st.bans.them[i] = D.champIndex[f.ci]; });
  st.focus = null;
  UI.shot = null;
  saveDraft();
  render();
}
function drawShot() {
  const host = document.getElementById('shotcard');
  if (host && S.tab === 'draft' && !S.p) host.outerHTML = shotCard();
}
function shotCard() {
  const U = UI.shot;
  const list = (title, arr) => `<div class="sh-list"><span class="muted small">${title}</span>${arr.length ? arr.map(f => `<span class="sh-hit" title="match ${(100 * f.score).toFixed(0)}%">${cicon(D.champIndex[f.ci], 26)}<small>${(100 * f.score).toFixed(0)}%</small></span>`).join('') : '<span class="muted small">none found</span>'}</div>`;
  let body = '';
  if (U && U.msg) body = `<div class="muted small sh-msg">${esc(U.msg)}</div>`;
  else if (U && U.A) body = `<div class="sh-res"><img class="sh-prev" src="${U.preview}" alt="The screenshot with each match boxed">` +
    `<div class="sh-found">${list('Your picks', U.A.us)}${list('Enemy picks', U.A.them)}${list('Your bans', U.A.bansUs)}${list('Enemy bans', U.A.bansThem)}` +
    `<div class="ms-act"><button type="button" class="pill sm on" data-shot-apply>Fill the board</button><button type="button" class="linkbtn" data-shot-clear>Discard</button></div>` +
    `<p class="muted small">Blue boxes are your team, red the enemy, light boxes bans; grey boxes were seen but left out. Anything wrong can be fixed on the board after filling it.</p></div></div>`;
  return `<div id="shotcard">` + card('From a screenshot',
    'Paste a screenshot of champion select (Ctrl+V anywhere on this tab), drop one here, or choose a file. It is read in this browser and never uploaded. ' +
    'Your picks are read from the left of the screen and the enemy\'s from the right, in pick order, with the bans along the top.',
    `<label class="sh-drop" data-shot-drop><input type="file" accept="image/*" data-shot-file hidden><span>📷 Drop a screenshot here, paste with Ctrl+V, or click to choose one</span></label>${body}`) + '</div>';
}
