/* ---- Players ------------------------------------------------------------------ */
const ZONE = { top: ['Top lane', '#e6b450'], mid: ['Mid', '#b08cff'], bot: ['Bot lane', '#4c8dff'], river: ['River', '#1fa5b3'], jungle: ['Jungle', '#2f9a5d'] };
const ZPART = { river_top: 'Top river', river_bot: 'Bot river', jungle_own: 'Own jungle', jungle_enemy: 'Enemy jungle' };
const ROLE_COL = { TOP: '#e6b450', JUNGLE: '#2f9a5d', MIDDLE: '#b08cff', BOTTOM: '#4c8dff', UTILITY: '#2ec4b6' };
const MODE_COL = { 'Ranked Solo/Duo': '#4c8dff', 'Ranked Flex': '#d6569c', 'Ranked 5s': '#e6b450' };
const refName = (tier, role) => (tier == null ? 'All ' : TIERS[tier] + ' ') + RLS[role];

/* The roaming bar: one block a lane, one for the river and one for the
   jungle, biggest first. Pointing at (or tapping) a block opens a small panel
   over the page with the split and the comparison, so nothing moves. */
function zoneBar(bar, refLabel, key = 'v') {
  return `<div class="zonebar">${bar.filter(b => b[key] > 0).map(b => {
    const z = ZONE[b.z], v = b[key];
    const rows = (b.parts || []).map(p => `<div><span><i class="sw" style="background:${z[1]}"></i>${ZPART[p[0]]}</span><b>${Math.round(key === 'v' ? p[1] : p[2])}%</b></div>`).join('');
    const foot = key === 'v' ? `<div class="ref"><span>${esc(refLabel)}</span><span>${Math.round(b.ref)}%</span></div>` : '';
    return `<span class="zb-seg" tabindex="0" style="flex:${v};background:${z[1]}"><span class="zb-txt">${v >= 15 ? z[0].replace(' lane', '') + ' ' : ''}${v >= 6 ? Math.round(v) + '%' : ''}</span>` +
      `<span class="zb-pop"><b>${z[0]} · ${Math.round(v)}%</b>${rows}${foot}</span></span>`;
  }).join('')}</div>`;
}
const zoneLegend = bar => `<div class="legend">${bar.map(b => `<span><i class="sw" style="background:${ZONE[b.z][1]}"></i>${ZONE[b.z][0]}${b.parts ? ' <span class="muted">(point for the split)</span>' : ''}</span>`).join('')}</div>`;

function heatLayer(h, phase) {
  const size = h.size, cell = MAPQ / size, grid = new Float64Array(size * size);
  const phases = phase === 'all' ? [0, 1, 2] : [Number(phase)];
  phases.forEach(p => { for (let i = 0; i < grid.length; i++) grid[i] += parseInt(h.g[p][i], 36) / 35 * h.gm[p]; });
  let top = 0;
  grid.forEach(v => { if (v > top) top = v; });
  let s = '<g filter="url(#hblur)">';
  for (let i = 0; i < grid.length; i++) {
    const v = top ? grid[i] / top : 0;
    if (v < 0.04) continue;
    const cx = i % size, cy = Math.floor(i / size);
    s += `<rect x="${(cx * cell).toFixed(1)}" y="${my((cy + 1) * cell).toFixed(1)}" width="${cell.toFixed(1)}" height="${cell.toFixed(1)}" fill="#ff8a3d" fill-opacity="${Math.min(0.9, Math.sqrt(v) * 0.9).toFixed(2)}"/>`;
  }
  return '<defs><filter id="hblur" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="5"/></filter></defs>' + s + '</g>';
}
/* What a set of switched-on layers draws, and the legend that goes with it. */
function layerDraw(L, get, heatHtml) {
  let s = L.pos ? heatHtml : '';
  if (L.kp) s += dots(get('a').concat(get('k')), KPCOL, 2.4);
  if (L.a) s += dots(get('a'), ACOL, 2.4);
  if (L.k) s += dots(get('k'), KCOL, 2.4);
  if (L.d) s += crosses(get('d'), DCOL);
  return s;
}
const layerLegend = (L, posText) => [L.pos ? `<span><i class="sw" style="background:#ff8a3d"></i>${posText}</span>` : '',
  L.kp ? `<span><i class="sw round" style="background:${KPCOL}"></i>kills and assists</span>` : '',
  L.k ? `<span><i class="sw round" style="background:${KCOL}"></i>kills</span>` : '',
  L.a ? `<span><i class="sw round" style="background:${ACOL}"></i>assists</span>` : '',
  L.d ? `<span><span style="color:${DCOL};font-weight:800">✕</span> deaths</span>` : ''].join('') ||
  '<span class="muted">every layer is off</span>';

function barRows(rows) {
  /* rows: [label html, winrate, games, colour] */
  return rows.map(r => `<div class="wrrow${r[2] < LOW ? ' thin' : ''}"><span class="l">${r[0]}</span>${wrBar(r[1], r[3])}` +
    `<b>${pc1(r[1])}</b><span class="muted small num">${r[2]}g</span></div>`).join('') || '<div class="empty">Nothing yet.</div>';
}

function tabPlayers() {
  const names = FR.filter(l => D.players[l] && Object.keys(D.players[l].roles).length);
  if (!names.length) return empty('No player has three stored games in one role yet.');
  const me = names.includes(S.player) ? S.player : names[0], PL = D.players[me];
  const roles = Object.keys(PL.roles);
  const role = roles.includes(S.role) ? S.role : roles[0];
  const P = PL.roles[role], rl = RN[role].toLowerCase(), rls = RLS[role], ref = refName(P.refTier, role);

  let out = `<div class="pillrow">${friendPills('player', me, names, false)}<div class="pills"><span class="pill-label">Role</span>` +
    roles.map(r => pill(`${ricon(r)}${RN[r]} · ${PL.roles[r].games}`, r === role, set({ role: r }), ' sm')).join('') + '</div></div>';
  out += `<div class="whohead"><span data-av-edit="${esc(me)}" role="button" tabindex="0" title="Change ${esc(me)}'s icon">${av(me, 56)}<i class="pen">✎</i></span>` +
    `<div><div class="big" style="font-size:24px;font-weight:700;color:${col(me)}">${esc(me)}</div>` +
    `<div class="muted">${P.games} ${rl} games · ${pc1(100 * P.wins / P.games)} winrate · average game score ${P.score == null ? '-' : P.score.toFixed(0)}` +
    `${P.tier != null ? ' · mostly played at ' + tierText(P.tier) : ''}</div></div></div>`;

  /* the four small cards from the original site, plus winrate by lobby rank */
  const total = PL.modes.reduce((s, m) => s + m[1], 0), ptotal = PL.positions.reduce((s, m) => s + m[1], 0) || 1;
  const short = q => q.replace('Ranked ', '');
  const legend = parts => `<div class="dlegend">${parts.map(p => `<div><i class="sw" style="background:${p[2]}"></i>${esc(p[0])} <b>${p[1]}</b></div>`).join('')}</div>`;
  const mparts = PL.modes.map(m => [short(m[0]), m[1], MODE_COL[m[0]] || '#788296']);
  const pparts = PL.positions.map(p => [RN[p[0]], p[1], ROLE_COL[p[0]]]);
  const cards = card('Games by mode', 'This season, all roles.', `<div class="drow">${donut(mparts, total, 'games')}${legend(mparts)}</div>`) +
    card('Roles played', 'Share of games.', pparts.length ? `<div class="drow">${donut(pparts, Math.round(100 * pparts[0][1] / ptotal) + '%', pparts[0][0].toLowerCase())}${legend(pparts)}</div>` : '<div class="empty">No roles recorded.</div>') +
    card('Winrate by mode', 'Every queue this season.', barRows(PL.modes.map(m => [esc(m[0]), 100 * m[2] / m[1], m[1], MODE_COL[m[0]] || '#788296']))) +
    card('Winrate by lobby rank', !D.meta.rankedGames ? 'No lobby ranks have been read yet, so for now this is the rank of the friend who played.'
      : `Average rank of the other nine players${D.meta.rankedGames < D.meta.storedGames ? ', where it has been read' : ''}.`,
      barRows(PL.byRank.map(r => [tierText(r[0]), 100 * r[2] / r[1], r[1], TCOL[r[0]]])));
  out += `<div class="grid g4">${cards}</div>`;

  out += '<div class="tiles six">' + P.tiles.map(t => tile(esc(STAT[t.k].label), stat(t.k, t.v),
    pcbar(t.pc) + `<div class="muted small" style="margin-top:6px">${esc(ref)} avg ${stat(t.k, t.ref)}</div>`)).join('') + '</div>';

  /* radar: the player against the average of their role at each rank */
  const tiers = Object.keys(P.radar.ranks).map(Number), shown = UI.rt || tiers;
  const series = tiers.filter(t => shown.includes(t)).map(t => ({ vals: P.radar.ranks[t], color: TCOL[t], width: 1.8 }));
  series.push({ vals: P.radar.me, color: col(me), fill: true, width: 2.4 });
  const tierPills = tiers.map(t => `<button type="button" class="pill sm${shown.includes(t) ? ' ton' : ''}" style="--tc:${TCOL[t]}" ` +
    `${ui({ rt: shown.includes(t) ? shown.filter(x => x !== t) : shown.concat([t]) })}>${TIERS[t]}</button>`).join('');
  const radCard = card(`${RN[role]} radar by rank`, `Percentile among all ${rls} in the stored games. Each thin line is the average ${rl} at that rank.`,
    (tiers.length ? `<div class="pills">${tierPills}</div>` : '') + radar(P.radar.axes.map(statName), series, { label: `${me} ${rl} radar` }) +
    `<div class="legend"><span><i class="sw" style="background:${col(me)}"></i>${esc(me)}</span>` +
    tiers.filter(t => shown.includes(t)).map(t => `<span><i class="sw" style="background:${TCOL[t]}"></i>${TSHORT[t]}</span>`).join('') + '</div>');

  /* where they play */
  const h = P.heat, ph = UI.hphase, phs = ph === 'all' ? [0, 1, 2] : [Number(ph)];
  const flat = k => phs.reduce((a, p) => a.concat(h[k][p]), []);
  const phases = [['0', 'Laning 0–15'], ['1', 'Mid 15–25'], ['2', 'Late 25+'], ['all', 'All']].map(m => pill(m[1], ph === m[0], ui({ hphase: m[0] }), ' sm')).join('');
  const mapCard = `<section class="card"><h2>Where ${esc(me)} plays</h2><div class="pills" style="margin:12px 0 8px">${layerPills('hl', UI.hl)}</div>` +
    `<div class="pills" style="margin-bottom:12px">${phases}</div><div class="mapwrap">${mapSvg(layerDraw(UI.hl, flat, heatLayer(h, ph)))}</div>` +
    `<div class="legend">${layerLegend(UI.hl, 'time spent')}<span class="muted">each layer switches on its own · shown as blue side</span></div></section>`;

  out += `<div class="grid g3">${radCard}${mapCard}${roamCard(me, role, P.roam, ref)}</div>`;
  if (P.jungle) out += jungleSection(me, P.jungle);

  const cmp = P.compare, head = `<thead><tr><th>Stat</th><th class="num">${esc(me)} · ${esc(RN[role])}</th>` +
    `<th class="num">${esc(me)} · ${esc(C(cmp.champ).n)}</th><th class="num">Group ${rls}</th>` +
    `<th class="num">${esc(ref)}</th><th class="num">All ${rls}</th><th style="min-width:170px">Percentile at their rank</th></tr></thead>`;
  const rows = cmp.rows.map(r => `<tr><td class="strong">${esc(STAT[r.k].label)}</td><td class="num strong">${stat(r.k, r.me)}</td>` +
    `<td class="num">${stat(r.k, r.champ)}</td><td class="num muted">${stat(r.k, r.group)}</td><td class="num muted">${stat(r.k, r.ref)}</td>` +
    `<td class="num muted">${stat(r.k, r.all)}</td><td>${pcbar(r.pc)}</td></tr>`).join('');
  out += card(`${esc(me)} vs comparison groups`,
    `${esc(RN[role])} games only, so these never mix with other roles. ${esc(C(cmp.champ).n)} is ${esc(me)}'s most played here (${cmp.champGames} games).`,
    tableWrap(head + `<tbody>${rows}</tbody>`));
  return out;
}

function roamCard(me, role, R, ref) {
  if (!R) return card('Roaming', 'Laning phase, 0–15 min.', '<div class="empty">Not enough early takedowns stored yet.</div>');
  const bars = `<h3>Where ${esc(me)}'s takedowns happen</h3>${zoneBar(R.bar, ref)}<h3>${esc(ref)}</h3>${zoneBar(R.bar, ref, 'ref')}${zoneLegend(R.bar)}`;
  if (R.jungle) {
    return card('Early pathing', 'Takedowns in the laning phase, 0–15 min, by where they happened.',
      bars + `<div class="grid g2" style="margin:16px 0 0">${tile('Early takedowns a game', R.perGame.toFixed(1), R.refPerGame != null ? `${esc(ref)} ${R.refPerGame.toFixed(1)}` : '', 'inner')}` +
      `${tile('Counted', R.takedowns, 'kills and assists', 'inner')}</div>`);
  }
  const up = (a, b) => a == null || b == null ? '' : `<span class="${a >= b ? 'pos' : 'neg'}">${a >= b ? '▲' : '▼'} ${esc(ref)} ${Math.round(b)}%</span>`;
  let body = bars + `<div class="grid g2" style="margin:16px 0 0">${tile('Roam takedown share', R.roamShare == null ? '-' : Math.round(R.roamShare) + '%', up(R.roamShare, R.refRoam), 'inner')}` +
    `${tile(role === 'UTILITY' ? 'Time out of lane (ADC still bot)' : 'Time out of lane', R.outLane == null ? '-' : Math.round(R.outLane) + '%', up(R.outLane, R.refOut), 'inner')}</div>`;
  if (R.split) {
    const s = R.split, g = v => `<td class="num strong ${gcls(v)}">${gold(v)}</td>`;
    body += `<h3>Does roaming pay off? Gold diff @15 for every lane</h3><div class="scroll"><table class="tbl"><thead><tr><th>Lane</th><th class="num">High-roam (${s.high.games}g)</th><th class="num">Low-roam (${s.low.games}g)</th></tr></thead><tbody>` +
      ROLES.map(r => `<tr><td>${ricon(r)} ${RN[r]}${r === role ? ` <span class="muted">(${esc(me)})</span>` : ''}</td>${g(s.high.lanes[r])}${g(s.low.lanes[r])}</tr>`).join('') +
      `<tr><td class="strong">Winrate</td><td class="num strong ${s.high.wr >= 50 ? 'pos' : ''}">${pc0(s.high.wr)}</td><td class="num strong ${s.low.wr >= 50 ? 'pos' : ''}">${pc0(s.low.wr)}</td></tr></tbody></table></div>`;
    const gain = ROLES.filter(r => r !== role && s.high.lanes[r] != null && s.low.lanes[r] != null).map(r => [s.high.lanes[r] - s.low.lanes[r], r]).sort((a, b) => b[0] - a[0]);
    const own = s.high.lanes[role] != null && s.low.lanes[role] != null ? s.high.lanes[role] - s.low.lanes[role] : null;
    if (gain.length && own != null) {
      body += `<p class="muted small" style="margin-top:12px">In ${esc(me)}'s high-roam games ${RN[gain[0][1]].toLowerCase()} is ${gold(Math.round(gain[0][0]))} better off at 15 ` +
        `and ${esc(me)}'s own lane is ${gold(Math.round(own))}. A pattern, not proof of cause.</p>`;
    }
  }
  return card('Roaming', `Laning phase, 0–15 min. Where ${esc(me)}'s takedowns happen.`, body);
}

/* ---- jungle pathing --------------------------------------------------------------- */
function routeSvg(routes) {
  const cols = ['#f472b6', '#e5e7eb'];
  let s = '<defs>' + cols.map((c, i) => `<marker id="arr${i}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${c}"/></marker>`).join('') + '</defs>';
  routes.slice(0, 2).forEach((rt, i) => {
    const pts = rt.pts.map(q => [q[0], my(q[1])]);
    for (let k = 0; k + 1 < pts.length; k++) {
      const a = pts[k], b = pts[k + 1], dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1, pad = 11;
      if (len < 2 * pad + 2) continue;
      s += `<line x1="${(a[0] + dx / len * pad).toFixed(1)}" y1="${(a[1] + dy / len * pad).toFixed(1)}" x2="${(b[0] - dx / len * pad).toFixed(1)}" y2="${(b[1] - dy / len * pad).toFixed(1)}" ` +
        `stroke="${cols[i]}" stroke-width="${i ? 1.4 : 2}"${i ? ' stroke-dasharray="4 3"' : ''} marker-end="url(#arr${i})"/>`;
    }
    pts.forEach((q, k) => {
      s += `<circle cx="${q[0]}" cy="${q[1]}" r="9.5" fill="${i ? '#10131a' : cols[0]}" stroke="${cols[i]}" stroke-width="1.5"/>` +
        `<text x="${q[0]}" y="${q[1] + 2.6}" text-anchor="middle" style="fill:${i ? '#e5e7eb' : '#10131a'};font-size:6.4px;font-weight:800">${k + 1}:00</text>`;
    });
  });
  return mapSvg(s, 'zones');
}
const routeLegend = routes => `<div class="legend">${routes.slice(0, 2).map((rt, i) =>
  `<span><i class="sw" style="background:${i ? '#e5e7eb' : '#f472b6'}"></i>${i ? '2nd' : 'Most common'}: ${esc(rt.label)} start (${rt.share}%)</span>`).join('')}` +
  '<span><i class="sw" style="background:#1fa5b3"></i>river</span><span><i class="sw" style="background:#2f9a5d"></i>jungle</span></div>';

function jungleSection(me, J) {
  const meter = (share, color) => `<div class="meter"><i style="width:${Math.max(2, Math.min(100, share))}%;background:${color}"></i></div>`;
  const first = card(`First clear · ${esc(me)} · ${esc(C(J.champ).n)}`,
    'Where they usually are at 1:00, 2:00, 3:00 and 4:00. Camps appear at 0:55, so 1:00 shows the camp they start on. Turned so every game reads as blue side.',
    J.routes.length ? `<div class="mapwrap">${routeSvg(J.routes)}</div>${routeLegend(J.routes)}` : '<div class="empty">Needs five games that start at a camp.</div>');
  const starts = card('Starting camp', 'From the 1:00 sample.',
    J.starts.filter(s => s.share >= 2).map(s => `<div class="jrow${s.games < LOW ? ' thin' : ''}"><span class="l">${esc(s.label)}</span>${meter(s.share, s.k === 'red' ? '#f472b6' : s.k === 'blue' ? '#a78bfa' : s.k === 'invade' ? '#e6b450' : '#788296')}` +
      `<b>${Math.round(s.share)}%</b><span class="muted small s">winrate ${pc1(s.wr)} · ${s.games}g</span></div>`).join(''));
  const c = J.clear, t = v => v == null ? '-' : mmss(v);
  const clear = card('Clear type', 'Level 4 marks the end of the first clear.', !c ? '<div class="empty">Level-up times are still being collected for these games.</div>' :
    `<div class="ctype"><div><i class="sw" style="background:#22c55e"></i><b>Full clear</b><span class="r"><b>${Math.round(c.full.share)}%</b> · ${t(c.full.time)}</span></div>` +
    `<p>No takedown and no lane visit before level 4. Average level 4 time; group average ${t(c.full.group)}.</p></div>` +
    `<div class="ctype"><div><i class="sw" style="background:#f97316"></i><b>Gank before clear</b><span class="r"><b>${Math.round(c.gank.share)}%</b> · ${t(c.gank.time)}</span></div>` +
    `<p>${c.gank.games ? `${pc0(c.gank.ok)} lead to a takedown without dying${c.gank.lane ? ', most often ' + (ZONE[c.gank.lane] || [c.gank.lane])[0].toLowerCase() : ''}.` : 'None recorded.'}</p></div>` +
    `<div class="ctype"><div><i class="sw" style="background:#e6b450"></i><b>Invade</b><span class="r"><b>${Math.round(c.invade.share)}%</b></span></div>` +
    `<p>In the enemy jungle at 1:00 or 2:00.</p></div><p class="muted small">${c.n} games with level-up times.</p>`);
  const sc = J.scuttle, srow = (lab, v, color) => `<div class="jrow${v[2] < LOW ? ' thin' : ''}"><span class="l">${lab}</span>${meter(v[0], color)}<b>${Math.round(v[0])}%</b>` +
    `<span class="muted small s">${v[2] ? 'winrate ' + pc1(v[1]) + ' · ' + v[2] + 'g' : 'never'}</span></div>`;
  const scut = card('First scuttles', `How the first two scuttle crabs went, from the game's own count.`, !sc ? '<div class="empty">Scuttle counts are still being collected for these games.</div>' :
    srow('Took both', sc.both, '#22c55e') + srow('One each', sc.one, '#94a3b8') + srow('Took none', sc.none, '#ef4444') +
    `<p class="muted small">${sc.n} games. Which side each crab was on is not recorded.</p>`);
  const tbl = D.jungle.length ? card('Group junglers compared', 'Full clear time only counts games with nothing before level 4.',
    tableWrap('<thead><tr><th>Jungler</th><th>Most played</th><th class="num">Jungle games</th><th class="num">Winrate</th><th class="num">Full clear time</th>' +
      '<th class="num">Gank before clear</th><th class="num">Double scuttle</th><th class="num">No scuttle</th></tr></thead><tbody>' +
      D.jungle.map(j => `<tr><td>${who(j.label)}</td><td>${champ(j.champ)}</td><td class="num">${j.games}${low(j.games)}</td><td class="num">${pc1(j.wr)}</td>` +
        `<td class="num strong">${j.fullGames >= 3 ? mmss(j.fullTime) : '-'}</td><td class="num">${pc0(j.gank)}</td>` +
        `<td class="num pos">${pc0(j.both)}</td><td class="num neg">${pc0(j.none)}</td></tr>`).join('') + '</tbody>')) : '';
  return `<div class="grid g-2-3"><div>${first}</div><div class="stack"><div class="grid g3" style="margin:0">${starts}${clear}${scut}</div>${tbl}</div></div>`;
}

/* ---- Champions ---------------------------------------------------------------- */
function champSuggest(q) {
  const L = D.champions.list, want = q.trim().toLowerCase();
  const hits = !want ? [] : L.filter(c => C(c.champ).n.toLowerCase().includes(want))
    .sort((a, b) => (C(b.champ).n.toLowerCase().startsWith(want) - C(a.champ).n.toLowerCase().startsWith(want)) || b.games - a.games).slice(0, 7);
  if (!want) return '';
  if (!hits.length) return '<div class="sg-pop"><div class="sg-foot">No champion the group has played matches that.</div></div>';
  return `<div class="sg-pop"><div class="sg-head">Champions</div>${hits.map((c, i) => `<button type="button" class="sg-row${i === 0 ? ' on' : ''}" ${set({ tab: 'champions', champ: c.champ, crole: '' })}>` +
    `${cicon(c.champ, 30)}<span><b>${esc(C(c.champ).n)}</b><small>${esc((C(c.champ).cs || []).join(' · '))}</small></span>` +
    `<span class="r"><b>${c.games} games</b><small class="${c.wr >= 52 ? 'pos' : c.wr < 48 ? 'neg' : ''}">${pc1(c.wr)} winrate</small></span></button>`).join('')}` +
    '<div class="sg-foot">↑↓ to move · Enter to open · only champions the group has played</div></div>';
}
const searchBox = big => `<div class="sg${big ? ' big' : ''}"><input class="search" type="search" autocomplete="off" placeholder="Search champion…" aria-label="Search champion" data-champ-search value="${esc(UI.q)}">` +
  `<div class="sg-host">${champSuggest(UI.q)}</div></div>`;

function champGrid() {
  const L = D.champions.list, rf = ROLES.includes(S.crf) ? S.crf : 'All', sort = S.csort === 'wr' ? 'wr' : 'games';
  /* The wiki's tags as a filter, commonest first, so "everything with crowd control" is one click. */
  const tagCount = {};
  L.forEach(c => (C(c.champ).tg || []).forEach(t => { tagCount[t] = (tagCount[t] || 0) + 1; }));
  const tags = Object.keys(tagCount).sort((a, b) => tagCount[b] - tagCount[a]), tg = tags.includes(S.ctag) ? S.ctag : '';
  const pick = L.filter(c => (rf === 'All' || c.roles.some(r => r[0] === rf)) && (!tg || (C(c.champ).tg || []).includes(tg)))
    .map(c => rf === 'All' ? c : Object.assign({}, c, { games: c.roles.find(r => r[0] === rf)[1] }));
  let out = `<section class="card" style="margin-bottom:20px"><div class="champ-head">${searchBox(true)}` +
    `<div class="pills"><span class="pill-label">Role</span>${pill('All', rf === 'All', set({ crf: '' }), ' sm')}${ROLES.map(r => pill(ricon(r) + RN[r], rf === r, set({ crf: r }), ' sm')).join('')}` +
    `<span class="pill-label" style="margin-left:10px">Sort</span>${pill('Games', sort === 'games', set({ csort: '' }), ' sm')}${pill('Winrate', sort === 'wr', set({ csort: 'wr' }), ' sm')}</div></div>` +
    `<div class="filters" style="margin-top:14px"><span class="pill-label">Tag</span>${pill('Any', !tg, set({ ctag: '' }), ' sm')}` +
    `${tags.map(t => pill(esc(t), tg === t, set({ ctag: t }), ' sm')).join('')}</div></section>`;
  if (!pick.length) out += empty('No champion the group has played matches that role and tag.');
  D.meta.families.forEach(([family, members]) => {
    const mine = pick.filter(c => members.includes(C(c.champ).c)).sort((a, b) => sort === 'wr' ? (b.games >= LOW) - (a.games >= LOW) || b.wr - a.wr : b.games - a.games);
    if (!mine.length) return;
    const open = UI.cexp[family], shown = open ? mine : mine.slice(0, 12);
    out += `<div class="fam"><h2>${esc(family)}</h2><span class="muted">${mine.reduce((s, c) => s + c.games, 0)} games · ${mine.length} played · ${esc(members.join(', '))}</span>` +
      (mine.length > 12 ? `<button type="button" class="linkbtn" ${ui({ cexp: Object.assign({}, UI.cexp, { [family]: !open }) })}>${open ? 'Show fewer' : 'Show all ' + mine.length + ' →'}</button>` : '') + '</div>' +
      `<div class="cgrid">${shown.map(c => `<button type="button" class="ccard${c.games < LOW ? ' thin' : ''}" ${set({ champ: c.champ, crole: rf === 'All' ? '' : rf })}>${cicon(c.champ, 52, true)}` +
        `<span><b>${esc(C(c.champ).n)}</b><small>${c.games} games · <span class="${c.games < LOW ? '' : c.wr >= 52 ? 'pos' : c.wr < 48 ? 'neg' : ''}">${pc1(c.wr)}</span></small>` +
        `<small>${esc(C(c.champ).c)} · most: ${fn(c.most)}</small></span></button>`).join('')}</div>`;
  });
  return out + '<p class="muted small" style="margin-top:18px">Classes and tags are the League of Legends Wiki\'s. Winrate is the group\'s; under ten games it is greyed.</p>';
}

/* How one top-champions score was reached: the chain of multipliers, and the
   three things behind them. */
function scoreWorking(w, slug, role) {
  const s = w.score;
  if (!s) return '<div class="empty">None of these games could be scored yet.</div>';
  const box = (lab, big, sub, hi) => `<div class="swbox${hi ? ' hi' : ''}"><div class="lab">${lab}</div><div class="big">${big}</div><div class="sub">${sub}</div></div>`;
  const times = (v, lab) => `<div class="swx"><b>× ${v}</b><span>${lab}</span></div>`;
  const chain = `<div class="swchain">${box('Average game score', s.raw.toFixed(1), `${s.scored} scored games`)}${times(s.rankW.toFixed(2), 'rank weight')}` +
    `${box('Rank-weighted', s.weighted.toFixed(1), `mostly ${esc(rankName(s.rank))} = ${rankWeight(s.rank)}`)}${times(s.gamesMult.toFixed(2), 'games played')}` +
    `${box('Games-weighted', (s.weighted * s.gamesMult).toFixed(1), `0.5 + ${s.games} × 0.01 · full at ${SC.full}`)}${times(s.wrMult.toFixed(3), 'vs usual winrate')}` +
    `${box('Top champions score', s.score.toFixed(1), s.champWr == null ? 'no winrate to compare with yet' : `adjusted WR ${s.adjWr}% vs ${s.champWr}%`, true)}</div>`;
  const weights = `<div class="swcard"><h3>Rank weight</h3>${SC.weights.filter(r => TIERS.indexOf(r[0]) >= 2).map(r => {
    const t = TIERS.indexOf(r[0]);
    return `<div class="kv"><span>${r[0]}${r[1].length > 1 ? ' I–IV' : ''}</span><span>${r[1].map((v, i) => t === s.rank[0] && (r[1].length === 1 || i + 1 === s.rank[1]) ? `<b style="color:${TCOL[t]}">${v.toFixed(2)}</b>` : v.toFixed(2)).join(' · ')}</span></div>`;
  }).join('')}</div>`;
  const gx = g => 20 + 220 * Math.min(g, 60) / 60, gy = m => 100 - 80 * (m - 0.5) / 0.5;
  const gm = `<div class="swcard"><h3>Games played multiplier</h3><svg class="chart" viewBox="0 0 260 124" role="img" aria-label="Games played multiplier">` +
    [0.5, 0.75, 1].map(m => `<line x1="20" x2="240" y1="${gy(m)}" y2="${gy(m)}" class="axis"/><text x="16" y="${gy(m) + 4}" text-anchor="end">×${m}</text>`).join('') +
    [0, 20, 40, 60].map(g => `<text x="${gx(g)}" y="118" text-anchor="middle">${g}</text>`).join('') +
    `<path d="M${gx(0)} ${gy(0.5)} L${gx(50)} ${gy(1)} L${gx(60)} ${gy(1)}" fill="none" stroke="#b08cff" stroke-width="2"/>` +
    `<line x1="${gx(s.games)}" x2="${gx(s.games)}" y1="14" y2="100" stroke="#56607a" stroke-dasharray="3 3"/>` +
    `<text x="${gx(s.games) + (s.games > 40 ? -6 : 6)}" y="${gy(s.gamesMult) + 14}" text-anchor="${s.games > 40 ? 'end' : 'start'}">${s.games} → ×${s.gamesMult.toFixed(2)}</text></svg></div>`;
  const wrow = (lab, v, color) => `<div class="wrrow"><span class="l">${lab}</span>${wrBar(v, color)}<b>${pc1(v)}</b></div>`;
  const wr = `<div class="swcard"><h3>Winrate vs the champion's usual</h3>${wrow(esc(w.label) + ' (adjusted)', s.adjWr, col(w.label))}` +
    (s.champWr == null ? '<p class="muted small">Too few games of this champion, or its class, in the stored lobbies to compare with yet.</p>'
      : wrow(esc(s.wrSource), s.champWr, '#38bdf8') + `<p class="muted small">${signed(s.adjWr - s.champWr, ' points')} → ×${s.wrMult.toFixed(3)} (held between ${SC.limits[0]} and ${SC.limits[1]}). ` +
        `Adjusted is (wins + ${SC.prior[0]}) / (games + ${SC.prior[1]}), so a short hot streak does not jump the score. From ${s.wrGames} games by other players.</p>`) + '</div>';
  return chain + `<div class="grid g3" style="margin:14px 0 0">${weights}${gm}${wr}</div>`;
}

function tabChampions() {
  const L = D.champions.list, det = D.champions.detail;
  if (!L.length) return empty('No champion games stored yet.');
  const cur = L.find(c => c.champ === S.champ);
  if (!cur) return champGrid();
  const roles = cur.roles;
  const role = (roles.find(r => r[0] === S.crole) || roles.find(r => det[cur.champ + '|' + r[0]]) || roles[0])[0];
  const X = det[cur.champ + '|' + role], cm = C(cur.champ), rl = RN[role].toLowerCase(), rls = RLS[role];
  const title = `${esc(cm.n)} ${rl}`;
  let out = `<section class="card" style="margin-bottom:20px"><div class="champ-head"><button type="button" class="pill sm" ${set({ champ: '', crole: '' })}>← All champions</button>` +
    `<div class="id">${cicon(cur.champ, 64)}<div><h2>${esc(cm.n)}</h2><div class="chips">${classChips(cur.champ)}</div></div></div>${searchBox(false)}` +
    `<div class="pills"><span class="pill-label">Role</span>${roles.map(r => pill(`${ricon(r[0])}${RN[r[0]]} · ${r[1]}`, r[0] === role, set({ champ: cur.champ, crole: r[0] }), ' sm')).join('')}</div>` +
    (X ? `<div class="tiles" style="margin:0;flex:1 1 380px;grid-template-columns:repeat(3,1fr)">${tile('Group winrate', pc1(X.wr), `${X.games} games`, 'inner')}` +
      `${tile(`All other ${esc(cm.n)} ${rls}`, X.lobby.wr == null ? '-' : pc1(X.lobby.wr), X.lobby.n ? `${X.lobby.n} games` : 'none met yet', 'inner')}` +
      `${tile('Group gold diff @15', `<span class="${gcls(X.g15)}">${gold(X.g15)}</span>`, 'vs lane opponent', 'inner')}</div>` : '') +
    '</div></section>';
  if (!X) return out + empty(`Fewer than three stored games of ${title}. Pick another role or champion.`);

  /* matchups: overall, then each friend beside it */
  const cell = (v, base) => !v ? '<td class="num muted">-</td>' :
    `<td class="heat mcell${v[0] < LOW ? ' thin' : ''}" style="background:${v[0] < LOW ? 'transparent' : heat(v[1] - (base == null ? 50 : base), 0, 18)}"><b>${pc0(v[1])}</b> <small>${v[0]}g</small><br><small class="${gcls(v[2])}">${gold(v[2])}</small></td>`;
  out += card('Matchups: overall and each player',
    `"Overall" is every ${title} in the stored games against that champion. A player's cell is coloured by how far they beat (green) or fall short of (red) it. Under ten games: greyed.`,
    X.matchups.length ? tableWrap(`<thead><tr><th>Enemy ${rl}</th><th class="num">Overall (all ${esc(cm.n)} ${rls})</th>` +
      X.cols.map(l => `<th class="num" style="color:${col(l)}">${esc(l)}</th>`).join('') + '<th class="num">Stands out</th></tr></thead><tbody>' +
      X.matchups.map(m => `<tr><td>${champ(m.opp)}</td><td class="num"><b>${pc1(m.all[1])}</b> <small class="muted">${m.all[0]}g</small><br><small class="${gcls(m.all[2])}">${gold(m.all[2])} @15</small></td>` +
        X.cols.map(l => cell(m.per[l], m.all[1])).join('') +
        `<td class="num">${!m.best ? '<span class="muted">-</span>' : Math.abs(m.best[1]) < 5 ? '<span class="muted">≈ in line</span>' :
          `<span class="${m.best[1] > 0 ? 'pos' : 'neg'}">${m.best[1] > 0 ? '▲' : '▼'} ${esc(m.best[0])} ${m.best[1] > 0 ? '+' : '−'}${Math.abs(m.best[1])} pts</span>`}</td></tr>`).join('') + '</tbody>')
      : '<div class="empty">No lane opponents recorded.</div>');

  /* radar by rank, winrate by rank, gold against the usual */
  const tiers = Object.keys(X.radar.ranks).map(Number);
  const series = tiers.map(t => ({ vals: X.radar.ranks[t], color: TCOL[t], width: 1.8 }));
  series.push({ vals: X.radar.me, color: col(X.radar.who), fill: true, width: 2.4 });
  const radCard = card(`${RN[role]} radar by rank`, `${esc(X.radar.who)}'s ${esc(cm.n)} against the average ${title} at each rank. Percentile among all ${rls}.`,
    radar(X.radar.axes.map(statName), series, { label: title + ' radar' }) +
    `<div class="legend"><span><i class="sw" style="background:${col(X.radar.who)}"></i>${esc(X.radar.who)} (${X.radar.games})</span>` +
    tiers.map(t => `<span><i class="sw" style="background:${TCOL[t]}"></i>${TSHORT[t]}</span>`).join('') + (tiers.length ? '' : '<span class="muted">too few at any one rank for a line yet</span>') + '</div>');
  const rankCard = card('Winrate by rank', `Group's ${title} against every other ${title}, by the lobby's average rank.`,
    X.byRank.length ? '<div class="scroll"><table class="tbl"><thead><tr><th>Lobby rank</th><th class="num">Games</th><th class="num">Group</th><th class="num">All others</th><th class="num">Difference</th></tr></thead><tbody>' +
      X.byRank.map(r => { const d = r[2] != null && r[4] != null && r[3] >= LOW ? r[2] - r[4] : null;
        return `<tr class="${r[1] < LOW ? 'thin' : ''}"><td>${tierText(r[0])}</td><td class="num">${r[1]}</td><td class="num strong">${pc1(r[2])}</td>` +
          `<td class="num muted">${r[3] >= LOW ? pc1(r[4]) : '-'}</td><td class="num ${gcls(d)}">${d == null ? '-' : signed(d, ' pts')}</td></tr>`; }).join('') + '</tbody></table></div>' +
      X.byRank.map(r => `<div class="wrrow${r[1] < LOW ? ' thin' : ''}"><span class="l">${tierText(r[0])}</span><div class="wrbar"><i style="width:${Math.min(100, r[2])}%;background:${TCOL[r[0]]}"></i>` +
        `${r[3] >= LOW ? `<u style="left:${Math.min(100, r[4])}%"></u>` : ''}</div><b>${pc0(r[2])}</b></div>`).join('') +
      '<div class="legend"><span>bar = group</span><span><i class="sw" style="background:#fff;width:2px;height:12px"></i>all others</span></div>'
      : '<div class="empty">No rank on these games yet.</div>');
  const ys = X.gold.flatMap(p => p.y.filter(v => v != null)), span = Math.max(500, Math.ceil(Math.max(...ys.map(Math.abs), 0) / 500) * 500);
  const goldCard = card('Gold vs the usual by minute', `Gold minus the average ${X.scoped ? title : rl} at that minute, so the lines spread out instead of sitting on top of each other.`,
    X.gold.length ? lineChart(X.gold.map(p => ({ pts: p.y.map((v, i) => [i, v]), color: col(p.label), end: p.label })),
      { x0: 0, x1: 25, y0: -span, y1: span, xt: [0, 5, 10, 15, 20, 25], xf: v => v + 'm', r: 70, zero: true, yt: [-span, -span / 2, 0, span / 2, span], yf: v => v === 0 ? '0' : gold(v), vline: 15, label: 'Gold against the usual by minute' })
      : '<div class="empty">Needs three games from one player.</div>');
  out += `<div class="grid g3">${radCard}${rankCard}${goldCard}</div>`;

  /* who plays it, and how the score was reached */
  const sel = X.who.find(w => w.label === S.cwho) || X.who[0];
  out += card(`Who plays ${title}`, `Ranked by the top champions score. Click a row to see how it was worked out. Scores were last recalculated ${esc(D.meta.generatedAt || 'this build')}.`,
    tableWrap('<thead><tr><th>Player</th><th class="num">Games</th><th>Top champions score</th><th class="num">Avg game score</th><th class="num">Winrate</th><th class="num">KDA</th>' +
      `<th class="num">Gold diff @15</th><th class="num">For their rank</th></tr></thead><tbody>` +
      X.who.map(w => `<tr class="click${w === sel ? ' me' : ''}" ${set({ cwho: w.label })}><td>${who(w.label)}</td><td class="num">${w.games}${low(w.games)}</td>` +
        `<td>${scoreBar(w.score ? w.score.score : null)}</td><td class="num">${w.score ? w.score.raw.toFixed(0) : '-'}</td><td class="num">${pc1(w.wr)}</td>` +
        `<td class="num">${w.kda == null ? '-' : w.kda.toFixed(1)}</td><td class="num strong ${gcls(w.g15)}">${gold(w.g15)}</td>` +
        `<td class="num">${verdict(w.score && w.score.verdict)}</td></tr>`).join('') + '</tbody>') +
    `<h3>How ${esc(sel.label)}'s ${sel.score ? sel.score.score.toFixed(1) : 'score'} is worked out</h3>${scoreWorking(sel, cur.champ, role)}`);

  const item = id => `<span class="chip">${iicon(id)}${esc(D.items[id] || 'Item ' + id)}</span>`;
  const bu = card('Builds', 'Most common first three finished items, with boots.',
    (X.builds.length ? X.builds.map(bd => `<div class="build"><div class="items">${bd.items.map(item).join('<span class="muted">→</span>')}` +
      `${bd.boots ? '<span class="muted">+</span>' + item(bd.boots) : ''}</div><div class="muted small" style="margin-top:8px">${bd.games} games · ` +
      `<b class="${bd.wr >= 50 ? 'pos' : 'neg'}">${pc1(bd.wr)} winrate</b></div></div>`).join('') : '<div class="empty">No game here reached three finished items.</div>') +
    (X.skill ? `<h3>Skill order</h3><span class="chip" style="padding-left:11px">${esc(X.skill.order)}</span> <span class="muted">${X.skill.share}% of games</span>` : ''));
  const plan = planFor(cur.champ, role), LN = { role: 'Role', class: 'Class', tag: 'Tag' };
  const how = card(`How a ${title} game is scored`, `Each number becomes a percentile against ${rls} at the same rank, then the layers are combined: role ${SC.layer.role * 100}%, class ${SC.layer.class * 100}%, tags ${SC.layer.tag * 100}%.`,
    '<table class="tbl"><tbody>' + plan.map(p => `<tr><td><span class="tag ly ly-${p[0]}">${LN[p[0]]}</span></td><td>${esc(p[3] ? p[3] + ': ' : '')}${esc(STAT[p[1]].label)}${STAT[p[1]].up ? '' : ' (fewer)'}</td>` +
      `<td class="num muted">${p[2] !== 1 ? '×' + p[2] + ' weight' : ''}</td></tr>`).join('') + '</tbody></table>' +
    `<p class="muted small" style="margin-top:10px">A number that already counted in an earlier layer is not counted twice. Tags with nothing a match records (${(cm.tg || []).filter(t => !SC.tag[t]).map(esc).join(', ') || 'none here'}) add nothing.</p>`);
  const third = X.clear && X.clear.length ? card(`First clear (${esc(X.radar.who)})`, 'Where they usually are at 1:00 to 4:00, turned to blue side.', `<div class="mapwrap">${routeSvg(X.clear)}</div>${routeLegend(X.clear)}`) : '';
  out += `<div class="grid ${third ? 'g3' : 'g2'}">${bu}${how}${third}</div>`;
  return out;
}
