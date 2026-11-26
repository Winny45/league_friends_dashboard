/* ---- Fill the draft from a screenshot of champion select ---------------------------
   Paste (Ctrl+V), drop or choose a screenshot on the Draft tab. Everything
   happens in this browser: nothing is uploaded anywhere.

   Champion select keeps everything in the same places, scaled with the
   window, so the reader looks only where things are:
     your team    round portraits down the left edge, five rows, in pick order
     the enemy    round portraits down the right edge, Enemy 1 to 5
     bans         a row of five small icons in each top corner
   Positions are measured in shares of the screenshot's height from the edge
   each thing hangs off (left things from the left, right things from the
   right), so any window size works, as long as the screenshot is the
   client window: Alt+Print Screen, or Win+Shift+S around the window.

   Each spot is compared with every champion's icon, nudged a little in
   place and size. The comparison is a small fingerprint of the middle of
   the icon: mostly its light and dark (the client dims and tints portraits)
   with some colour, leaving out the ring round a portrait and the swap
   badge on its bottom-right corner. A spot with no clear winner (an empty
   ban, a champion still being hovered) is left blank. */

const SHOT_READY = true;
const SHOT_N = 12;
/* All in shares of the screenshot's height. Your portraits sit in one of
   two places: further right and larger once picks are done (summoner spells
   sit beside them), further left and smaller while picking. The enemy's and
   the bans do not move. Measured on real screenshots of both phases. */
const SHOT_LAYOUT = {
  pick: { top: 0.176, step: 0.1172,
    us: [{ x: 0.0997, size: 0.084 }, { x: 0.049, size: 0.072 }],
    them: { x: 0.0621, size: 0.082 } },
  ban: { size: 0.0375, y: 0.0445, left: 0.0188, right: 0.0246, step: 0.0586 },
};
const SHOT = { lib: null, busy: false };
function shotMask(r, badge) {
  const m = [], c = (SHOT_N - 1) / 2;
  for (let y = 0; y < SHOT_N; y++) for (let x = 0; x < SHOT_N; x++) {
    if ((x - c) ** 2 + (y - c) ** 2 > (SHOT_N / 2 * r) ** 2) continue;
    if (badge && x >= SHOT_N * 0.62 && y >= SHOT_N * 0.62) continue;
    m.push(y * SHOT_N + x);
  }
  return m;
}
const MASKS = { pick: shotMask(0.8, true), ban: shotMask(0.92, false) };
/* Light and dark at full weight, colour at half: [Y, R-Y, B-Y] a pixel,
   brightness centred, scaled to length one. */
function shotDesc(px, mask) {
  const v = new Float32Array(mask.length * 3);
  let mean = 0;
  mask.forEach((i, k) => {
    const p = i * 4, R = px[p], G = px[p + 1], B = px[p + 2], Y = 0.299 * R + 0.587 * G + 0.114 * B;
    v[3 * k] = Y; v[3 * k + 1] = (R - Y) * 0.5; v[3 * k + 2] = (B - Y) * 0.5;
    mean += Y;
  });
  mean /= mask.length;
  let ss = 0;
  for (let k = 0; k < mask.length; k++) v[3 * k] -= mean;
  for (let i = 0; i < v.length; i++) ss += v[i] * v[i];
  if (ss < mask.length * 40) return null;     // flat: an empty slot
  const n = 1 / Math.sqrt(ss);
  for (let i = 0; i < v.length; i++) v[i] *= n;
  return v;
}
const loadImg = src => new Promise((res, rej) => { const im = new Image(); im.crossOrigin = 'anonymous'; im.onload = () => res(im); im.onerror = rej; im.src = src; });
/* Every champion's fingerprints, both masks, at two crops: the whole icon
   and its middle (portraits are a little zoomed). */
async function shotLibrary(progress) {
  if (SHOT.lib) return SHOT.lib;
  const cv = document.createElement('canvas');
  cv.width = cv.height = SHOT_N;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const lib = { pick: [], ban: [] };
  let done = 0;
  const imgs = await Promise.all(D.champIndex.map(s => loadImg(champUrl(s)).catch(() => null).then(im => {
    if (++done % 25 === 0 && progress) progress(`Learning the champions… ${done} of ${D.champIndex.length}`);
    return im;
  })));
  imgs.forEach((im, ci) => {
    if (!im) return;
    for (const cr of [1, 0.86]) {
      const s = im.naturalWidth * cr, o = (im.naturalWidth - s) / 2;
      cx.clearRect(0, 0, SHOT_N, SHOT_N);
      cx.drawImage(im, o, o, s, s, 0, 0, SHOT_N, SHOT_N);
      const px = cx.getImageData(0, 0, SHOT_N, SHOT_N).data;
      for (const kind of ['pick', 'ban']) { const d = shotDesc(px, MASKS[kind]); if (d) lib[kind].push([ci, d]); }
    }
  });
  SHOT.lib = lib;
  return lib;
}
/* The best champion at one spot, nudged within a fifth of its size and
   resized by up to fifteen per cent: {ci, best, second, x, y, s}. */
function shotRead1(full, cx, lib, kind, cxp, cyp, s0, slack = 0.2) {
  const mask = MASKS[kind], L = lib[kind];
  let best = null;
  for (let s = s0 * 0.86; s <= s0 * 1.16; s *= 1.05) {
    for (let dy = -0.2; dy <= 0.2001; dy += 0.1) for (let dx = -slack; dx <= slack + 0.0001; dx += 0.1) {
      const x = cxp - s / 2 + dx * s0, y = cyp - s / 2 + dy * s0;
      if (x < 0 || y < 0 || x + s > full.width || y + s > full.height) continue;
      cx.clearRect(0, 0, SHOT_N, SHOT_N);
      cx.drawImage(full, x, y, s, s, 0, 0, SHOT_N, SHOT_N);
      const d = shotDesc(cx.getImageData(0, 0, SHOT_N, SHOT_N).data, mask);
      if (!d) continue;
      const per = new Map();
      for (const [ci, v] of L) {
        let sc = 0;
        for (let i = 0; i < d.length; i++) sc += d[i] * v[i];
        if (!per.has(ci) || sc > per.get(ci)) per.set(ci, sc);
      }
      let b1 = -1, c1 = -1, b2 = -1;
      per.forEach((sc, ci) => { if (sc > b1) { b2 = b1; b1 = sc; c1 = ci; } else if (sc > b2) b2 = sc; });
      if (!best || b1 > best.best) best = { ci: c1, best: b1, second: b2, x, y, s };
    }
  }
  return best;
}
/* Whether a row of your team shows splash art behind it, which the client
   only draws once that player has locked in: a hovered champion sits on a
   plain dark row. Measured as the colour and texture of a band of the row
   to the right of the portrait and name. */
function rowHasArt(full, y, H) {
  const x0 = Math.round(0.22 * H), w = Math.round(0.22 * H), y0 = Math.round(y - 0.03 * H), h = Math.round(0.06 * H);
  if (y0 < 0 || y0 + h > full.height || x0 + w > full.width) return false;
  const d = full.getContext('2d', { willReadFrequently: true }).getImageData(x0, y0, w, h).data;
  let n = 0, s = 0, ss = 0, ch = 0;
  for (let i = 0; i < d.length; i += 4) {
    const R = d[i], G = d[i + 1], B = d[i + 2], Y = 0.299 * R + 0.587 * G + 0.114 * B;
    s += Y; ss += Y * Y; ch += Math.max(R, G, B) - Math.min(R, G, B); n++;
  }
  const m = s / n, sd = Math.sqrt(Math.max(0, ss / n - m * m));
  return ch / n >= 20 && sd >= 24;
}
const tick = () => new Promise(r => setTimeout(r, 0));
/* Read every slot. A match needs to be close (0.62) and clear of the next
   champion (0.08); one clear but not by much (under 0.15) is kept and
   marked for checking. On your side, a champion whose row has no splash
   art, or whose portrait is the enlarged one of the player picking right
   now, is only being hovered, and is left blank. */
async function shotRead(img, progress) {
  const lib = await shotLibrary(progress);
  const W = img.naturalWidth, H = img.naturalHeight;
  const full = document.createElement('canvas');
  full.width = W; full.height = H;
  full.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
  const cv = document.createElement('canvas');
  cv.width = cv.height = SHOT_N;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const P = SHOT_LAYOUT.pick, B = SHOT_LAYOUT.ban, out = { us: [], them: [], bansUs: [], bansThem: [], spots: [] };
  const good = r => !!r && r.best >= 0.62 && r.best - r.second >= 0.08;
  const rowY = k => (P.top + P.step * k) * H;
  /* Your side: whichever of the two layouts fits better. */
  if (progress) progress('Reading your team…');
  let mine = null, fit = -1;
  for (const L of P.us) {
    const rows = [0, 1, 2, 3, 4].map(k => shotRead1(full, cx, lib, 'pick', L.x * H, rowY(k), L.size * H));
    const score = rows.reduce((t, r) => t + (good(r) ? r.best : 0), 0);
    if (score > fit) { fit = score; mine = rows; }
    await tick();
  }
  mine.forEach((r, k) => {
    const ok = good(r);
    if (ok) { r.unsure = r.best - r.second < 0.15; r.hover = !rowHasArt(full, rowY(k), H); }
    /* Not locked in is left blank: a hover is not a pick, and an empty
       slot's lane icon can look a little like some champion anyway. */
    const keep = ok && !r.hover;
    out.us.push(keep ? r : null);
    if (r) out.spots.push({ x: r.x, y: r.y, s: r.s, r, ok: keep && !r.hover, list: out.us });
  });
  if (progress) progress('Reading the enemy team…');
  for (let k = 0; k < 5; k++) {
    const r = shotRead1(full, cx, lib, 'pick', W - P.them.x * H, rowY(k), P.them.size * H), ok = good(r);
    if (ok) r.unsure = r.best - r.second < 0.15;
    out.them.push(ok ? r : null);
    if (r) out.spots.push({ x: r.x, y: r.y, s: r.s, r, ok, list: out.them });
  }
  await tick();
  if (progress) progress('Reading the bans…');
  for (let k = 0; k < 5; k++) {
    [[out.bansUs, (B.left + B.step * k) * H], [out.bansThem, W - (B.right + B.step * (4 - k)) * H]].forEach(([list, x]) => {
      const r = shotRead1(full, cx, lib, 'ban', x, B.y * H, B.size * H, 0.35), ok = good(r);
      if (ok) r.unsure = r.best - r.second < 0.15;
      list.push(ok ? r : null);
      if (r) out.spots.push({ x: r.x, y: r.y, s: r.s, r, ok, list });
    });
  }
  /* The slack lets two slots land on the same icon: keep the better one. */
  [out.bansUs, out.bansThem].forEach(list => list.forEach((r, i) => {
    if (r && list.some((o, j) => j !== i && o && o.ci === r.ci && o.best > r.best)) list[i] = null;
  }));
  /* The player picking now has a portrait drawn bigger than the rest. */
  const sizes = out.us.filter(Boolean).map(r => r.s).sort((a, b) => a - b);
  if (sizes.length >= 2) {
    const med = sizes[Math.floor(sizes.length / 2)];
    out.us.forEach((r, i) => { if (r && r.s > med * 1.15) out.us[i] = null; });
  }
  return out;
}

/* A small copy of the screenshot with every slot boxed, for checking. */
function shotPreview(img, A) {
  const c = document.createElement('canvas'), k = Math.min(1, 900 / img.naturalWidth);
  c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
  const x = c.getContext('2d');
  x.drawImage(img, 0, 0, c.width, c.height);
  x.lineWidth = 2; x.font = 'bold 11px Inter, sans-serif';
  A.spots.forEach(sp => {
    const col = !sp.ok ? 'rgba(255,255,255,0.4)' : sp.list === A.us ? '#4c8dff' : sp.list === A.them ? '#ff5f5f' : '#ffcf70';
    x.strokeStyle = col;
    x.strokeRect(sp.x * k, sp.y * k, sp.s * k, sp.s * k);
    if (sp.ok) { x.fillStyle = col; x.fillText(C(D.champIndex[sp.r.ci]).n, sp.x * k, sp.y * k + sp.s * k + 11); }
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
    const ratio = img.naturalWidth / img.naturalHeight;
    const A = await shotRead(img, m => { UI.shot = { msg: m }; drawShot(); });
    const hits = [...A.us, ...A.them, ...A.bansUs, ...A.bansThem].filter(f => f && !f.hover), found = hits.length;
    /* Real champion select gives clear matches; anything else (the loading
       screen, a desktop around a small window) gives a few weak ones. */
    const shaky = hits.filter(f => f.unsure).length > found / 2;
    UI.shot = { A, preview: shotPreview(img, A), found,
      warn: ratio < 1.6 || ratio > 2.1 ? 'This does not look like the client window on its own; crop to the window (Alt+Print Screen) for the best read.'
        : !found || shaky ? 'This does not look like champion select: most of what was found is a weak match. Take the screenshot during champion select, cropped to the client window (Alt+Print Screen).' : '' };
    URL.revokeObjectURL(url);
  } catch (e) {
    UI.shot = { msg: 'That screenshot could not be read: ' + (e.message || e) };
  }
  SHOT.busy = false;
  drawShot();
}
/* Into the board: champions into the slots they were read from, and, where
   your team's lanes can be told from its champions, those too. */
function applyShot() {
  const st = draftState(), A = (UI.shot || {}).A;
  if (!A) return;
  const name = f => f ? D.champIndex[f.ci] : null;
  A.us.forEach((f, i) => { if (f && !f.hover) st.us[i].c = name(f); });
  A.them.forEach((f, i) => { if (f) st.them[i].c = name(f); });
  A.bansUs.forEach((f, i) => { if (f) st.bans.us[i] = name(f); });
  A.bansThem.forEach((f, i) => { if (f) st.bans.them[i] = name(f); });
  /* Your lanes, guessed the way the enemy's are: every champion at once,
     the likeliest way to give them one lane each. All of it is used, so no
     two of you end up in the same lane; a wrong one is a dropdown away. */
  const mine = enemyRoles({ them: st.us.map(x => ({ c: x.c, r: '' })) });
  Object.entries(mine).forEach(([i, g]) => { st.us[i].r = g.r; });
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
  const list = (title, arr) => `<div class="sh-list"><span class="muted small">${title}</span>${arr.map(f => f
    ? f.hover ? `<span class="sh-hit hover" title="${esc(C(D.champIndex[f.ci]).n)} is being hovered, not locked in: it is not filled in">${cicon(D.champIndex[f.ci], 28)}<small>hovering</small></span>`
      : `<span class="sh-hit${f.unsure ? ' unsure' : ''}" title="${esc(C(D.champIndex[f.ci]).n)}: match ${(100 * f.best).toFixed(0)}%${f.unsure ? ', worth checking' : ''}">${cicon(D.champIndex[f.ci], 28)}<small>${f.unsure ? 'check' : (100 * f.best).toFixed(0) + '%'}</small></span>`
    : '<span class="sh-hit none" title="Nothing clear here"><span class="sh-blank">?</span><small>blank</small></span>').join('')}</div>`;
  let body = '';
  if (U && U.msg) body = `<div class="muted small sh-msg">${esc(U.msg)}</div>`;
  else if (U && U.A) body = `<div class="sh-res"><img class="sh-prev" src="${U.preview}" alt="The screenshot with each slot boxed and named">` +
    `<div class="sh-found">${U.warn ? `<div class="ms-warn">⚠ ${esc(U.warn)}</div>` : ''}${list('Your picks, in pick order', U.A.us)}${list('Enemy picks', U.A.them)}${list('Your bans', U.A.bansUs)}${list('Enemy bans', U.A.bansThem)}` +
    `<div class="ms-act"><button type="button" class="pill sm on" data-shot-apply>Fill the board</button><button type="button" class="linkbtn" data-shot-clear>Discard</button></div>` +
    `<p class="muted small">Boxes show where it looked: blue your team, red the enemy, gold the bans, faint where nothing was clear. "check" means the match was close. Your teammates' champions are only read once locked in: one that is just being hovered stays blank. Anything wrong can be fixed on the board.</p></div></div>`;
  return `<div id="shotcard">` + card('From a screenshot',
    'Take a screenshot of the client window in champion select (Alt+Print Screen, or Win+Shift+S around the window), then paste it anywhere on this tab with Ctrl+V, drop it here, or choose the file. ' +
    'It is read in this browser and never uploaded. Your picks come from the left in pick order, the enemy\'s from the right, and the bans from the top corners; your lanes are guessed from your champions.',
    `<label class="sh-drop" data-shot-drop><input type="file" accept="image/*" data-shot-file hidden><span>📷 Drop a screenshot here, paste with Ctrl+V, or click to choose one</span></label>${body}`) + '</div>';
}
