'use strict';
/* The analysis page renders entirely in the browser from one embedded JSON
   document. Nothing here computes a statistic: every number arrives already
   worked out by analysis.py, so there is one implementation of each figure
   and the two cannot drift. This file is only layout, formatting and SVG. */

const D = JSON.parse(document.getElementById('analysis-data').textContent);
const CFG = JSON.parse(document.getElementById('analysis-config').textContent);
const ROLES = D.meta.roles, RN = D.meta.roleName, STAT = D.meta.stats;
const FR = D.meta.friends.map(f => f.label);
const VER = D.meta.ddragon || '15.1.1';
const TABS = [['game', 'Game breakdown'], ['players', 'Players'], ['champions', 'Champions'],
  ['roles', 'Roles & classes'], ['time', 'Time patterns'], ['duos', 'Duos & stacks'], ['flow', 'Game flow']];
const MAPQ = 232;

/* ---- state lives in the URL, so any view can be linked to ----------------- */
const KEYS = ['tab', 'game', 'team', 'gwho', 'player', 'role', 'champ', 'crole', 'rtab', 'cls', 'who', 'metric', 'queue'];
function parseHash() {
  const o = {};
  location.hash.slice(1).split('&').forEach(kv => {
    const i = kv.indexOf('=');
    if (i > 0) o[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1));
  });
  return o;
}
const S = Object.assign({ tab: 'game' }, parseHash());
const UI = { hmode: 'pos', hphase: '0', mapMode: 'kills', mapT: null, focus: null };
function setState(patch) {
  Object.assign(S, patch);
  const h = KEYS.filter(k => S[k] != null && S[k] !== '').map(k => k + '=' + encodeURIComponent(S[k])).join('&');
  history.replaceState(null, '', '#' + h);
  render();
}
window.addEventListener('hashchange', () => { Object.assign(S, parseHash()); render(); });

/* ---- formatting ------------------------------------------------------------- */
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const set = o => `data-set="${esc(JSON.stringify(o))}"`;
const ui = o => `data-ui="${esc(JSON.stringify(o))}"`;
function gold(v) {
  if (v == null) return '-';
  const a = Math.abs(v), s = a >= 1000 ? (a / 1000).toFixed(1) + 'k' : String(Math.round(a));
  return (v > 0 ? '+' : v < 0 ? '−' : '') + s;
}
const gcls = v => v == null ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '';
const FMT = {
  pct: v => (v * 100).toFixed(0) + '%',
  f2: v => v.toFixed(2), f1: v => v.toFixed(1),
  int: v => Math.round(v).toLocaleString('en-GB'),
  k: v => Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(Math.round(v)),
  sec: v => Math.round(v) + 's',
  signed: v => gold(Math.round(v)),
};
const stat = (key, v) => v == null ? '-' : FMT[STAT[key].fmt](v);
const pc1 = v => v == null ? '-' : v.toFixed(1) + '%';
function ord(n) {
  if (n == null) return '-';
  n = Math.round(n);
  const s = ['th', 'st', 'nd', 'rd'], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
const mmss = t => Math.floor(t / 60) + ':' + String(Math.floor(t % 60)).padStart(2, '0');
const DT = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const DS = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
const when = ms => DT.format(new Date(ms));
const QUEUE = { 420: 'Ranked Solo/Duo', 440: 'Ranked Flex', 710: 'Ranked 5s' };

/* ---- people and champions ---------------------------------------------------- */
const C = slug => D.champs[slug] || { n: slug, i: slug, c: '', t: '' };
function cicon(slug, s = 22) {
  return `<img class="ci" width="${s}" height="${s}" loading="lazy" alt="" ` +
    `src="https://ddragon.leagueoflegends.com/cdn/${VER}/img/champion/${encodeURIComponent(C(slug).i)}.png" ` +
    `onerror="this.style.visibility='hidden'">`;
}
function iicon(id, s = 22) {
  return `<img class="ii" width="${s}" height="${s}" loading="lazy" alt="" ` +
    `src="https://ddragon.leagueoflegends.com/cdn/${VER}/img/item/${id}.png" onerror="this.style.visibility='hidden'">`;
}
const champ = (slug, s = 22) => `<span class="cell-champ">${cicon(slug, s)}<b>${esc(C(slug).n)}</b></span>`;
const col = label => CFG.colors[label] || '#aeb6c6';
const fn = label => `<b style="color:${col(label)}">${esc(label)}</b>`;
const av = label => `<span class="av" style="background:${col(label)}">${esc(label.slice(0, 2))}</span>`;
const who = label => `<span class="cell-champ">${av(label)}${fn(label)}</span>`;
const low = n => n < 10 ? ' <span class="tag low">low sample</span>' : '';

/* ---- colour scales ------------------------------------------------------------ */
function blend(a, b, t) { return a.map((v, i) => Math.round(v + (b[i] - v) * t)); }
const NEUTRAL = [38, 44, 60], GREEN = [28, 128, 80], RED = [168, 50, 64];
/* Red below, grey at the middle, green above. `span` is how far from the
   middle full colour is reached. */
function heat(v, mid = 50, span = 15) {
  if (v == null) return 'transparent';
  const t = Math.max(-1, Math.min(1, (v - mid) / span));
  return `rgb(${blend(NEUTRAL, t >= 0 ? GREEN : RED, Math.abs(t))})`;
}
const pcClass = p => p == null ? 'mid' : p >= 55 ? '' : p <= 40 ? 'low' : 'mid';
function pcbar(p) {
  if (p == null) return '<span class="muted small">not enough games</span>';
  return `<div class="pcbar"><div class="bar pc ${pcClass(p)}"><i style="width:${Math.max(3, Math.min(100, p))}%"></i></div>` +
    `<span class="pcnum">${ord(p)}</span></div>`;
}
function perfBar(v) {
  return `<div class="perf"><div class="bar"><i style="width:${Math.max(3, Math.min(100, v))}%"></i></div><b>${v}</b></div>`;
}
const verdict = v => !v ? '<span class="muted">-</span>'
  : `<span class="verdict ${v}">${v === 'above' ? '▲ above' : v === 'below' ? '▼ below' : '≈ average'}</span>`;

/* ---- pills -------------------------------------------------------------------- */
const pill = (label, on, attrs, extra = '') =>
  `<button type="button" class="pill${on ? ' on' : ''}${extra}" ${attrs}>${label}</button>`;
function friendPills(key, current, names, withAll) {
  let out = withAll ? pill('All friends', current === 'All', set({ [key]: 'All' })) : '';
  names.forEach(l => { out += pill(av(l) + esc(l), current === l, set({ [key]: l })); });
  return `<div class="pills">${out}</div>`;
}

/* ---- charts ------------------------------------------------------------------- */
function radar(labels, series, o = {}) {
  const W = o.w || 400, H = o.h || 340, cx = W / 2, cy = H / 2 + 2, R = o.r || 112, n = labels.length;
  const pt = (i, v) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [cx + Math.cos(a) * R * v / 100, cy + Math.sin(a) * R * v / 100];
  };
  const poly = vals => vals.map((v, i) => pt(i, v == null ? 0 : Math.max(4, v)).map(x => x.toFixed(1)).join(',')).join(' ');
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Radar chart')}">`;
  [25, 50, 75, 100].forEach(r => {
    s += `<polygon points="${poly(labels.map(() => r))}" fill="none" stroke="${r === 50 ? '#56607a' : '#2a3040'}" ` +
      `stroke-width="1"${r === 50 ? ' stroke-dasharray="4 4"' : ''}/>`;
  });
  labels.forEach((_, i) => { const p = pt(i, 100); s += `<line x1="${cx}" y1="${cy}" x2="${p[0].toFixed(1)}" y2="${p[1].toFixed(1)}" class="axis"/>`; });
  series.forEach(se => {
    if (!se || !se.vals) return;
    s += `<polygon points="${poly(se.vals)}" fill="${se.color}" fill-opacity="${se.dash ? 0.06 : 0.16}" stroke="${se.color}" ` +
      `stroke-width="2"${se.dash ? ' stroke-dasharray="5 4"' : ''} stroke-linejoin="round"/>`;
    if (!se.dash) se.vals.forEach((v, i) => { const p = pt(i, v == null ? 0 : Math.max(4, v)); s += `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="${se.color}"/>`; });
  });
  labels.forEach((lab, i) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n, x = cx + Math.cos(a) * (R + 16), y = cy + Math.sin(a) * (R + 16);
    const anchor = Math.abs(Math.cos(a)) < 0.3 ? 'middle' : Math.cos(a) > 0 ? 'start' : 'end';
    const words = lab.split(' ');
    let lines = [lab];
    if (lab.length > 11 && words.length > 1) {
      const half = Math.ceil(words.length / 2);
      lines = [words.slice(0, half).join(' '), words.slice(half).join(' ')];
    }
    const y0 = y - (lines.length - 1) * 6.5 + (Math.sin(a) > 0.3 ? 8 : Math.sin(a) < -0.3 ? -2 : 4);
    lines.forEach((ln, k) => { s += `<text class="lbl" x="${x.toFixed(1)}" y="${(y0 + k * 13).toFixed(1)}" text-anchor="${anchor}">${esc(ln)}</text>`; });
  });
  return s + '</svg>';
}

/* A team gold lead through a game: blue above the line, red below it. */
let _clip = 0;
function leadChart(series, dur, o = {}) {
  const W = o.w || 760, H = o.h || 300, L = 46, Rm = 14, T = o.objs ? 34 : 14, B = 26;
  const n = series.length, tmax = dur / 60;
  const tx = i => i === n - 1 ? tmax : i;
  const peak = Math.max(2000, ...series.map(Math.abs));
  const top = Math.ceil(peak / 2000) * 2000;
  const x = t => L + (W - L - Rm) * t / tmax, y = v => T + (H - T - B) * (top - v) / (2 * top);
  const line = series.map((v, i) => `${i ? 'L' : 'M'}${x(tx(i)).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${x(tmax).toFixed(1)} ${y(0).toFixed(1)} L${x(0).toFixed(1)} ${y(0).toFixed(1)} Z`;
  const id = 'lc' + (++_clip);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Team gold lead by minute">` +
    `<defs><clipPath id="${id}a"><rect x="0" y="0" width="${W}" height="${y(0).toFixed(1)}"/></clipPath>` +
    `<clipPath id="${id}b"><rect x="0" y="${y(0).toFixed(1)}" width="${W}" height="${H}"/></clipPath></defs>`;
  for (let g = -top; g <= top; g += top / 2) {
    s += `<line x1="${L}" x2="${W - Rm}" y1="${y(g).toFixed(1)}" y2="${y(g).toFixed(1)}" class="axis"${g === 0 ? ' stroke="#56607a"' : ''}/>` +
      `<text x="${L - 8}" y="${(y(g) + 4).toFixed(1)}" text-anchor="end">${g === 0 ? '0' : gold(g)}</text>`;
  }
  const tick = W < 620 && tmax > 22 ? 10 : 5;
  for (let t = 0; t <= tmax; t += tick) s += `<text x="${x(t).toFixed(1)}" y="${H - 6}" text-anchor="middle">${t}:00</text>`;
  s += `<path d="${area}" fill="#4c8dff" fill-opacity=".28" clip-path="url(#${id}a)"/>` +
    `<path d="${area}" fill="#ef5350" fill-opacity=".28" clip-path="url(#${id}b)"/>` +
    `<path d="${line}" fill="none" stroke="#4c8dff" stroke-width="2" clip-path="url(#${id}a)"/>` +
    `<path d="${line}" fill="none" stroke="#ef5350" stroke-width="2" clip-path="url(#${id}b)"/>`;
  if (o.mark != null && o.mark <= tmax) {
    s += `<line x1="${x(o.mark).toFixed(1)}" x2="${x(o.mark).toFixed(1)}" y1="${T}" y2="${H - B}" stroke="#56607a" stroke-dasharray="4 4"/>` +
      `<text x="${(x(o.mark) + 5).toFixed(1)}" y="${H - B - 5}">${o.mark}:00</text>`;
  }
  (o.objs || []).forEach(ob => {
    /* [seconds, letter, mine(1/0), stolen(1/0)] */
    const px = x(Math.min(tmax, ob[0] / 60)).toFixed(1);
    s += (ob[3] ? `<circle cx="${px}" cy="16" r="12" fill="none" stroke="#e6b450" stroke-dasharray="3 3"/>` : '') +
      `<circle cx="${px}" cy="16" r="9" fill="${ob[2] ? '#4c8dff' : '#ef5350'}"/>` +
      `<text x="${px}" y="19.5" text-anchor="middle" style="fill:#fff;font-size:10px;font-weight:800">${ob[1]}</text>`;
  });
  return s + '</svg>';
}

function lineChart(lines, o) {
  /* lines: [{pts: [[x, y]...], color, dash, width}], o: {x0,x1,y0,y1,xt:[...],yt:[...],xf,yf,band,vline} */
  const W = o.w || 760, H = o.h || 320, L = o.l || 46, Rm = o.r || 16, T = 14, B = 28;
  const x = v => L + (W - L - Rm) * (v - o.x0) / (o.x1 - o.x0), y = v => T + (H - T - B) * (o.y1 - v) / (o.y1 - o.y0);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Chart')}">`;
  (o.yt || []).forEach(v => {
    s += `<line x1="${L}" x2="${W - Rm}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="axis"/>` +
      `<text x="${L - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${esc(o.yf ? o.yf(v) : v)}</text>`;
  });
  (o.xt || []).forEach(v => { s += `<text x="${x(v).toFixed(1)}" y="${H - 7}" text-anchor="middle">${esc(o.xf ? o.xf(v) : v)}</text>`; });
  if (o.vline != null) s += `<line x1="${x(o.vline).toFixed(1)}" x2="${x(o.vline).toFixed(1)}" y1="${T}" y2="${H - B}" stroke="#56607a" stroke-dasharray="4 4"/>`;
  if (o.band) {
    const up = o.band.hi.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
    const dn = o.band.lo.slice().reverse().map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
    s += `<polygon points="${up} ${dn}" fill="${o.band.color || '#8b6cf6'}" fill-opacity=".14"/>`;
  }
  const ends = [];
  lines.forEach(ln => {
    const pts = ln.pts.filter(p => p[1] != null);
    if (pts.length < 2) return;
    s += `<path d="${pts.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(' ')}" fill="none" ` +
      `stroke="${ln.color}" stroke-width="${ln.width || 2}"${ln.dash ? ` stroke-dasharray="${ln.dash}"` : ''} stroke-linejoin="round"/>`;
    if (ln.end) { const p = pts[pts.length - 1]; ends.push({ x: x(p[0]) + 6, y: y(p[1]) + 4, c: ln.color, t: ln.end }); }
  });
  ends.sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 13) ends[i].y = ends[i - 1].y + 13;
  ends.forEach(e => { s += `<text x="${e.x.toFixed(1)}" y="${e.y.toFixed(1)}" style="fill:${e.c};font-weight:700">${esc(e.t)}</text>`; });
  (o.dots || []).forEach(d => { s += `<circle cx="${x(d[0]).toFixed(1)}" cy="${y(d[1]).toFixed(1)}" r="4" fill="#fff" stroke="#10131a" stroke-width="1.5"/>`; });
  return s + '</svg>';
}

function spark(vals, color) {
  const pts = vals.map((v, i) => [i, v]).filter(p => p[1] != null);
  if (pts.length < 2) return '';
  const lo = Math.min(...pts.map(p => p[1])) - 4, hi = Math.max(...pts.map(p => p[1])) + 4;
  const x = i => 6 + 148 * i / (vals.length - 1), y = v => 6 + 38 * (hi - v) / (hi - lo || 1);
  return `<svg class="chart" viewBox="0 0 160 50" role="img" aria-label="Winrate by game number">` +
    `<path d="${pts.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2"/></svg>`;
}

/* The map is drawn rather than loaded: lanes, river, bases and jungle as plain
   shapes, in stored map units with y flipped so blue base is bottom left. */
const my = y => MAPQ - y;
function mapBase() {
  return `<rect x="0" y="0" width="${MAPQ}" height="${MAPQ}" rx="8" fill="#0e1a15"/>` +
    [[62, 150], [92, 104], [150, 82], [176, 128], [70, 200 - 30], [128, 58], [140, 150], [96, 176 - 96 + 40]].map(p =>
      `<circle cx="${p[0]}" cy="${my(p[1])}" r="17" fill="#15261d"/>`).join('') +
    `<path d="M34 ${my(198)} L198 ${my(34)}" stroke="#172c47" stroke-width="15" stroke-linecap="round" fill="none"/>` +
    `<path d="M16 ${my(34)} L16 ${my(216)} L198 ${my(216)}" stroke="#203427" stroke-width="10" stroke-linejoin="round" stroke-linecap="round" fill="none"/>` +
    `<path d="M34 ${my(16)} L216 ${my(16)} L216 ${my(198)}" stroke="#203427" stroke-width="10" stroke-linejoin="round" stroke-linecap="round" fill="none"/>` +
    `<path d="M36 ${my(36)} L196 ${my(196)}" stroke="#203427" stroke-width="10" stroke-linecap="round" fill="none"/>` +
    `<circle cx="64" cy="${my(168)}" r="7" fill="#1d2d44"/><circle cx="168" cy="${my(64)}" r="7" fill="#1d2d44"/>` +
    `<path d="M0 ${MAPQ} L0 ${MAPQ - 42} A42 42 0 0 1 42 ${MAPQ} Z" fill="#17305a"/>` +
    `<path d="M${MAPQ} 0 L${MAPQ - 42} 0 A42 42 0 0 0 ${MAPQ} 42 Z" fill="#4a1c22"/>`;
}
const mapSvg = inner => `<svg viewBox="0 0 ${MAPQ} ${MAPQ}" role="img" aria-label="Map">${mapBase()}${inner}</svg>`;
const cross = (x, y, c) => `<path d="M${x - 3} ${y - 3} L${x + 3} ${y + 3} M${x + 3} ${y - 3} L${x - 3} ${y + 3}" stroke="${c}" stroke-width="1.6" stroke-linecap="round"/>`;
function dots(flat, color, r = 2.6) {
  let s = '';
  for (let i = 0; i + 1 < flat.length; i += 2) s += `<circle cx="${flat[i]}" cy="${my(flat[i + 1])}" r="${r}" fill="${color}" stroke="#0b0e14" stroke-width=".7"/>`;
  return s;
}
function crosses(flat, color) {
  let s = '';
  for (let i = 0; i + 1 < flat.length; i += 2) s += cross(flat[i], my(flat[i + 1]), color);
  return s;
}

const card = (title, hint, body, extra = '') =>
  `<section class="card"><h2>${title}${extra}</h2>${hint ? `<p class="hint">${hint}</p>` : '<div style="height:14px"></div>'}${body}</section>`;
const tile = (lab, big, sub = '', cls = '') =>
  `<div class="tile ${cls}"><div class="lab">${lab}</div><div class="big">${big}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>`;
const empty = msg => `<div class="card"><div class="empty">${msg}</div></div>`;
