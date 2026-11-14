'use strict';
/* The analysis page renders in the browser from one embedded JSON document.
   Every season-wide number arrives already worked out by analysis.py. The one
   thing done here as well as there is scoring a single game, because a game's
   file holds only raw values (see public_game) and its score depends on
   baselines that move; that arithmetic is a copy of scoring.py, and Check at
   the end of a4_more.js compares the two on real games. The rest of this file
   is layout, formatting and SVG. */

const D = JSON.parse(document.getElementById('analysis-data').textContent);
const CFG = JSON.parse(document.getElementById('analysis-config').textContent);
const ROLES = D.meta.roles, RN = D.meta.roleName, STAT = D.meta.stats;
const FR = D.meta.friends.map(f => f.label);
const VER = D.meta.ddragon || '15.1.1';
const TIERS = D.meta.tiers, TSHORT = D.meta.tierShort, SC = D.scoring;
const TABS = [['game', 'Game breakdown'], ['players', 'Players'], ['champions', 'Champions'],
  ['roles', 'Roles & classes'], ['time', 'Time patterns'], ['duos', 'Duos & stacks'], ['flow', 'Game flow'], ['records', 'Records']];
const MAPQ = 232;
/* Small-sample rules, the same on every tab: under ten games an average is
   greyed, under five a cell is left blank. */
const LOW = 10, BLANK = 5;

/* ---- state lives in the URL, so any view can be linked to ----------------- */
const KEYS = ['tab', 'game', 'team', 'gwho', 'player', 'role', 'champ', 'crole', 'cwho', 'crf', 'csort', 'rtab', 'cls',
  'who', 'metric', 'queue', 'dview', 'dwho', 'dchamp', 'drole', 'dshow'];
function parseHash() {
  const o = {};
  location.hash.slice(1).split('&').forEach(kv => {
    const i = kv.indexOf('=');
    if (i > 0) o[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1));
  });
  return o;
}
/* On the merged page a second account is its owner. Links written for one
   account (the Basic page names accounts) and game files (which name the
   account that played) are both read through this. */
const OWNER = {};
D.meta.friends.forEach(f => (f.accounts || [f.label]).forEach(a => { OWNER[a] = f.label; }));
function ownState(o) { ['player', 'gwho', 'who', 'dwho', 'cwho'].forEach(k => { if (o[k] && OWNER[o[k]]) o[k] = OWNER[o[k]]; }); return o; }
const S = ownState(Object.assign({ tab: 'game' }, parseHash()));
const UI = { hl: { pos: 1 }, hphase: '0', ml: { pos: 1 }, mapT: null, focus: null, rt: null, fmode: 'scale', cexp: {}, q: '' };
function setState(patch) {
  Object.assign(S, patch);
  const h = KEYS.filter(k => S[k] != null && S[k] !== '').map(k => k + '=' + encodeURIComponent(S[k])).join('&');
  history.replaceState(null, '', '#' + h);
  render();
}
window.addEventListener('hashchange', () => { KEYS.forEach(k => delete S[k]); ownState(Object.assign(S, { tab: 'game' }, parseHash())); render(); });

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
const signed = (v, unit = '') => v == null ? '-' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + unit;
const FMT = {
  pct: v => (v * 100).toFixed(0) + '%',
  f2: v => v.toFixed(2), f1: v => v.toFixed(1),
  int: v => Math.round(v).toLocaleString('en-GB'),
  k: v => Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(Math.round(v)),
  sec: v => Math.round(v) + 's',
  signed: v => gold(Math.round(v)),
};
const stat = (key, v) => v == null ? '-' : FMT[STAT[key].fmt](v);
const statName = k => STAT[k].label.replace(' / game', '') + (STAT[k].up ? '' : ' (fewer)');
const pc1 = v => v == null ? '-' : v.toFixed(1) + '%';
const pc0 = v => v == null ? '-' : Math.round(v) + '%';
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
/* "Gold junglers", not "Gold jungles". */
const RLS = { TOP: 'top laners', JUNGLE: 'junglers', MIDDLE: 'mid laners', BOTTOM: 'ADCs', UTILITY: 'supports' };
const plural = (n, one, many) => n + ' ' + (n === 1 ? one : (many || one + 's'));

/* ---- ranks -------------------------------------------------------------------- */
const TCOL = ['#7d8597', '#b9825a', '#aab3c5', '#f0b232', '#38bdf8', '#34d399', '#b08cff', '#e879f9', '#fb7185', '#fde047'];
const DIV = ['', 'I', 'II', 'III', 'IV'];
const rankName = r => !r || r[0] == null ? 'Unranked' : TIERS[r[0]] + (r[0] >= 7 ? '' : ' ' + DIV[r[1] || 4]);
const tierName = t => t == null ? 'all ranks' : TIERS[t];
const rankChip = (r, pre = '') => !r || r[0] == null ? '' :
  `<span class="pill sm still" style="color:${TCOL[r[0]]};border-color:${TCOL[r[0]]}55">${pre}${esc(rankName(r))}</span>`;
const tierText = (t, text) => `<b style="color:${TCOL[t]}">${esc(text || TIERS[t])}</b>`;
/* A copy of scoring.rank_weight. */
function rankWeight(r) {
  if (!r || r[0] == null) return null;
  if (r[0] >= 9) return 1.10;
  if (r[0] === 8) return 1.05;
  if (r[0] === 7) return 1.00;
  return Math.round((0.99 - 0.05 * (6 - r[0]) - [0, 0, 0.01, 0.02, 0.04][r[1] || 4]) * 100) / 100;
}

/* ---- scoring one game: a copy of scoring.py --------------------------------- */
const baseKey = (role, tier) => tier != null && (SC.quant[role] || {})[tier] ? String(tier) : 'all';
/* scoring.percentile. A tie takes the middle of the points it ties with;
   anything else is placed by straight line between its neighbours. */
function pctOf(role, tier, key, v) {
  const q = ((SC.quant[role] || {})[baseKey(role, tier)] || {})[key];
  if (!q || v == null) return null;
  const n = q.length;
  let lo = 0, hi = 0;
  for (let i = 0; i < n; i++) { if (q[i] < v) lo++; if (q[i] <= v) hi++; }
  let pos;
  if (hi > lo) pos = (lo + hi - 1) / 2;
  else if (lo === 0) pos = 0;
  else if (lo === n) pos = n - 1;
  else pos = lo - 1 + (v - q[lo - 1]) / (q[lo] - q[lo - 1]);
  const p = 100 * pos / (n - 1);
  return STAT[key].up ? p : 100 - p;
}
/* scoring.plan: which metrics score a champion in a role. */
function planFor(champ, role) {
  const slug = String(champ || '').toLowerCase(), c = C(champ), over = SC.overrides[slug] || {};
  const drop = (over.drop || {})[role] || [], add = (over.add || {})[role] || [];
  const roleKeys = (SC.role[role] || []).filter(m => !drop.includes(m));
  add.forEach(m => { if (!roleKeys.includes(m)) roleKeys.push(m); });
  const tags = c.tg || [];
  const w = Object.assign({}, tags.includes('Hypercarry') ? SC.hypercarry : {}, over.weight || {});
  const out = roleKeys.map(m => ['role', m, w[m] || 1, null]), used = new Set(roleKeys);
  const classKeys = (c.c === 'Specialist' && SC.specialist[slug]) || SC.cls[c.c] || [];
  classKeys.forEach(m => { if (!used.has(m)) { out.push(['class', m, 1, null]); used.add(m); } });
  let taken = 0;
  tags.forEach(tag => {
    const m = SC.tag[tag];
    if (m && !used.has(m) && taken < 2) { out.push(['tag', m, 1, tag]); used.add(m); taken++; }
  });
  return out;
}
/* scoring.game_score. Returns {score, lines, layers}; score is null when no
   role metric could be ranked. */
function gameScore(champ, role, tier, values) {
  const layers = {}, lines = [];
  planFor(champ, role).forEach(([layer, m, w, tag]) => {
    const p = pctOf(role, tier, m, values[m]);
    if (p == null) return;
    const acc = layers[layer] || (layers[layer] = [0, 0]);
    acc[0] += p * w; acc[1] += w;
    lines.push({ layer, m, tag, v: values[m], p, w });
  });
  if (!layers.role) return { score: null, lines, layers: {} };
  let total = 0, sum = 0;
  const avg = {};
  Object.keys(layers).forEach(l => { avg[l] = layers[l][0] / layers[l][1]; total += SC.layer[l]; sum += SC.layer[l] * avg[l]; });
  return { score: sum / total, lines, layers: avg };
}

/* ---- people and champions ---------------------------------------------------- */
const C = slug => D.champs[slug] || { n: slug, i: slug, c: '', cs: [], tg: [], f: '', s: 0 };
const champUrl = slug => `https://ddragon.leagueoflegends.com/cdn/${VER}/img/champion/${encodeURIComponent(C(slug).i)}.png`;
function cicon(slug, s = 22, sq = false) {
  return `<img class="ci${sq ? ' sq' : ''}" width="${s}" height="${s}" loading="lazy" alt="" src="${champUrl(slug)}" ` +
    `onerror="this.style.visibility='hidden'">`;
}
function iicon(id, s = 22) {
  return `<img class="ii" width="${s}" height="${s}" loading="lazy" alt="" ` +
    `src="https://ddragon.leagueoflegends.com/cdn/${VER}/img/item/${id}.png" onerror="this.style.visibility='hidden'">`;
}
const champ = (slug, s = 22) => `<span class="cell-champ">${cicon(slug, s)}<b>${esc(C(slug).n)}</b></span>`;
const col = label => CFG.colors[label] || '#aeb6c6';
const fn = label => `<b style="color:${col(label)}">${esc(label)}</b>`;
/* A player's face: the champion portrait they (or their mastery) chose, ringed
   in their own colour, or their initials when there is no portrait to show. */
function av(label, size = 22) {
  const u = window.Avatars && Avatars.url(label);
  if (!u) return `<span class="av" style="background:${col(label)};width:${size}px;height:${size}px">${esc(label.slice(0, 2))}</span>`;
  return `<span class="av img" style="width:${size}px;height:${size}px;box-shadow:0 0 0 2px ${col(label)}">` +
    `<img alt="" loading="lazy" src="${u}" onerror="this.remove()"></span>`;
}
/* Class and tags, each once. A champion with two wiki classes shows both. */
const classChips = slug => (C(slug).cs || []).map(c => `<span class="tag cls">${esc(c)}</span>`).join('') +
  (C(slug).tg || []).map(t => `<span class="tag tg${SC.tag[t] ? ' on' : ''}" title="${SC.tag[t] ? 'Scored as ' + esc(STAT[SC.tag[t]].label) : 'Descriptive only'}">${esc(t)}</span>`).join('');

/* Real game art for objectives and roles, from Community Dragon's mirror of
   the client's own files. It is a volunteer-run host, so nothing here depends
   on it answering: every icon sits on top of the letter or word it stands for
   and simply is not there if the image does not load. */
const CDRAGON = 'https://raw.communitydragon.org/latest/';
const MON_ICON = { 'DRAGON:FIRE_DRAGON': 'dragon_infernal', 'DRAGON:WATER_DRAGON': 'dragon_ocean', 'DRAGON:EARTH_DRAGON': 'dragon_mountain',
  'DRAGON:AIR_DRAGON': 'dragon_cloud', 'DRAGON:HEXTECH_DRAGON': 'dragon_hextech', 'DRAGON:CHEMTECH_DRAGON': 'dragon_chemtech',
  'DRAGON:ELDER_DRAGON': 'dragon_elder', RIFTHERALD: 'riftherald', BARON_NASHOR: 'baron', HORDE: 'grub', ATAKHAN: 'atakhan_r',
  TOWER: 'tower', INHIB: 'inhibitor' };
const monUrl = code => CDRAGON + 'game/assets/ux/minimap/icons/' + (MON_ICON[code] || 'dragon') + '.png';
const ROLE_ICON = { TOP: 'top', JUNGLE: 'jungle', MIDDLE: 'middle', BOTTOM: 'bottom', UTILITY: 'utility' };
const ricon = (role, s = 16) => !ROLE_ICON[role] ? '' :
  `<img class="ri" width="${s}" height="${s}" alt="" loading="lazy" onerror="this.remove()" ` +
  `src="${CDRAGON}plugins/rcp-fe-lol-clash/global/default/assets/images/position-selector/positions/icon-position-${ROLE_ICON[role]}.png">`;
/* An objective badge: team-coloured ring, the monster's icon, its letter underneath as the fallback. */
const monBadge = (code, letter, mine, s = 26) =>
  `<span class="mon ${mine ? 'b' : 'r'}" style="width:${s}px;height:${s}px"><span>${letter}</span>` +
  `<img alt="" loading="lazy" src="${monUrl(code)}" onload="this.previousElementSibling.remove()" onerror="this.remove()"></span>`;
const who = label => `<span class="cell-champ">${av(label)}${fn(label)}</span>`;
const low = n => n < LOW ? ' <span class="tag low">low</span>' : '';

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
/* The same, but a cell with too few games behind it gets no colour at all:
   "100%, 1 game" in full green is what people notice, however faint the text. */
const heatN = (v, games, mid, span) => games < BLANK ? `rgb(${NEUTRAL})` : heat(v, mid, span);
const pcClass = p => p == null ? 'mid' : p >= 55 ? '' : p <= 40 ? 'low' : 'mid';
function pcbar(p) {
  if (p == null) return '<span class="muted small">not enough games</span>';
  return `<div class="pcbar"><div class="bar pc ${pcClass(p)}"><i style="width:${Math.max(3, Math.min(100, p))}%"></i></div>` +
    `<span class="pcnum">${ord(p)}</span></div>`;
}
function scoreBar(v, title = '') {
  if (v == null) return '<span class="muted">-</span>';
  return `<div class="perf" title="${esc(title)}"><div class="bar"><i style="width:${Math.max(3, Math.min(100, v))}%"></i></div><b>${v.toFixed(1)}</b></div>`;
}
const verdict = v => !v ? '<span class="muted">-</span>'
  : `<span class="verdict ${v}">${v === 'above' ? '▲ above' : v === 'below' ? '▼ below' : '≈ average'}</span>`;
/* A bar with a number on the right: a winrate, with 50% marked. */
const wrBar = (wr, color) => `<div class="wrbar"><i style="width:${Math.max(2, Math.min(100, wr))}%;background:${color}"></i><em></em></div>`;

/* ---- pills -------------------------------------------------------------------- */
const pill = (label, on, attrs, extra = '') =>
  `<button type="button" class="pill${on ? ' on' : ''}${extra}" ${attrs}>${label}</button>`;
function friendPills(key, current, names, withAll) {
  let out = withAll ? pill('All friends', current === 'All', set({ [key]: 'All' })) : '';
  names.forEach(l => { out += pill(av(l) + esc(l), current === l, set({ [key]: l })); });
  return `<div class="pills">${out}</div>`;
}
/* A toggle that keeps its own state in UI rather than the URL. */
const check = (label, on, patch, extra = ' sm') => pill((on ? '☑ ' : '☐ ') + label, on, ui(patch), extra);

/* ---- charts ------------------------------------------------------------------- */
/* series: [{vals, color, fill, width}]. Every line is solid: a dashed
   comparison line was read as "less real" rather than "the comparison". */
function radar(labels, series, o = {}) {
  const W = o.w || 400, H = o.h || 340, cx = W / 2, cy = H / 2 + 2, R = o.r || 112, n = labels.length;
  const pt = (i, v) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [cx + Math.cos(a) * R * v / 100, cy + Math.sin(a) * R * v / 100];
  };
  const poly = vals => vals.map((v, i) => pt(i, v == null ? 0 : Math.max(4, v)).map(x => x.toFixed(1)).join(',')).join(' ');
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Radar chart')}">`;
  [25, 50, 75, 100].forEach(r => { s += `<polygon points="${poly(labels.map(() => r))}" fill="none" stroke="${r === 50 ? '#3a4258' : '#2a3040'}" stroke-width="1"/>`; });
  labels.forEach((_, i) => { const p = pt(i, 100); s += `<line x1="${cx}" y1="${cy}" x2="${p[0].toFixed(1)}" y2="${p[1].toFixed(1)}" class="axis"/>`; });
  series.forEach(se => {
    if (!se || !se.vals) return;
    s += `<polygon points="${poly(se.vals)}" fill="${se.color}" fill-opacity="${se.fill ? 0.18 : 0}" stroke="${se.color}" ` +
      `stroke-width="${se.width || 2}" stroke-linejoin="round"/>`;
    if (se.fill) se.vals.forEach((v, i) => { const p = pt(i, v == null ? 0 : Math.max(4, v)); s += `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="${se.color}"/>`; });
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

/* parts: [[label, value, colour]]. */
function donut(parts, big, small) {
  const total = parts.reduce((s, p) => s + p[1], 0) || 1, R = 52, CIRC = 2 * Math.PI * R;
  let off = 0, s = `<svg class="donut" viewBox="0 0 140 140" role="img" aria-label="${esc(parts.map(p => p[0] + ' ' + p[1]).join(', '))}">` +
    `<circle cx="70" cy="70" r="${R}" fill="none" stroke="#2a3040" stroke-width="18"/>`;
  parts.forEach(p => {
    const len = CIRC * p[1] / total;
    s += `<circle cx="70" cy="70" r="${R}" fill="none" stroke="${p[2]}" stroke-width="18" stroke-dasharray="${len.toFixed(2)} ${(CIRC - len).toFixed(2)}" ` +
      `stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 70 70)"><title>${esc(p[0])}: ${p[1]}</title></circle>`;
    off += len;
  });
  return s + `<text x="70" y="68" text-anchor="middle" style="fill:#f2f4f8;font-size:19px;font-weight:700">${esc(big)}</text>` +
    `<text x="70" y="86" text-anchor="middle" style="font-size:11px">${esc(small)}</text></svg>`;
}

/* A team gold lead through a game: blue above the line, red below it. */
let _clip = 0;
function leadChart(series, dur, o = {}) {
  const W = o.w || 760, H = o.h || 300, L = 46, Rm = 14, T = o.objs ? 42 : 14, B = 26;
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
  /* Towers are small ticks along the zero line, so they are there to be read
     without crowding the objectives above the chart. */
  (o.towers || []).forEach(tw => {
    const px = x(Math.min(tmax, tw[0] / 60)), up = tw[1];
    s += `<path d="M${px.toFixed(1)} ${(y(0) + (up ? -3 : 3)).toFixed(1)} v${up ? -7 : 7}" stroke="${up ? '#4c8dff' : '#ef5350'}" stroke-width="${tw[2] ? 3.4 : 2}" stroke-linecap="round">` +
      `<title>${up ? 'Your team' : 'Enemy'} took ${tw[2] ? 'an inhibitor' : 'a tower'} at ${mmss(tw[0])}</title></path>`;
  });
  (o.objs || []).forEach(ob => {
    /* [seconds, letter, mine(1/0), stolen(1/0), monster code] */
    const px = x(Math.min(tmax, ob[0] / 60)), ring = ob[2] ? '#4c8dff' : '#ef5350';
    s += (ob[3] ? `<circle cx="${px.toFixed(1)}" cy="19" r="16" fill="none" stroke="#e6b450" stroke-dasharray="3 3"/>` : '') +
      `<circle cx="${px.toFixed(1)}" cy="19" r="12" fill="#10131a" stroke="${ring}" stroke-width="2.5"/>` +
      `<text x="${px.toFixed(1)}" y="23" text-anchor="middle" style="fill:#fff;font-size:11px;font-weight:800">${ob[1]}</text>` +
      (ob[4] ? `<image href="${monUrl(ob[4])}" x="${(px - 9.5).toFixed(1)}" y="9.5" width="19" height="19" ` +
        `onload="this.previousElementSibling.remove()" onerror="this.remove()"/>` : '');
  });
  return s + '</svg>';
}

function lineChart(lines, o) {
  /* lines: [{pts: [[x, y]...], color, dash, width, end}], o: {x0,x1,y0,y1,xt:[...],yt:[...],xf,yf,band,vline,zero} */
  const W = o.w || 760, H = o.h || 320, L = o.l || 46, Rm = o.r || 16, T = 14, B = 28;
  const x = v => L + (W - L - Rm) * (v - o.x0) / (o.x1 - o.x0), y = v => T + (H - T - B) * (o.y1 - v) / (o.y1 - o.y0);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Chart')}">`;
  (o.yt || []).forEach(v => {
    s += `<line x1="${L}" x2="${W - Rm}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="axis"${o.zero && v === 0 ? ' stroke="#56607a"' : ''}/>` +
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

/* ---- the map ------------------------------------------------------------------
   Drawn by the page, from the vector copy of the minimap in
   analysis_assets/map: one set of shapes (the <g id="rift"> analysis_page.py
   puts in the document), coloured two ways by the class on the <svg>. "site"
   is the plain map; "zones" colours only the river and the jungle, for the
   views that count things by area. rift_zones.py is made from the same
   shapes, so what is counted in an area is what is drawn in it.

   Overlays are placed in stored map units (game units // 64), y flipped so
   blue base is bottom left. The drawing covers a little more than the
   playable square on every side. */
const MAP = { x0: -120 / 64, x1: 14870 / 64, y0: -120 / 64, y1: 14980 / 64 };
const MW = MAP.x1 - MAP.x0, MH = MAP.y1 - MAP.y0;
const my = y => MAP.y1 - y;
const mapSvg = (inner, theme = 'site') =>
  `<svg class="rift ${theme}" viewBox="${MAP.x0} 0 ${MW} ${MH}" role="img" aria-label="Map of Summoner's Rift">` +
  `<g transform="translate(${MAP.x0} 0) scale(${(MW / 1200).toFixed(5)} ${(MH / 1200).toFixed(5)})"><rect width="1200" height="1200" fill="#0c111b"/><use href="#rift"/></g>${inner}</svg>`;
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
/* The five layers a map can show, each on its own switch. "Kill
   participation" is kills and assists as one layer, for when the split does
   not matter. */
const LAYERS = [['pos', 'Positions'], ['kp', 'Kill participation'], ['k', 'Kills'], ['a', 'Assists'], ['d', 'Deaths']];
const layerPills = (key, cur) => LAYERS.map(l => check(l[1], !!cur[l[0]], { [key]: Object.assign({}, cur, { [l[0]]: cur[l[0]] ? 0 : 1 }) })).join('');
const KCOL = '#34d399', ACOL = '#38bdf8', DCOL = '#ff6b6b', KPCOL = '#c4b5fd';

const card = (title, hint, body, extra = '') =>
  `<section class="card"><h2>${title}${extra}</h2>${hint ? `<p class="hint">${hint}</p>` : '<div style="height:14px"></div>'}${body}</section>`;
const tile = (lab, big, sub = '', cls = '') =>
  `<div class="tile ${cls}"><div class="lab">${lab}</div><div class="big">${big}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>`;
const empty = msg => `<div class="card"><div class="empty">${msg}</div></div>`;
/* A wide table: scrolls sideways on a phone with its first column held still. */
const tableWrap = (inner, cls = '') => `<div class="scroll"><table class="tbl sticky ${cls}">${inner}</table></div>`;

/* ---- pop-up ------------------------------------------------------------------- */
function openModal(html) {
  closeModal();
  const el = document.createElement('div');
  el.className = 'modal-back';
  el.id = 'modal';
  el.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  el.addEventListener('click', e => { if (e.target === el || e.target.closest('[data-close]')) closeModal(); });
  document.body.appendChild(el);
  const btn = el.querySelector('[data-close]');
  if (btn) btn.focus();
}
function closeModal() { const el = document.getElementById('modal'); if (el) el.remove(); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
