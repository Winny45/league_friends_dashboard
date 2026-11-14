/* ---- Game breakdown ------------------------------------------------------------
   The list of games is in the page; each game's detail is not. A season of
   timelines is tens of megabytes, so they are published as one small file per
   day and fetched when a game is opened. */
const GAMES = D.games;
const dayDocs = {}, dayWait = {};
const dayOf = t0 => new Date(t0).toISOString().slice(0, 10);
function loadDay(day) {
  if (!dayWait[day]) {
    dayWait[day] = fetch('g/' + day + '.json').then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(doc => { dayDocs[day] = doc; return doc; });
  }
  return dayWait[day];
}
const isFriend = p => p.f && FR.includes(p.f);
/* Where a raw value sits in the lobby baseline for that role, 0 to 100, high
   always meaning good. The same mid-rank rule analysis.py uses on its rows. */
function pctOf(role, key, v) {
  const q = (D.quant[role] || {})[key];
  if (!q || v == null) return null;
  let lo = 0, hi = 0;
  for (let i = 0; i < q.length; i++) { if (q[i] < v) lo = i + 1; if (q[i] <= v) hi = i + 1; }
  const p = 100 * (lo + hi) / 2 / q.length;
  return Math.round(STAT[key].up ? p : 100 - p);
}
const MON = { 'DRAGON:FIRE_DRAGON': 'Infernal Drake', 'DRAGON:WATER_DRAGON': 'Ocean Drake', 'DRAGON:EARTH_DRAGON': 'Mountain Drake',
  'DRAGON:AIR_DRAGON': 'Cloud Drake', 'DRAGON:HEXTECH_DRAGON': 'Hextech Drake', 'DRAGON:CHEMTECH_DRAGON': 'Chemtech Drake',
  'DRAGON:ELDER_DRAGON': 'Elder Dragon', RIFTHERALD: 'Rift Herald', BARON_NASHOR: 'Baron Nashor', HORDE: 'Voidgrubs', ATAKHAN: 'Atakhan' };
const monLetter = c => c.startsWith('DRAGON') ? (c.includes('ELDER') ? 'E' : 'D') : ({ RIFTHERALD: 'H', BARON_NASHOR: 'B', HORDE: 'G', ATAKHAN: 'A' }[c] || '?');
function slopeAt(m) {
  const sl = D.flow.slopes, keys = Object.keys(sl).map(Number);
  if (!keys.length) return null;
  if (sl[m] != null) return sl[m];
  return sl[keys.reduce((a, b) => Math.abs(b - m) < Math.abs(a - m) ? b : a)];
}
function currentEntry(list) {
  if (S.game) {
    const hit = GAMES.find(g => g[0] === S.game && (!S.team || String(g[4]) === String(S.team))) || GAMES.find(g => g[0] === S.game);
    if (hit) return hit;
  }
  return list[0];
}
function tabGame() {
  if (!GAMES.length) return empty('No games are stored yet. They are fetched a few hundred at a time, newest first.');
  const names = FR.filter(l => GAMES.some(g => g[6].some(f => f[0] === l)));
  const me = names.includes(S.gwho) ? S.gwho : 'All';
  const list = me === 'All' ? GAMES : GAMES.filter(g => g[6].some(f => f[0] === me));
  const cur = currentEntry(list);
  let strip = '';
  const shown = list.slice(0, 40);
  if (!shown.includes(cur)) shown.unshift(cur);
  shown.forEach(g => {
    const f = (me !== 'All' && g[6].find(x => x[0] === me)) || g[6][0];
    strip += `<button type="button" class="gcard ${g[5] ? 'w' : 'l'}${g === cur ? ' on' : ''}" ${set({ game: g[0], team: g[4] })}>` +
      `<div class="who">${cicon(f[1], 26)}<span>${esc(C(f[1]).n)}<br><span style="color:${col(f[0])}">${esc(f[0])}${g[6].length > 1 ? ' +' + (g[6].length - 1) : ''}</span></span></div>` +
      `<div class="meta"><span class="tag ${g[5] ? 'win' : 'loss'}">${g[5] ? 'WIN' : 'LOSS'}</span><b>${f[3]}/${f[4]}/${f[5]}</b></div>` +
      `<div class="meta"><span>${DS.format(new Date(g[1]))}</span><span class="${gcls(f[6])}">${f[6] == null ? '' : '@15 ' + gold(f[6])}</span></div></button>`;
  });
  return `<div class="pillrow">${friendPills('gwho', me, names, true)}<span class="muted small">${list.length} stored games · newest first</span></div>` +
    `<div class="strip">${strip}</div><div id="game-body" data-id="${esc(cur[0])}" data-team="${cur[4]}"><div class="card"><div class="empty">Loading this game…</div></div></div>`;
}
let NOW = null;   /* {G, entry} for the game on screen, so the map can redraw without a fetch */
function fillGame() {
  const host = document.getElementById('game-body');
  if (!host) return;
  const entry = GAMES.find(g => g[0] === host.dataset.id && String(g[4]) === host.dataset.team);
  if (!entry) return;
  const day = dayOf(entry[1]);
  const draw = doc => {
    const G = doc[entry[0]];
    if (!document.body.contains(host) || host.dataset.id !== entry[0]) return;
    if (!G) { host.innerHTML = empty('This game is listed but its detail file has not been published yet.'); return; }
    NOW = { G, entry };
    if (UI.mapGame !== G.id) { UI.mapGame = G.id; UI.mapT = G.dur; UI.focus = null; stopPlay(); }
    NOW.kf = keyframes(G);
    host.innerHTML = gameBody(G, entry);
  };
  if (dayDocs[day]) draw(dayDocs[day]);
  else loadDay(day).then(draw).catch(err => { host.innerHTML = empty('Could not load this game (' + esc(err.message) + ').'); });
}
function gameBody(G, entry) {
  const team = entry[4], P = G.p, frames = P[0].g.length, lastWhole = frames - 2, win = G.win === team;
  const mine = P.map((p, i) => Object.assign({ pid: i + 1 }, p)).filter(p => p.t === team).sort((a, b) => ROLES.indexOf(a.r) - ROLES.indexOf(b.r));
  const theirs = P.map((p, i) => Object.assign({ pid: i + 1 }, p)).filter(p => p.t !== team).sort((a, b) => ROLES.indexOf(a.r) - ROLES.indexOf(b.r));
  const lead = []; for (let m = 0; m < frames; m++) lead.push(mine.reduce((s, p) => s + p.g[m], 0) - theirs.reduce((s, p) => s + p.g[m], 0));
  const chance = lead.map((v, m) => { const b = slopeAt(Math.min(m, lastWhole)); return b == null ? null : sig(b * v / 1000); });
  const friends = mine.filter(isFriend);
  const label = pid => { const p = P[pid - 1]; return p ? (isFriend(p) ? fn(p.f) : esc(C(p.c).n)) : '-'; };

  /* header */
  let lo = { v: 1, m: 0 }, hi = { v: 0, m: 0 };
  chance.forEach((c, m) => { if (c == null || m < 3 || m > lastWhole) return; if (c < lo.v) lo = { v: c, m }; if (c > hi.v) hi = { v: c, m }; });
  const minLead = Math.min(...lead), maxLead = Math.max(...lead), at = v => lead.indexOf(v);
  const c15 = lastWhole >= 15 ? chance[15] : null;
  let vt, vs;
  if (win && lo.v < 0.35) { vt = 'Comeback'; vs = `Won from ${Math.round(lo.v * 100)}% win chance`; }
  else if (!win && hi.v > 0.65) { vt = 'Throw'; vs = `Lost from ${Math.round(hi.v * 100)}% win chance`; }
  else if (win) { vt = minLead > -1500 ? 'Wire to wire' : 'Steady win'; vs = `Never below ${Math.round(lo.v * 100)}% win chance`; }
  else { vt = maxLead < 1500 ? 'Never ahead' : 'Slipped away'; vs = `Peaked at ${Math.round(hi.v * 100)}% win chance`; }
  const stackName = ['', 'Solo', 'Duo', 'Trio', 'Four', 'Five'][Math.min(5, friends.length)] || '';
  let out = `<section class="card" style="margin-bottom:20px"><div class="ghead"><div><div class="result ${win ? 'w' : 'l'}">${win ? 'VICTORY' : 'DEFEAT'}</div>` +
    `<div class="muted" style="margin-top:6px">${esc(QUEUE[G.q] || 'Ranked')} · ${mmss(G.dur)} · ${when(G.t0)}${G.patch ? ' · Patch ' + esc(G.patch) : ''}</div></div>` +
    `<div class="pills">${friends.map(p => `<span class="pill" style="cursor:default">${av(p.f)}${esc(p.f)}</span>`).join('')}${stackName ? `<span class="pill" style="cursor:default">${stackName}</span>` : ''}</div>` +
    `<div class="tiles">${tile('Win chance at 15 min', c15 == null ? '-' : Math.round(c15 * 100) + '%', c15 == null ? 'game ended before 15' : gold(lead[15]) + ' gold', 'inner')}` +
    (win || -minLead > maxLead ? tile(`Biggest deficit (${at(minLead)}:00)`, `<span class="${minLead < 0 ? 'neg' : ''}">${gold(minLead)}</span>`, '', 'inner')
      : tile(`Biggest lead (${at(maxLead)}:00)`, `<span class="pos">${gold(maxLead)}</span>`, '', 'inner')) +
    tile('', `<span style="color:${vt === 'Comeback' ? 'var(--warn)' : vt === 'Throw' ? 'var(--critical)' : 'inherit'}">${vt}</span>`, vs, 'inner') + '</div></div></section>';

  /* scoreboard */
  const k = v => v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v;
  const board = (rows, blue, mineSide) => `<div><div class="side-title ${blue ? 'blue' : 'red'}"><span>${blue ? 'Blue side' : 'Red side'}${mineSide ? ' · your team' : ''}</span></div>` +
    `<div class="scroll"><table class="tbl"><thead><tr><th>Role</th><th>Champion</th><th>Player</th><th class="num">K/D/A</th><th class="num">CS</th><th class="num">Gold</th><th class="num">Dmg</th><th class="num">Vis</th></tr></thead><tbody>` +
    rows.map(p => `<tr class="${isFriend(p) ? 'me' : ''}"><td class="muted"><span class="cell-champ">${ricon(p.r)}${RN[p.r] || '-'}</span></td><td>${champ(p.c)}</td>` +
      `<td>${isFriend(p) ? who(p.f) : '<span class="muted">' + esc(p.n) + '</span>'}</td><td class="num strong">${p.k}/${p.d}/${p.a}</td>` +
      `<td class="num">${p.cs}</td><td class="num">${k(p.gold)}</td><td class="num">${k(p.dmg)}</td><td class="num">${p.vis}</td></tr>`).join('') + '</tbody></table></div></div>';
  out += `<section class="card" style="margin-bottom:20px"><div class="grid g2" style="margin:0">${board(mine, team === 100, true)}${board(theirs, team !== 100, false)}</div></section>`;

  /* gold lead, lane differences, win chance */
  const objs = G.obj.map(o => [o[0], monLetter(o[1]), o[2] === team ? 1 : 0, o[5], o[1]]);
  const stolen = G.obj.filter(o => o[5]).map(o => `${esc(MON[o[1]] || o[1])} stolen by ${label(o[3])} at ${mmss(o[0])}`);
  const goldCard = card('Team gold lead', "Above the line is your team ahead. Each objective is marked when it was taken, ringed blue for yours and red for theirs. A dashed gold ring is a steal.",
    leadChart(lead, G.dur, { objs, h: 400, mark: lastWhole >= 15 ? 15 : null }) +
    `<div class="legend"><span><i class="sw" style="background:#4c8dff"></i>Your team's objective</span><span><i class="sw" style="background:#ef5350"></i>Enemy objective</span>` +
    (stolen.length ? `<span style="color:var(--warn)">◌ ${stolen.join(' · ')}</span>` : '') + '</div>');
  const dcell = (v, span) => `<td class="heat" style="${v == null ? '' : 'background:' + heat(v, 0, span)}">${v == null ? '-' : gold(v)}</td>`;
  const lanes = ROLES.map(r => {
    const a = mine.find(p => p.r === r), b = theirs.find(p => p.r === r);
    if (!a || !b) return '';
    const gd = m => m <= lastWhole ? a.g[m] - b.g[m] : null;
    const d = (x, y) => x == null || y == null ? null : x - y;
    const cs = d(a.c15, b.c15);
    return `<tr><td><span class="cell-champ">${ricon(r)}${r === 'BOTTOM' ? 'Bot (ADC)' : RN[r]}</span></td><td class="nowrap">${cicon(a.c, 20)} <span class="muted">vs</span> ${cicon(b.c, 20)}</td>` +
      `${dcell(gd(10), 1200)}${dcell(gd(15), 1800)}${dcell(d(a.x15, b.x15), 1500)}<td class="num">${cs == null ? '-' : (cs > 0 ? '+' : cs < 0 ? '−' : '') + Math.abs(cs)}</td></tr>`;
  }).join('');
  const cpts = chance.map((c, m) => [m === frames - 1 ? G.dur / 60 : m, c == null ? null : c * 100]);
  const ext = win ? lo : hi;
  const wc = lineChart([{ pts: cpts, color: '#b08cff', width: 2 }], { x0: 0, x1: G.dur / 60, y0: 0, y1: 100, h: 200, w: 520, l: 40,
    xt: [0, 10, 20, 30, 40].filter(t => t <= G.dur / 60), yt: [0, 50, 100], yf: v => v + '%', vline: ext.m, label: 'Win chance through the game' });
  const laneCard = card('Lane differences', 'Your laner minus their laner.',
    `<div class="scroll"><table class="tbl"><thead><tr><th>Lane</th><th>Matchup</th><th class="num">Gold@10</th><th class="num">Gold@15</th><th class="num">XP@15</th><th class="num">CS@15</th></tr></thead><tbody>${lanes}</tbody></table></div>` +
    `<h3>Win chance through the game</h3>${wc}<p class="muted small">${win ? 'Lowest' : 'Highest'} point: ${Math.round(ext.v * 100)}% at ${ext.m}:00.</p>`);
  out += `<div class="grid g-3-2">${goldCard}${laneCard}</div>`;

  /* objective log, map, this game against the usual */
  const log = G.obj.length ? `<div class="oblog">${G.obj.map(o => `<div class="row"><span class="muted">${mmss(o[0])}</span>${monBadge(o[1], monLetter(o[1]), o[2] === team)}` +
    `<div><b>${esc(MON[o[1]] || o[1])}${o[4] > 1 ? ' ×' + o[4] : ''}</b>${o[5] ? ' <span class="tag stolen">STOLEN</span>' : ''}` +
    `<div class="muted small">killer ${label(o[3])} · assists ${o[6].length ? o[6].map(label).join(', ') : 'none'}</div></div></div>`).join('')}</div>`
    : '<div class="empty">No epic monsters were taken.</div>';
  const logCard = card('Objective log', 'Who killed it and who helped.', log);
  const modes = [['kills', 'Kills'], ['pos', 'Positions']].map(m => pill(m[1], UI.mapMode === m[0], ui({ mapMode: m[0] }), ' sm')).join('');
  const mapCard = `<section class="card"><h2>Map<span class="pills" style="margin-left:auto">${modes}</span></h2><div style="height:12px"></div>` +
    `<div class="mapwrap" id="gmap">${gameMap()}</div><div class="scrub">` +
    `<button type="button" id="map-play" data-play aria-label="Play the game back">${PLAY.timer ? '\u275A\u275A' : '\u25B6'}</button>` +
    `<button type="button" data-step="-15" aria-label="Back 15 seconds">\u25C0</button>` +
    `<input type="range" id="map-t" min="0" max="${G.dur}" step="5" value="${UI.mapT}" aria-label="Time in the game">` +
    `<button type="button" data-step="15" aria-label="Forward 15 seconds">\u25B6</button>` +
    `<b id="map-t-label" class="num" style="min-width:52px">${mapLabel()}</b></div>` +
    `<div class="legend" id="gmap-legend">${mapLegend()}</div><p class="muted small">Riot records where everyone stands once a minute and exactly where each death happens. ` +
    `Between those points movement is drawn as a straight line, so a recall looks like a walk home. Ward positions are not in the data at all.</p></section>`;
  const fx = friends.filter(p => p.fx && D.meta.roleStats[p.r]);
  let radCard = card('This game vs usual', '', '<div class="empty">No tracked player with a role in this game.</div>');
  if (fx.length) {
    const p = fx.find(q => q.f === UI.focus) || fx[0], axes = D.meta.roleStats[p.r];
    const pcs = axes.map((a, i) => pctOf(p.r, a, p.fx[i]));
    const usual = ((D.usual[p.f] || {})[p.c + '|' + p.r]) || [0, null];
    const pick = fx.length > 1 ? `<div class="pills" style="margin-bottom:6px">${fx.map(q => pill(av(q.f) + esc(q.f), q === p, ui({ focus: q.f }), ' sm')).join('')}</div>` : '';
    radCard = card(`${esc(p.f)}'s game vs usual`, `${esc(RN[p.r])} · ${esc(C(p.c).n)}. Percentile vs ${RN[p.r].toLowerCase()}s in our lobbies.`,
      pick + radar(axes.map(a => STAT[a].label.replace(' / game', '') + (STAT[a].up ? '' : ' (fewer)')),
        [usual[1] ? { vals: usual[1], color: '#788296', dash: true } : null, { vals: pcs, color: col(p.f) }], { label: 'This game against the usual' }) +
      `<div class="legend"><span><i class="sw" style="background:${col(p.f)}"></i>This game</span><span><i class="sw" style="background:#788296"></i>${esc(p.f)}'s ${esc(C(p.c).n)} average (${usual[0]} games)</span></div>`);
  }
  out += `<div class="grid g3">${logCard}${mapCard}${radCard}</div>`;
  return out;
}
const mapLabel = () => mmss(Math.min(UI.mapT, NOW.G.dur));
function mapLegend() {
  return UI.mapMode === 'kills'
    ? `<span><i class="sw round" style="background:#34d399"></i>Your team's kills</span><span><span style="color:#ff6b6b;font-weight:800">\u2715</span> deaths</span><span class="muted">up to ${mapLabel()}, the last 30 seconds ringed</span>`
    : `<span><i class="sw round" style="background:#4c8dff"></i>your team</span><span><i class="sw round" style="background:#ef5350"></i>enemy</span><span class="muted">at ${mapLabel()} · faded = dead</span>`;
}
/* Everything known about where each player was, in time order: the one
   position a minute Riot samples, plus the exact spot and second of every
   death. That is all there is, and it is enough to play a game back. */
function keyframes(G) {
  const frames = G.p[0].g.length;
  const kf = G.p.map(p => {
    const out = [];
    for (let i = 0; i < frames; i++) out.push({ t: i < frames - 1 ? i * 60 : G.dur, x: p.xy[2 * i], y: p.xy[2 * i + 1] });
    return out;
  });
  G.kills.forEach(e => { if (e[4] >= 1 && e[4] <= 10) kf[e[4] - 1].push({ t: e[0], x: e[1], y: e[2], dead: true }); });
  kf.forEach(list => list.sort((a, b) => a.t - b.t));
  return kf;
}
function posAt(list, t) {
  let a = list[0];
  for (let i = 1; i < list.length && list[i].t <= t; i++) a = list[i];
  const b = list[list.indexOf(a) + 1];
  /* Someone who has just died stays where they fell, faded, until the next sample finds them again. */
  if (!b || a.dead) return { x: a.x, y: a.y, dead: !!a.dead && !!b };
  const f = (t - a.t) / (b.t - a.t || 1);
  return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, dead: false };
}
function gameMap() {
  const G = NOW.G, team = NOW.entry[4], t = Math.min(UI.mapT, G.dur);
  let s = '';
  if (UI.mapMode === 'kills') {
    G.kills.forEach(e => {
      if (e[0] > t) return;
      const killerTeam = e[3] >= 1 && e[3] <= 10 ? G.p[e[3] - 1].t : (G.p[e[4] - 1].t === 100 ? 200 : 100);
      const fresh = t - e[0] <= 30 && t < G.dur, ours = killerTeam === team;
      if (fresh) s += `<circle cx="${e[1]}" cy="${my(e[2])}" r="7" fill="none" stroke="${ours ? '#34d399' : '#ff6b6b'}" stroke-width="1.2" opacity=".9"/>`;
      s += ours ? `<circle cx="${e[1]}" cy="${my(e[2])}" r="${fresh ? 3.6 : 2.8}" fill="#34d399" stroke="#0b0e14" stroke-width=".7"/>` : cross(e[1], my(e[2]), '#ff6b6b');
    });
  } else {
    let defs = '';
    G.p.forEach((p, i) => {
      const q = posAt(NOW.kf[i], t), fr = isFriend(p), r = fr ? 8.5 : 6.5, cx = q.x.toFixed(1), cy = my(q.y).toFixed(1);
      const ring = fr ? col(p.f) : p.t === team ? '#4c8dff' : '#ef5350';
      defs += `<clipPath id="pc${i}"><circle cx="${cx}" cy="${cy}" r="${r}"/></clipPath>`;
      s += `<g${q.dead ? ' opacity=".4" style="filter:grayscale(1)"' : ''}><circle cx="${cx}" cy="${cy}" r="${r}" fill="${ring}"/>` +
        `<image href="${champUrl(p.c)}" x="${(q.x - r * 1.14).toFixed(1)}" y="${(my(q.y) - r * 1.14).toFixed(1)}" width="${(r * 2.28).toFixed(1)}" height="${(r * 2.28).toFixed(1)}" clip-path="url(#pc${i})"/>` +
        `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${ring}" stroke-width="${fr ? 2 : 1.5}"/>` +
        `<title>${esc(fr ? p.f + ' · ' : '')}${esc(C(p.c).n)}${q.dead ? ' (dead)' : ''}</title></g>`;
    });
    s = `<defs>${defs}</defs>` + s;
  }
  return mapSvg(s);
}
function redrawMap() {
  const host = document.getElementById('gmap');
  if (!host || !NOW) return;
  host.innerHTML = gameMap();
  document.getElementById('map-t-label').textContent = mapLabel();
  document.getElementById('gmap-legend').innerHTML = mapLegend();
}
/* Playback: about forty game-seconds a real second, so a half-hour game runs in under a minute. */
const PLAY = { timer: null };
function stopPlay() {
  if (PLAY.timer) { clearInterval(PLAY.timer); PLAY.timer = null; }
  const b = document.getElementById('map-play');
  if (b) b.textContent = '\u25B6';
}
function togglePlay() {
  if (PLAY.timer) return stopPlay();
  if (!NOW) return;
  if (UI.mapT >= NOW.G.dur) UI.mapT = 0;
  document.getElementById('map-play').textContent = '\u275A\u275A';
  PLAY.timer = setInterval(() => {
    const slider = document.getElementById('map-t');
    if (!NOW || !slider) return stopPlay();
    UI.mapT = Math.min(NOW.G.dur, UI.mapT + 4);
    slider.value = UI.mapT;
    redrawMap();
    if (UI.mapT >= NOW.G.dur) stopPlay();
  }, 100);
}

/* ---- wiring ---------------------------------------------------------------------- */
const VIEWS = { game: tabGame, players: tabPlayers, champions: tabChampions, roles: tabRoles, time: tabTime, duos: tabDuos, flow: tabFlow };
function render() {
  const tab = VIEWS[S.tab] ? S.tab : 'game';
  document.getElementById('tabs').innerHTML = TABS.map(t =>
    `<button type="button" role="tab" aria-selected="${t[0] === tab}" class="tab-btn${t[0] === tab ? ' on' : ''}" ${set({ tab: t[0] })}>${t[1]}</button>`).join('');
  let html;
  try { html = VIEWS[tab](); } catch (e) { console.error(e); html = empty('This view could not be drawn: ' + esc(e.message)); }
  document.getElementById('view').innerHTML = html;
  /* Seven tabs do not fit across a phone, so the strip scrolls. Without this
     the page could open on a tab whose own button was off the edge of it. */
  const on = document.querySelector('.tab-btn.on'), strip = document.getElementById('tabs');
  if (on && strip.scrollWidth > strip.clientWidth) strip.scrollLeft = on.offsetLeft - (strip.clientWidth - on.offsetWidth) / 2;
  if (tab === 'game') fillGame();
}
document.addEventListener('click', e => {
  if (e.target.closest('[data-play]')) return togglePlay();
  const step = e.target.closest('[data-step]');
  if (step && NOW) {
    stopPlay();
    UI.mapT = Math.max(0, Math.min(NOW.G.dur, UI.mapT + Number(step.dataset.step)));
    document.getElementById('map-t').value = UI.mapT;
    redrawMap();
    return;
  }
  const a = e.target.closest('[data-set]');
  if (a) { stopPlay(); setState(JSON.parse(a.dataset.set)); if (a.dataset.set.includes('"tab"')) window.scrollTo({ top: 0 }); return; }
  const u = e.target.closest('[data-ui]');
  if (u) {
    const playing = !!PLAY.timer;
    Object.assign(UI, JSON.parse(u.dataset.ui));
    if (playing && S.tab === 'game' && document.getElementById('gmap')) {
      /* Switching between kills and positions mid-playback should not stop it. */
      document.querySelectorAll('[data-ui]').forEach(b => { const v = JSON.parse(b.dataset.ui); if ('mapMode' in v) b.classList.toggle('on', v.mapMode === UI.mapMode); });
      return redrawMap();
    }
    if (S.tab === 'game' && NOW && document.getElementById('game-body')) document.getElementById('game-body').innerHTML = gameBody(NOW.G, NOW.entry);
    else render();
  }
});
document.addEventListener('input', e => { if (e.target.id === 'map-t') { stopPlay(); UI.mapT = Number(e.target.value); redrawMap(); } });
/* A new face was chosen: everything that shows it is redrawn. */
document.addEventListener('avatars:changed', () => render());
document.addEventListener('change', e => {
  if (!e.target.matches('[data-champ-search]')) return;
  const want = e.target.value.trim().toLowerCase();
  const hit = D.champions.list.find(c => C(c.champ).n.toLowerCase() === want) || D.champions.list.find(c => C(c.champ).n.toLowerCase().startsWith(want));
  if (hit && want) setState({ champ: hit.champ, crole: '' });
});
(function stamp() {
  const el = document.querySelector('[data-generated-ms]');
  if (!el) return;
  const ms = Number(el.dataset.generatedMs), mins = Math.max(0, Math.round((Date.now() - ms) / 60000));
  const ago = mins < 60 ? mins + 'm ago' : mins < 2880 ? Math.round(mins / 60) + 'h ago' : Math.round(mins / 1440) + 'd ago';
  el.innerHTML = `updated <b>${new Date(ms).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })}</b> · ${ago}`;
})();
render();
