/* ---- Game breakdown ------------------------------------------------------------
   The list of games is in the page; each game's detail is not. A season of
   timelines is tens of megabytes, so they are published as one small file per
   day and fetched when a game is opened.

   A row of D.games:
     [id, start, seconds, queue, team, won, friends, lobby rank, flag, scaling gap]
   where a friend is [label, champion, role, k, d, a, gold@15, game score, rank],
   flag is 1 for a comeback and 2 for a throw, and the gap is how far the
   team's champions out-scale the enemy's (see _fit_model). */
const GAMES = D.games;
const dayDocs = {}, dayWait = {};
const dayOf = t0 => new Date(t0).toISOString().slice(0, 10);
function loadDay(day) {
  if (!dayWait[day]) {
    dayWait[day] = fetch('g/' + day + '.json').then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(doc => {
      Object.keys(doc).forEach(id => doc[id].p.forEach(p => { if (p.f && OWNER[p.f]) p.f = OWNER[p.f]; }));
      dayDocs[day] = doc;
      return doc;
    });
  }
  return dayWait[day];
}
const isFriend = p => p.f && FR.includes(p.f);
const MON = { 'DRAGON:FIRE_DRAGON': 'Infernal Drake', 'DRAGON:WATER_DRAGON': 'Ocean Drake', 'DRAGON:EARTH_DRAGON': 'Mountain Drake',
  'DRAGON:AIR_DRAGON': 'Cloud Drake', 'DRAGON:HEXTECH_DRAGON': 'Hextech Drake', 'DRAGON:CHEMTECH_DRAGON': 'Chemtech Drake',
  'DRAGON:ELDER_DRAGON': 'Elder Dragon', RIFTHERALD: 'Rift Herald', BARON_NASHOR: 'Baron Nashor', HORDE: 'Voidgrubs', ATAKHAN: 'Atakhan' };
const monLetter = c => c.startsWith('DRAGON') ? (c.includes('ELDER') ? 'E' : 'D') : ({ RIFTHERALD: 'H', BARON_NASHOR: 'B', HORDE: 'G', ATAKHAN: 'A' }[c] || '?');
const TOWER = { TO: 'Outer tower', TI: 'Inner tower', TB: 'Inhibitor tower', TN: 'Nexus tower', I: 'Inhibitor' };
const LANE = { TOP: 'top', MID: 'mid', BOT: 'bot' };
/* The model's two tables, nearest minute. With a scaling gap the chance is
   gold and scaling together; without one it is gold alone. */
function nearest(table, m) {
  const keys = Object.keys(table).map(Number);
  if (!keys.length) return null;
  return table[table[m] != null ? m : keys.reduce((a, b) => Math.abs(b - m) < Math.abs(a - m) ? b : a)];
}
function chanceAt(lead, m, gap) {
  const two = gap == null ? null : nearest(D.flow.slopes2, m);
  if (two) return sig(two[0] * lead / 1000 + two[1] * gap);
  const b = nearest(D.flow.slopes, m);
  return b == null ? null : sig(b * lead / 1000);
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
      `<div class="meta"><span>${DS.format(new Date(g[1]))}</span><span>${f[7] == null ? '' : 'score ' + scoreNum(f[7], false)}</span></div></button>`;
  });
  return `<div class="pillrow">${friendPills('gwho', me, names, true)}<span class="muted small">${list.length} stored games · newest first</span></div>` +
    `<div class="strip">${strip}</div><div id="game-body" data-id="${esc(cur[0])}" data-team="${cur[4]}"><div class="card"><div class="empty">Loading this game…</div></div></div>`;
}
let NOW = null;   /* {G, entry, kf} for the game on screen, so the map can redraw without a fetch */
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
/* The rank a player's game is scored at: their own reading, or failing that
   the friend's rank in the game, or failing that the lobby's. */
function tierFor(p, entry) {
  if (p.rk) return p.rk;
  const f = entry[6].find(x => x[0] === p.f);
  return (f && f[8]) || (entry[7] && entry[7][0] != null ? entry[7] : null) || (entry[6][0] && entry[6][0][8]) || null;
}
function scoreOf(p, entry) {
  if (!p.m || !SC.role[p.r]) return null;
  const rank = tierFor(p, entry);
  return Object.assign(gameScore(p.c, p.r, rank ? rank[0] : null, p.m), { rank, tier: rank ? rank[0] : null });
}

function gameBody(G, entry) {
  const team = entry[4], P = G.p, frames = P[0].g.length, lastWhole = frames - 2, win = G.win === team, gap = entry[9];
  const mine = P.map((p, i) => Object.assign({ pid: i + 1 }, p)).filter(p => p.t === team).sort((a, b) => ROLES.indexOf(a.r) - ROLES.indexOf(b.r));
  const theirs = P.map((p, i) => Object.assign({ pid: i + 1 }, p)).filter(p => p.t !== team).sort((a, b) => ROLES.indexOf(a.r) - ROLES.indexOf(b.r));
  const lead = []; for (let m = 0; m < frames; m++) lead.push(mine.reduce((s, p) => s + p.g[m], 0) - theirs.reduce((s, p) => s + p.g[m], 0));
  const chance = lead.map((v, m) => chanceAt(v, Math.min(m, lastWhole), gap));
  const friends = mine.filter(isFriend);
  const label = pid => { const p = P[pid - 1]; return p ? (isFriend(p) ? fn(p.f) : esc(C(p.c).n)) : '-'; };

  /* header */
  let lo = { v: 1, m: 0 }, hi = { v: 0, m: 0 };
  chance.forEach((c, m) => { if (c == null || m < 3 || m > lastWhole) return; if (c < lo.v) lo = { v: c, m }; if (c > hi.v) hi = { v: c, m }; });
  const minLead = Math.min(...lead), maxLead = Math.max(...lead), at = v => lead.indexOf(v);
  const c15 = lastWhole >= 15 ? chance[15] : null;
  let vt, vs;
  if (entry[8] === 1) { vt = 'Comeback'; vs = `Won from ${Math.round(lo.v * 100)}% · counts at 5k+ behind`; }
  else if (entry[8] === 2) { vt = 'Throw'; vs = `Lost from ${Math.round(hi.v * 100)}% · counts at 5k+ ahead`; }
  else if (win) { vt = minLead > -1500 ? 'Wire to wire' : 'Steady win'; vs = `Never below ${Math.round(lo.v * 100)}% win chance`; }
  else { vt = maxLead < 1500 ? 'Never ahead' : 'Slipped away'; vs = `Peaked at ${Math.round(hi.v * 100)}% win chance`; }
  const stackName = ['', 'Solo', 'Duo', 'Trio', 'Four', 'Five'][Math.min(5, friends.length)] || '';
  let out = `<section class="card" style="margin-bottom:20px"><div class="ghead"><div><div class="result ${win ? 'w' : 'l'}">${win ? 'VICTORY' : 'DEFEAT'}</div>` +
    `<div class="muted" style="margin-top:6px">${esc(QUEUE[G.q] || 'Ranked')} · ${mmss(G.dur)} · ${when(G.t0)}${G.patch ? ' · Patch ' + esc(G.patch) : ''}</div></div>` +
    `<div class="pills">${friends.map(p => `<span class="pill still">${av(p.f)}${esc(p.f)}</span>`).join('')}${stackName ? `<span class="pill still">${stackName}</span>` : ''}${rankChip(entry[7], 'Lobby: ')}</div>` +
    `<div class="tiles">${tile('Win chance at 15 min', c15 == null ? '-' : Math.round(c15 * 100) + '%', c15 == null ? 'game ended before 15' : gold(lead[15]) + ' gold', 'inner')}` +
    (win || -minLead > maxLead ? tile(`Biggest deficit (${at(minLead)}:00)`, `<span class="${minLead < 0 ? 'neg' : ''}">${gold(minLead)}</span>`, '', 'inner')
      : tile(`Biggest lead (${at(maxLead)}:00)`, `<span class="pos">${gold(maxLead)}</span>`, '', 'inner')) +
    tile('', `<span style="color:${vt === 'Comeback' ? 'var(--warn)' : vt === 'Throw' ? 'var(--critical)' : 'inherit'}">${vt}</span>`, vs, 'inner') + '</div></div></section>';

  /* scoreboard, with every player's game score */
  const k = v => v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v;
  const scores = {};
  P.forEach((p, i) => { scores[i + 1] = scoreOf(p, entry); });
  const sc = p => { const s = scores[p.pid]; return !s || s.score == null ? '<span class="muted">-</span>' : scoreNum(s.score); };
  const board = (rows, blue, mineSide) => `<div><div class="side-title ${blue ? 'blue' : 'red'}"><span>${blue ? 'Blue side' : 'Red side'}${mineSide ? ' · your team' : ''}</span></div>` +
    tableWrap('<thead><tr><th>Player</th><th>Champion</th><th>Rank</th><th class="num">Score</th><th class="num">K/D/A</th><th class="num">CS</th><th class="num">Gold</th><th class="num">Dmg</th><th class="num">Vis</th></tr></thead><tbody>' +
    rows.map(p => `<tr class="${isFriend(p) ? 'me' : ''}"><td><span class="cell-champ">${ricon(p.r)}${isFriend(p) ? who(p.f) : '<span class="muted">' + esc(p.n) + '</span>'}</span></td><td>${champ(p.c)}</td>` +
      `<td class="small">${p.rk ? `<span style="color:${TCOL[p.rk[0]]}">${TSHORT[p.rk[0]]}${p.rk[0] >= 7 ? '' : ' ' + DIV[p.rk[1]]}</span>` : '<span class="muted">-</span>'}</td>` +
      `<td class="num">${sc(p)}</td><td class="num strong">${p.k}/${p.d}/${p.a}</td>` +
      `<td class="num">${p.cs}</td><td class="num">${k(p.gold)}</td><td class="num">${k(p.dmg)}</td><td class="num">${p.vis}</td></tr>`).join('') + '</tbody>') + '</div>';
  out += `<section class="card" style="margin-bottom:20px"><div class="grid g2" style="margin:0">${board(mine, team === 100, true)}${board(theirs, team !== 100, false)}</div>` +
    `<p class="muted small" style="margin:12px 0 0">Score is the game score, 0 to 100: each player against others in their role at their rank. ` +
    `${P.some(p => p.rk) ? '' : 'Ranks for this game have not been read yet, so everyone is scored at the lobby\'s rank. '}Scores move as more games are stored.</p></section>`;

  /* gold lead, lane differences, win chance */
  const objs = G.obj.map(o => [o[0], monLetter(o[1]), o[2] === team ? 1 : 0, o[5], o[1]]);
  const towers = (G.bld || []).map(b => [b[0], b[1] !== team ? 1 : 0, b[2] === 'I' ? 1 : 0]);
  const kinds = [...new Set(G.obj.map(o => o[1]))];
  const stolen = G.obj.filter(o => o[5]).map(o => `${esc(MON[o[1]] || o[1])} stolen by ${label(o[3])} at ${mmss(o[0])}`);
  const goldCard = card('Team gold lead', "Above the line is your team ahead. Each objective has its own icon, ringed blue for yours and red for theirs; a dashed gold ring is a steal. The ticks on the middle line are towers.",
    leadChart(lead, G.dur, { objs, towers, h: 400, mark: lastWhole >= 15 ? 15 : null }) +
    `<div class="legend">${kinds.map(c => `<span class="cell-champ">${monBadge(c, monLetter(c), true, 20)}${esc((MON[c] || c).replace(' Drake', '').replace(' Nashor', ''))}</span>`).join('')}` +
    (towers.length ? '<span><i class="sw" style="background:#4c8dff;width:3px;height:12px"></i>tower taken</span><span><i class="sw" style="background:#ef5350;width:3px;height:12px"></i>tower lost</span>' : '') +
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
  const took = side => { const l = G.obj.filter(o => (o[2] === team) === side); return l.length ? l.map(o => monBadge(o[1], monLetter(o[1]), side, 24)).join('') : '<span class="muted small">none</span>'; };
  /* the two junglers' first clears, where the game has them */
  const CAMP = { blue: 'Blue buff', gromp: 'Gromp', wolves: 'Wolves', raptors: 'Raptors', red: 'Red buff', krugs: 'Krugs', invade: 'the enemy jungle', elsewhere: 'away from any camp' };
  const CLEAR = { full: 'full clear', gank: 'ganked before level 4', invade: 'invaded' };
  const jgLine = p => !p || !p.jg ? '' : `<div class="kv"><span class="cell-champ">${cicon(p.c, 20)}${isFriend(p) ? fn(p.f) : esc(C(p.c).n)}</span>` +
    `<span>started at ${CAMP[p.jg[0]] || '-'}${p.jg[1] ? ' · ' + CLEAR[p.jg[1]] : ''}${p.jg[2] != null ? ' · level 4 at <b>' + mmss(p.jg[2]) + '</b>' : ''}` +
    `${p.jg[3] != null ? ' · first scuttles <b>' + Math.min(2, p.jg[3]) + ' of 2</b>' : ''}</span></div>`;
  const jungle = jgLine(mine.find(p => p.r === 'JUNGLE')) + jgLine(theirs.find(p => p.r === 'JUNGLE'));
  const cpts = chance.map((c, m) => [m === frames - 1 ? G.dur / 60 : m, c == null ? null : c * 100]);
  const ext = win ? lo : hi;
  const wc = lineChart([{ pts: cpts, color: '#b08cff', width: 2 }], { x0: 0, x1: G.dur / 60, y0: 0, y1: 100, h: 190, w: 520, l: 40,
    xt: [0, 10, 20, 30, 40].filter(t => t <= G.dur / 60), yt: [0, 50, 100], yf: v => v + '%', vline: ext.m, label: 'Win chance through the game' });
  const laneCard = card('Lane differences', 'Your laner minus their laner.',
    tableWrap(`<thead><tr><th>Lane</th><th>Matchup</th><th class="num">Gold@10</th><th class="num">Gold@15</th><th class="num">XP@15</th><th class="num">CS@15</th></tr></thead><tbody>${lanes}</tbody>`) +
    `<h3>Objectives taken</h3><div class="grid g2" style="margin:0;gap:12px"><div class="took"><b style="color:var(--blue-side)">Your team</b><div>${took(true)}</div></div>` +
    `<div class="took"><b style="color:var(--red-side)">Enemy</b><div>${took(false)}</div></div></div>` +
    (jungle ? `<h3>First clears</h3>${jungle}` : '') +
    `<h3>Win chance through the game</h3>${wc}<p class="muted small">${win ? 'Lowest' : 'Highest'} point: ${Math.round(ext.v * 100)}% at ${ext.m}:00, ` +
    `counting gold and how the two teams' champions scale.</p>`);
  out += `<div class="grid g-3-2">${goldCard}${laneCard}</div>`;

  /* objective log, map, this game against the rank */
  const events = G.obj.map(o => ({ t: o[0], html: `${monBadge(o[1], monLetter(o[1]), o[2] === team)}<div><b>${esc(MON[o[1]] || o[1])}${o[4] > 1 ? ' ×' + o[4] : ''}</b>` +
    `${o[5] ? ' <span class="tag stolen">STOLEN</span>' : ''}<div class="muted small">killer ${label(o[3])} · assists ${o[6].length ? o[6].map(label).join(', ') : 'none'}</div></div>` }));
  if (UI.logTowers) (G.bld || []).forEach(b => events.push({ t: b[0], html: `${monBadge(b[2] === 'I' ? 'INHIB' : 'TOWER', b[2] === 'I' ? 'I' : 'T', b[1] !== team)}` +
    `<div><b>${TOWER[b[2]] || 'Tower'}</b> <span class="muted small">${LANE[b[3]] || ''}${b[1] !== team ? '' : ' · lost'}</span></div>` }));
  events.sort((a, b) => a.t - b.t);
  const log = events.length ? `<div class="oblog">${events.map(e => `<div class="row"><span class="muted">${mmss(e.t)}</span>${e.html}</div>`).join('')}</div>` : '<div class="empty">No epic monsters were taken.</div>';
  const logCard = card('Objective log', 'Who killed it and who helped.', log,
    (G.bld || []).length ? `<span class="pills" style="margin-left:auto">${check('Towers', !!UI.logTowers, { logTowers: !UI.logTowers })}</span>` : '');
  const fx = friends.filter(p => p.m && SC.role[p.r]);
  const focus = fx.find(q => q.f === UI.focus) || fx[0];
  NOW.focusPid = focus ? focus.pid : null;
  const pick = fx.length > 1 ? `<div class="pills" style="margin-bottom:8px"><span class="pill-label">Whose</span>${fx.map(q => pill(av(q.f) + esc(q.f), q === focus, ui({ focus: q.f }), ' sm')).join('')}</div>` : '';
  const mapCard = `<section class="card"><h2>Map</h2><div class="pills" style="margin:12px 0 8px" id="map-layers">${layerPills('ml', UI.ml)}</div>` +
    `<div class="mapwrap" id="gmap">${gameMap()}</div><div class="scrub">` +
    `<button type="button" id="map-play" data-play aria-label="Play the game back">${PLAY.timer ? '❚❚' : '▶'}</button>` +
    `<button type="button" data-step="-60" aria-label="Back one minute">◀</button>` +
    `<input type="range" id="map-t" min="0" max="${G.dur}" step="5" value="${UI.mapT}" aria-label="Time in the game">` +
    `<button type="button" data-step="60" aria-label="Forward one minute">▶</button>` +
    `<b id="map-t-label" class="num" style="min-width:52px">${mapLabel()}</b></div>` +
    `<div class="legend" id="gmap-legend">${mapLegend()}</div><p class="muted small">Riot records where everyone stands once a minute and exactly where each death happens. ` +
    `Between those points movement is drawn as a straight line, so a recall looks like a walk home.</p></section>`;
  let radCard = card('This game vs rank averages', '', '<div class="empty">No tracked player with a role in this game.</div>'), scoreCard = '';
  if (focus) {
    const p = focus, axes = SC.role[p.r], s = scores[p.pid], rl = RN[p.r].toLowerCase(), rls = RLS[p.r], tk = baseKey(p.r, s.tier), tname = tk === 'all' ? 'All' : TIERS[s.tier];
    const usual = ((D.usual[p.f] || {})[p.c + '|' + p.r]) || [0, null];
    const tierAvg = tk === 'all' ? null : axes.map(a => pctOf(p.r, null, a, ((SC.avg[p.r] || {})[tk] || {})[a]));
    radCard = card(`${esc(p.f)}'s game vs rank averages`, `${esc(RN[p.r])} · ${esc(C(p.c).n)}. Percentile among all ${rls} in the stored games.`,
      pick + radar(axes.map(statName), [tierAvg ? { vals: tierAvg, color: TCOL[s.tier], width: 1.8 } : null, usual[1] ? { vals: usual[1], color: '#94a3b8', width: 1.8 } : null,
        { vals: axes.map(a => pctOf(p.r, null, a, p.m[a])), color: col(p.f), fill: true, width: 2.4 }], { label: 'This game against the rank' }) +
      `<div class="legend"><span><i class="sw" style="background:${col(p.f)}"></i>This game</span><span><i class="sw" style="background:#94a3b8"></i>${esc(p.f)}'s ${esc(C(p.c).n)} (${usual[0]})</span>` +
      (tierAvg ? `<span><i class="sw" style="background:${TCOL[s.tier]}"></i>${TIERS[s.tier]} ${rls}</span>` : '') + '</div>');
    scoreCard = gameScoreCard(p, s, entry, tname, win, G);
  }
  out += `<div class="grid g3">${logCard}${mapCard}${radCard}</div>${scoreCard}`;
  return out;
}

/* One game's score, metric by metric: the bottom half of the scoring page. */
function gameScoreCard(p, s, entry, tname, win, G) {
  if (!s || s.score == null) return '';
  const rl = RN[p.r].toLowerCase(), rls = RLS[p.r], tk = baseKey(p.r, s.tier), avg = (SC.avg[p.r] || {})[tk] || {}, LN = { role: 'Role', class: 'Class', tag: 'Tag' };
  const w = rankWeight(s.rank), fromIndex = (entry[6].find(f => f[0] === p.f) || [])[7];
  const shown = fromIndex != null ? fromIndex : s.score;
  const rows = s.lines.map(l => `<tr><td><span class="tag ly ly-${l.layer}">${LN[l.layer]}</span></td><td>${esc(l.tag ? l.tag + ': ' : '')}${esc(STAT[l.m].label)}${STAT[l.m].up ? '' : ' (fewer)'}` +
    `${l.w !== 1 ? ` <span class="muted small">×${l.w} weight</span>` : ''}</td><td class="num strong">${stat(l.m, l.v)}</td><td class="num muted">${stat(l.m, avg[l.m])}</td><td>${pcbar(l.p)}</td></tr>`).join('');
  const foot = Object.keys(s.layers).map(l => `<span><span class="tag ly ly-${l}">${LN[l]}</span> average ${s.layers[l].toFixed(0)} × ${Math.round(SC.layer[l] * 100)}%</span>`).join('') +
    (Object.keys(s.layers).length < 3 ? '<span class="muted">an empty layer gives its share to the others</span>' : '') + `<span>= <b>${s.score.toFixed(1)}</b></span>`;
  return `<section class="card" style="margin-bottom:20px"><div class="gscore-head"><div><h2>Game score: this game</h2>` +
    `<p class="hint">${esc(p.f)} · ${esc(C(p.c).n)} ${rl} · ${win ? 'Win' : 'Loss'} · ${mmss(G.dur)}${s.rank ? ' · played at ' + esc(rankName(s.rank)) : ''}. ` +
    `Each metric is a percentile against ${tk === 'all' ? 'all ' + rls + ' (too few at this rank for its own baseline yet)' : rls + ' at ' + TIERS[s.tier]}.</p></div>` +
    `<div class="tiles" style="margin:0;grid-template-columns:repeat(2,minmax(130px,1fr))">${tile('Game score', shown.toFixed(0), '', 'inner')}` +
    `${tile('After rank weight', w == null ? '-' : `<span style="color:var(--violet-2)">${Math.min(100, shown * w).toFixed(0)}</span>`, w == null ? '' : `× ${w.toFixed(2)} for ${esc(rankName(s.rank))}`, 'inner')}</div></div>` +
    tableWrap(`<thead><tr><th>Layer</th><th>Metric</th><th class="num">${esc(p.f)}</th><th class="num">${esc(tname)} ${rls} avg</th><th style="min-width:200px">Percentile</th></tr></thead><tbody>${rows}</tbody>`) +
    `<div class="legend" style="margin-top:14px">${foot}</div></section>`;
}

const mapLabel = () => mmss(Math.min(UI.mapT, NOW.G.dur));
function mapLegend() {
  const L = UI.ml, p = NOW.focusPid ? NOW.G.p[NOW.focusPid - 1] : null, whose = p ? esc(p.f) + "'s " : '';
  const parts = [L.pos ? `<span><i class="sw round" style="background:#4c8dff"></i>your team</span><span><i class="sw round" style="background:#ef5350"></i>enemy</span><span class="muted">faded = dead</span>` : '',
    L.kp ? `<span><i class="sw round" style="background:${KPCOL}"></i>${whose}kills and assists</span>` : '',
    L.k ? `<span><i class="sw round" style="background:${KCOL}"></i>${whose}kills</span>` : '',
    L.a ? `<span><i class="sw round" style="background:${ACOL}"></i>${whose}assists</span>` : '',
    L.d ? `<span><span style="color:${DCOL};font-weight:800">✕</span> ${whose}deaths</span>` : ''].join('');
  return (parts || '<span class="muted">every layer is off</span>') + `<span class="muted">at ${mapLabel()}${L.kp || L.k || L.a || L.d ? ' · the last 30 seconds ringed' : ''}</span>`;
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
  const G = NOW.G, team = NOW.entry[4], t = Math.min(UI.mapT, G.dur), L = UI.ml, me = NOW.focusPid;
  let s = '';
  /* Kills, assists and deaths belong to the picked player; with nobody picked
     (no tracked player has a role) they are the team's. */
  const mark = (e, kind) => {
    const fresh = t - e[0] <= 30 && t < G.dur, colr = kind === 'd' ? DCOL : kind === 'k' ? KCOL : kind === 'a' ? ACOL : KPCOL;
    if (fresh) s += `<circle cx="${e[1]}" cy="${my(e[2])}" r="7" fill="none" stroke="${colr}" stroke-width="1.2" opacity=".9"/>`;
    s += kind === 'd' ? cross(e[1], my(e[2]), colr) : `<circle cx="${e[1]}" cy="${my(e[2])}" r="${fresh ? 3.6 : 2.8}" fill="${colr}" stroke="#0b0e14" stroke-width=".7"/>`;
  };
  if (L.kp || L.k || L.a || L.d) {
    G.kills.forEach(e => {
      if (e[0] > t) return;
      const onTeam = pid => pid >= 1 && pid <= 10 && G.p[pid - 1].t === team;
      const killed = me ? e[3] === me : onTeam(e[3]), helped = me ? e.slice(5).includes(me) : false, died = me ? e[4] === me : onTeam(e[4]);
      if (L.kp && (killed || helped)) mark(e, 'kp');
      if (L.a && helped) mark(e, 'a');
      if (L.k && killed) mark(e, 'k');
      if (L.d && died) mark(e, 'd');
    });
  }
  if (L.pos) {
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
    /* An objective taken in the last twenty seconds is marked where it lives. */
    G.obj.forEach(o => { if (o[0] <= t && t - o[0] <= 20) { const pit = o[1] === 'BARON_NASHOR' || o[1] === 'RIFTHERALD' || o[1] === 'HORDE' ? [78, 162] : o[1] === 'ATAKHAN' ? null : [154, 69];
      if (pit) s += `<circle cx="${pit[0]}" cy="${my(pit[1])}" r="12" fill="none" stroke="${o[2] === team ? '#4c8dff' : '#ef5350'}" stroke-width="2" stroke-dasharray="4 3"/>`; } });
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
  if (b) b.textContent = '▶';
}
function togglePlay() {
  if (PLAY.timer) return stopPlay();
  if (!NOW) return;
  if (UI.mapT >= NOW.G.dur) UI.mapT = 0;
  document.getElementById('map-play').textContent = '❚❚';
  PLAY.timer = setInterval(() => {
    const slider = document.getElementById('map-t');
    if (!NOW || !slider) return stopPlay();
    UI.mapT = Math.min(NOW.G.dur, UI.mapT + 4);
    slider.value = UI.mapT;
    redrawMap();
    if (UI.mapT >= NOW.G.dur) stopPlay();
  }, 100);
}
