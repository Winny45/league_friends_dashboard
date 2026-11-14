/* ---- Players ------------------------------------------------------------------ */
const ZONE = { top: ['Top', '#e6b450'], mid: ['Mid', '#b08cff'], bot: ['Bot', '#4c8dff'], river: ['River', '#2ec4b6'], jungle: ['Jungle', '#6bbf59'] };
function zoneBar(bar) {
  return `<div class="zonebar">${bar.map(z => `<span style="flex:${z[1]};background:${ZONE[z[0]][1]}" title="${ZONE[z[0]][0]} ${z[1]}%">` +
    `${z[1] >= 17 ? ZONE[z[0]][0] + ' ' + Math.round(z[1]) + '%' : z[1] >= 7 ? Math.round(z[1]) + '%' : ''}</span>`).join('')}</div>`;
}
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
function tabPlayers() {
  const names = FR.filter(l => D.players[l]);
  if (!names.length) return empty('No player has three stored games in one role yet.');
  const me = names.includes(S.player) ? S.player : names[0];
  const roles = Object.keys(D.players[me]);
  const role = roles.includes(S.role) ? S.role : roles[0];
  const P = D.players[me][role], rl = RN[role].toLowerCase();

  let out = `<div class="pillrow">${friendPills('player', me, names, false)}<div class="pills"><span class="pill-label">Role</span>` +
    roles.map(r => pill(`${ricon(r)}${RN[r]} · ${D.players[me][r].games}`, r === role, set({ role: r }), ' sm')).join('') + '</div></div>';
  out += `<div class="whohead"><span data-av-edit="${esc(me)}" role="button" tabindex="0" title="Change ${esc(me)}'s icon">${av(me, 56)}<i class="pen">\u270E</i></span>` +
    `<div><div class="big" style="font-size:24px;font-weight:700;color:${col(me)}">${esc(me)}</div>` +
    `<div class="muted">${P.games} stored ${rl} games · ${pc1(100 * P.wins / P.games)} winrate · click the portrait to change it</div></div></div>`;

  out += '<div class="tiles">' + P.tiles.map(t => tile(esc(STAT[t.k].label), stat(t.k, t.v),
    pcbar(t.pc) + `<div class="muted small" style="margin-top:6px">lobby ${rl}s avg ${stat(t.k, t.lobby)}</div>`)).join('') + '</div>';

  const labels = P.radar.axes.map(k => STAT[k].up ? STAT[k].label.replace(' / game', '') : STAT[k].label.replace(' / game', '') + ' (fewer)');
  const rad = radar(labels, [P.radar.ref ? { vals: P.radar.ref, color: '#2ec4b6', dash: true } : null, { vals: P.radar.me, color: col(me) }],
    { label: `${me} ${rl} radar` });
  const radCard = card(`${RN[role]} radar`, `Percentile vs ${rl}s in our lobbies. The dashed ring at 50 is average.`,
    rad + `<div class="legend"><span><i class="sw" style="background:${col(me)}"></i>${esc(me)} (${P.games} games)</span>` +
    (P.radar.ref ? `<span><i class="sw" style="background:#2ec4b6"></i>${esc(P.radar.refLabel)}</span>` : '') + '</div>');

  const h = P.heat, ph = UI.hphase, phs = ph === 'all' ? [0, 1, 2] : [Number(ph)];
  const flat = k => phs.reduce((a, p) => a.concat(h[k][p]), []);
  let layer = '';
  if (UI.hmode === 'pos') layer = heatLayer(h, ph) + dots(flat('a'), '#38bdf8', 2.3) + dots(flat('k'), '#34d399', 2.3);
  else if (UI.hmode === 'kills') layer = dots(flat('a'), '#38bdf8') + dots(flat('k'), '#34d399');
  else layer = crosses(flat('d'), '#ff6b6b');
  const modes = [['pos', 'Positions'], ['kills', 'Kills'], ['deaths', 'Deaths']].map(m => pill(m[1], UI.hmode === m[0], ui({ hmode: m[0] }), ' sm')).join('');
  const phases = [['0', '0–14 min'], ['1', '14–25'], ['2', '25+'], ['all', 'All']].map(m => pill(m[1], ph === m[0], ui({ hphase: m[0] }), ' sm')).join('');
  const mapCard = `<section class="card"><h2>Where ${esc(me)} plays<span class="pills" style="margin-left:auto">${modes}</span></h2>` +
    `<div class="pills" style="margin:12px 0">${phases}</div><div class="mapwrap">${mapSvg(layer)}</div>` +
    `<div class="legend">${UI.hmode === 'deaths' ? '<span><span style="color:#ff6b6b;font-weight:800">✕</span> deaths</span>'
      : (UI.hmode === 'pos' ? '<span><i class="sw" style="background:#ff8a3d"></i>time spent</span>' : '') +
        '<span><i class="sw round" style="background:#38bdf8"></i>assists</span><span><i class="sw round" style="background:#34d399"></i>kills</span>'}` +
    '<span class="muted">shown as blue side</span></div></section>';

  out += `<div class="grid g3">${radCard}${mapCard}${roamCard(me, role, P.roam)}</div>`;

  const cmp = P.compare, head = `<tr><th>Stat</th><th class="num">${esc(me)} · ${esc(RN[role])}</th>` +
    `<th class="num">${esc(me)} · ${esc(C(cmp.champ).n)}</th><th class="num">Group ${rl}s</th>` +
    `<th class="num">${esc(cmp.cls)}s (lobby)</th><th class="num">All lobby ${rl}s</th><th style="min-width:170px">Percentile</th></tr>`;
  const rows = cmp.rows.map(r => `<tr><td class="strong">${esc(STAT[r.k].label)}</td><td class="num strong">${stat(r.k, r.me)}</td>` +
    `<td class="num">${stat(r.k, r.champ)}</td><td class="num muted">${stat(r.k, r.group)}</td><td class="num muted">${stat(r.k, r.cls)}</td>` +
    `<td class="num muted">${stat(r.k, r.lobby)}</td><td>${pcbar(r.pc)}</td></tr>`).join('');
  out += card(`${esc(me)} vs comparison groups`,
    `${esc(RN[role])} games only, so these never mix with other roles. ${esc(C(cmp.champ).n)} is ${esc(me)}'s most played here (${cmp.champGames} games). Percentile is against all lobby ${rl}s.`,
    `<div class="scroll"><table class="tbl"><thead>${head}</thead><tbody>${rows}</tbody></table></div>`);
  return out;
}
function roamCard(me, role, R) {
  if (!R) return card('Roaming', 'Laning phase, 3–14 min.', '<div class="empty">Not enough early takedowns stored yet.</div>');
  if (R.jungle) {
    return card('Early pathing', 'Takedowns between 3 and 14 minutes, by where they happened.',
      `<h3>Where ${esc(me)}'s takedowns happen</h3>${zoneBar(R.bar)}` +
      (R.lobbyBar && R.lobbyBar.length ? `<h3>Lobby junglers</h3>${zoneBar(R.lobbyBar)}` : '') +
      `<div class="grid g2" style="margin:16px 0 0">${tile('Early takedowns a game', R.perGame.toFixed(1), R.lobbyPerGame != null ? `lobby junglers ${R.lobbyPerGame.toFixed(1)}` : '', 'inner')}` +
      `${tile('Counted', R.takedowns, 'kills and assists', 'inner')}</div>`);
  }
  const up = (a, b) => a == null || b == null ? '' : `<span class="${a >= b ? 'pos' : 'neg'}">${a >= b ? '▲' : '▼'} lobby ${b}%</span>`;
  let body = `<h3>Where ${esc(me)}'s takedowns happen</h3>${zoneBar(R.bar)}` +
    `<p class="muted small" style="margin:8px 0 0">In own lane: lobby ${R.lobbyOwn == null ? '-' : R.lobbyOwn + '%'} · group ${R.groupOwn == null ? '-' : R.groupOwn + '%'}</p>` +
    `<div class="grid g2" style="margin:16px 0 0">${tile('Roam takedown share', R.roamShare == null ? '-' : Math.round(R.roamShare) + '%', up(R.roamShare, R.lobbyRoam), 'inner')}` +
    `${tile(role === 'UTILITY' ? 'Time out of lane (ADC still bot)' : 'Time out of lane', R.outLane == null ? '-' : Math.round(R.outLane) + '%', up(R.outLane, R.lobbyOut), 'inner')}</div>`;
  if (R.split) {
    const s = R.split, row = (lab, f) => `<tr><td>${lab}</td><td class="num strong">${f(s.high)}</td><td class="num strong">${f(s.low)}</td></tr>`;
    const g = k => c => `<span class="${gcls(c[k])}">${gold(c[k])}</span>`;
    body += `<h3>Does roaming pay off?</h3><table class="tbl"><thead><tr><th></th><th class="num">High-roam games</th><th class="num">Low-roam games</th></tr></thead><tbody>` +
      row('Games', c => c.games) + row('Winrate', c => `<span class="${c.wr >= 50 ? 'pos' : ''}">${pc1(c.wr)}</span>`) +
      row(esc(s.aLabel), g('a')) + row(esc(s.bLabel), g('b')) + '</tbody></table>';
    if (s.high.a != null && s.low.a != null && s.high.b != null && s.low.b != null) {
      const da = s.high.a - s.low.a, db = s.high.b - s.low.b, dw = s.high.wr - s.low.wr;
      body += `<p class="muted small" style="margin-top:12px">In high-roam games the ${esc(s.aLabel.replace(' gold @15', '').toLowerCase())} is ` +
        `${gold(Math.round(da))} at 15 and the ${esc(s.bLabel.replace(' gold @15', '').toLowerCase())} ${gold(Math.round(db))}, with winrate ${dw >= 0 ? 'up' : 'down'} ` +
        `${Math.abs(dw).toFixed(0)} points. A pattern, not proof of cause.</p>`;
    }
  }
  return card('Roaming', 'Laning phase, 3–14 min.', body);
}

/* ---- Champions ---------------------------------------------------------------- */
function tabChampions() {
  const L = D.champions.list, det = D.champions.detail;
  if (!L.length) return empty('No champion games stored yet.');
  const has = c => c.roles.some(r => det[c.champ + '|' + r[0]]);
  let cur = L.find(c => c.champ === S.champ) || L.find(has) || L[0];
  const roles = cur.roles;
  let role = (roles.find(r => r[0] === S.crole) || roles.find(r => det[cur.champ + '|' + r[0]]) || roles[0])[0];
  const X = det[cur.champ + '|' + role], cm = C(cur.champ), rl = RN[role].toLowerCase();
  const title = `${esc(cm.n)} ${rl}`;
  const options = L.map(c => `<option value="${esc(C(c.champ).n)}"></option>`).join('');
  let out = `<section class="card" style="margin-bottom:20px"><div class="champ-head"><div class="id">${cicon(cur.champ, 64)}<div><h2>${esc(cm.n)}</h2>` +
    `<div class="muted">${esc(cm.t || '')}${cm.t && cm.c ? ' · ' : ''}${esc(cm.c)}</div></div></div>` +
    `<input class="search" list="champ-list" placeholder="Search champion…" aria-label="Search champion" data-champ-search><datalist id="champ-list">${options}</datalist>` +
    `<div class="pills"><span class="pill-label">Role</span>${roles.map(r => pill(`${ricon(r[0])}${RN[r[0]]} · ${r[1]}${r[0] === role ? ' games' : ''}`, r[0] === role, set({ champ: cur.champ, crole: r[0] }), ' sm')).join('')}</div>` +
    (X ? `<div class="tiles" style="margin:0;flex:1 1 380px;grid-template-columns:repeat(3,1fr)">${tile('Group winrate', pc1(X.wr), `${X.games} games`, 'inner')}` +
      `${tile(`Lobby ${esc(cm.n)} ${rl}`, X.lobby.wr == null ? '-' : pc1(X.lobby.wr), X.lobby.n ? `${X.lobby.n} games` : 'none met yet', 'inner')}` +
      `${tile('Group gold diff @15', `<span class="${gcls(X.g15)}">${gold(X.g15)}</span>`, 'vs lane opponent', 'inner')}</div>` : '') +
    '</div></section>';
  if (!X) return out + empty(`Fewer than three stored games of ${title}. Pick another role or champion.`);
  const scope = X.scoped ? `${esc(cm.n)} ${rl}s in our lobbies` : `all ${rl}s in our lobbies (too few lobby ${esc(cm.n)} games to compare against)`;

  out += card(`Who plays ${title}`, `Only ${rl} games. Other roles on this champion have their own page.`,
    `<div class="scroll"><table class="tbl"><thead><tr><th>Player</th><th class="num">Games</th><th>Performance</th><th class="num">Winrate</th><th class="num">KDA</th>` +
    `<th class="num">Gold diff @15</th><th class="num">Objective participation</th><th class="num">vs lobby ${rl}s</th></tr></thead><tbody>` +
    X.who.map(w => `<tr><td>${who(w.label)}</td><td class="num">${w.games}${low(w.games)}</td><td>${perfBar(w.perf)}</td><td class="num">${pc1(w.wr)}</td>` +
      `<td class="num">${w.kda == null ? '-' : w.kda.toFixed(1)}</td><td class="num strong ${gcls(w.g15)}">${gold(w.g15)}</td>` +
      `<td class="num">${w.objp == null ? '-' : Math.round(w.objp * 100) + '%'}</td><td class="num">${verdict(w.verdict)}</td></tr>`).join('') +
    '</tbody></table></div>');

  const rs = X.radar.players.map(p => ({ vals: p.vals, color: col(p.label) }));
  const radCard = card(`${esc(RN[role])} radar`, `Percentile vs ${scope}.`,
    (rs.length ? radar(X.radar.axes.map(k => STAT[k].label.replace(' / game', '') + (STAT[k].up ? '' : ' (fewer)')), rs, { label: title + ' radar' }) : '<div class="empty">Needs three games from one player.</div>') +
    `<div class="legend">${X.radar.players.map(p => `<span><i class="sw" style="background:${col(p.label)}"></i>${esc(p.label)} (${p.games})</span>`).join('')}<span class="muted">dashed ring = lobby average</span></div>`);

  const b = X.gold.band, xs = b.p50.map((_, i) => i), ok = i => b.p50[i] != null;
  const yMax = Math.max(1000, ...b.p75.filter(v => v != null), ...X.gold.players.flatMap(p => p.y.filter(v => v != null)));
  const top = Math.ceil(yMax / 2500) * 2500;
  const lines = [{ pts: xs.filter(ok).map(i => [i, b.p50[i]]), color: '#aeb6c6', dash: '5 4', end: 'Lobby' }]
    .concat(X.gold.players.map(p => ({ pts: p.y.map((v, i) => [i, v]), color: col(p.label), end: p.label })));
  const goldCard = card('Gold by minute', `Total gold on ${title}, against the middle half of ${scope} (shaded).`,
    lineChart(lines, { x0: 0, x1: 25, y0: 0, y1: top, xt: [0, 5, 10, 15, 20, 25], xf: v => v + ' min', r: 64,
      yt: [0, 1, 2, 3, 4].map(i => i * top / 4), yf: v => v >= 1000 ? (v / 1000).toFixed(v % 1000 ? 1 : 0) + 'k' : '0', vline: 15, label: 'Gold by minute',
      band: { hi: xs.filter(ok).map(i => [i, b.p75[i]]), lo: xs.filter(ok).map(i => [i, b.p25[i]]), color: '#aeb6c6' } }));
  out += `<div class="grid g-1-2">${radCard}${goldCard}</div>`;

  const mu = card('Matchups', `Group's ${title} against the enemy ${rl}.`,
    X.matchups.length ? `<table class="tbl"><thead><tr><th>Enemy ${rl}</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">Gold diff @15</th></tr></thead><tbody>` +
      X.matchups.map(m => `<tr><td>${champ(m.opp)}</td><td class="num">${m.games}${m.games < 10 ? ' <span class="tag low">low</span>' : ''}</td>` +
        `<td class="heat" style="background:${heat(m.wr)}${m.games < 10 ? ';opacity:.55' : ''}">${pc1(m.wr)}</td><td class="num strong ${gcls(m.g15)}">${gold(m.g15)}</td></tr>`).join('') +
      '</tbody></table>' : '<div class="empty">No lane opponents recorded.</div>');
  const item = id => `<span class="chip">${iicon(id)}${esc(D.items[id] || 'Item ' + id)}</span>`;
  const bu = card('Builds', 'Most common first three finished items, with boots.',
    (X.builds.length ? X.builds.map(bd => `<div class="build"><div class="items">${bd.items.map(item).join('<span class="muted">→</span>')}` +
      `${bd.boots ? '<span class="muted">+</span>' + item(bd.boots) : ''}</div><div class="muted small" style="margin-top:8px">${bd.games} games · ` +
      `<b class="${bd.wr >= 50 ? 'pos' : 'neg'}">${pc1(bd.wr)} winrate</b></div></div>`).join('') : '<div class="empty">No game here reached three finished items.</div>') +
    (X.skill ? `<h3>Skill order</h3><span class="chip" style="padding-left:11px">${esc(X.skill.order)}</span> <span class="muted">${X.skill.share}% of games</span>` : ''));
  let third = '';
  if (X.clear) {
    const cols = ['#b08cff', '#788296'];
    const paths = X.clear.slice(0, 2).map((p, i) => {
      const pts = p.pts.map(q => [q[0], my(q[1])]);
      return `<path d="${pts.map((q, k) => `${k ? 'L' : 'M'}${q[0]} ${q[1]}`).join(' ')}" fill="none" stroke="${cols[i]}" stroke-width="1.6" stroke-dasharray="4 3"/>` +
        pts.map((q, k) => `<circle cx="${q[0]}" cy="${q[1]}" r="7" fill="${cols[i]}"/><text x="${q[0]}" y="${q[1] + 3.5}" text-anchor="middle" style="fill:#10131a;font-size:9px;font-weight:800">${k + 2}</text>`).join('');
    }).join('');
    third = card(`First clear (${esc(X.clearWho)})`, 'Average position at 2, 3 and 4 minutes, drawn as blue side.',
      `<div class="mapwrap">${mapSvg(paths)}</div><div class="legend">${X.clear.slice(0, 2).map((p, i) =>
        `<span><i class="sw" style="background:${cols[i]}"></i>Starts ${p.start} side → ${p.end} side (${p.share}%)</span>`).join('')}</div>`);
  }
  out += `<div class="grid ${third ? 'g3' : 'g2'}">${mu}${bu}${third}</div>`;
  return out;
}

/* ---- Roles & classes ----------------------------------------------------------- */
function tabRoles() {
  const role = ROLES.includes(S.rtab) ? S.rtab : 'UTILITY', R = D.roles.roles[role], rl = RN[role].toLowerCase();
  const cls = R.views[S.cls] ? S.cls : 'All', V = R.views[cls];
  let out = `<div class="pillrow"><div class="pills">${ROLES.map(r => pill(ricon(r) + RN[r], r === role, set({ rtab: r, cls: 'All' }))).join('')}</div>` +
    `<div class="pills"><span class="pill-label">Class filter</span>${pill(`All ${rl}s`, cls === 'All', set({ cls: 'All' }), ' sm')}` +
    R.classes.map(c => pill(esc(c[0]), cls === c[0], set({ cls: c[0] }), ' sm')).join('') + '</div></div>';
  const cols = R.cols, short = { kp: 'Kill part.', vpm: 'Vision/min', hs: 'Heal+shield', cc: 'CC score', roam: 'Roam %', deaths: 'Deaths', g15: 'Gold@15',
    cspm: 'CS/min', dshare: 'Dmg share', dpm: 'Dmg/min', solo: 'Solo kills', objp: 'Obj part.', objd: 'Obj dmg' };
  const cell = (k, v, colour, thin) => `<td class="heat" style="${colour && v[1] != null ? 'background:' + heat(v[1], 50, 28) + (thin ? ';opacity:.5' : '') : ''}">${stat(k, v[0])}</td>`;
  const line = (r, name, colour, klass) => {
    const thin = colour && r.games < 10;
    return `<tr class="${klass}"><td>${name}</td><td class="num">${r.games}${thin ? ' <span class="tag low">low</span>' : ''}</td>` +
      `<td class="heat" style="${colour ? 'background:' + heat(r.wr, 50, 12) + (thin ? ';opacity:.5' : '') : ''}">${pc1(r.wr)}</td>${cell('kda', r.vals.kda, colour, thin)}` +
      cols.map(k => cell(k, r.vals[k], colour, thin)).join('') + '</tr>';
  };
  out += card(`${esc(RN[role])}${cls === 'All' ? '' : ' · ' + esc(cls)} · everyone side by side`,
    `Cell colour is the percentile against lobby ${rl}s: red below, grey average, green above. Only stats that mean something for a ${rl}.`,
    V.rows.length ? `<div class="scroll"><table class="tbl"><thead><tr><th>Player</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">KDA</th>` +
      cols.map(k => `<th class="num">${short[k] || STAT[k].label}</th>`).join('') + '</tr></thead><tbody>' +
      V.rows.map(r => line(r, who(r.label), true, '')).join('') +
      (V.group ? line(V.group, `<b class="muted">Group ${rl}s</b>`, false, 'dim') : '') +
      (V.lobby ? line(V.lobby, `<b class="muted">Lobby ${rl}s</b>`, false, 'dim') : '') + '</tbody></table></div>'
      : '<div class="empty">Nobody has stored games here.</div>');

  const M = D.roles.matrix, names = FR;
  let grid = `<div class="hm" style="grid-template-columns:110px repeat(${names.length}, minmax(74px, 1fr))"><div></div>` +
    names.map(n => `<div class="h" style="color:${col(n)}">${esc(n)}</div>`).join('');
  Object.keys(M).forEach(c => {
    grid += `<div class="r">${esc(c)}</div>` + names.map(n => {
      const v = M[c][n];
      if (!v) return '<div class="c none muted">-</div>';
      const wr = 100 * v[1] / v[0];
      return `<div class="c${v[0] < 10 ? ' faint' : ''}" style="background:${heat(wr, 50, 14)}">${wr.toFixed(0)}%<small>${v[0]}g</small></div>`;
    }).join('');
  });
  const matrix = card('Winrate by class', 'Every role, whole season. Faded cells have under ten games; the small number is games.', `<div class="scroll">${grid}</div></div>`);
  const objs = card('Objective participation by role', "Share of the team's dragons, grubs, heralds, barons and Atakhans each role was part of.",
    D.roles.objectives.map(o => `<div class="hbar"><span class="cell-champ">${ricon(o.role)}${RN[o.role]}</span><div class="track"><i style="width:${Math.round((o.group || 0) * 100)}%"></i>` +
      (o.lobby != null ? `<em style="left:${Math.round(o.lobby * 100)}%"></em>` : '') + `</div><span class="num">${o.group == null ? '-' : Math.round(o.group * 100) + '%'}</span></div>`).join('') +
    '<div class="legend"><span><i class="sw" style="background:#8b6cf6"></i>Group</span><span><i class="sw" style="background:#fff;width:2px;height:12px"></i>lobby average</span></div>');
  const ins = card('Class insights', 'Worked out from the stored games; each appears once it has thirty or more to stand on.',
    D.roles.insights.length ? D.roles.insights.map(i => `<div class="insight"><span style="font-size:19px">${i[0]}</span><span>${esc(i[1])}</span></div>`).join('')
      : '<div class="empty">Not enough stored games for any of these yet.</div>');
  out += `<div class="grid">${matrix}</div><div class="grid g2">${objs}${ins}</div>`;
  return out;
}

/* ---- Time patterns -------------------------------------------------------------- */
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const hourLabel = h => ((h % 12) || 12) + (h < 12 ? 'am' : 'pm');
function tabTime() {
  const T = D.time, names = FR.filter(l => T.views[l] && T.views[l].games);
  const me = T.views[S.who] && S.who !== 'All' ? S.who : 'All', V = T.views[me], metric = ['wr', 'games', 'gold'].includes(S.metric) ? S.metric : 'wr';
  let out = `<div class="pillrow">${friendPills('who', me, names, true)}<div class="pills">` +
    [['wr', 'Winrate'], ['games', 'Games played'], ['gold', 'Gold @15']].map(m => pill(m[1], metric === m[0], set({ metric: m[0] }), ' sm')).join('') + '</div></div>';
  const order = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5];
  const A = T.views.All.cells, floor = Math.max(1, T.views.All.games * 0.004);
  const used = order.filter(h => DAYS.reduce((s, _, d) => s + A[d][h][0], 0) >= floor);
  const hours = used.length ? order.slice(order.indexOf(used[0]), order.indexOf(used[used.length - 1]) + 1) : order;
  const maxN = Math.max(1, ...V.cells.flatMap(r => r.map(c => c[0])));
  let grid = `<div class="hm" style="grid-template-columns:54px repeat(${hours.length}, minmax(40px, 1fr))"><div></div>` +
    hours.map(h => `<div class="h">${hourLabel(h)}</div>`).join('');
  DAYS.forEach((dname, d) => {
    grid += `<div class="r">${dname}</div>` + hours.map(h => {
      const c = V.cells[d][h];
      if (!c[0]) return '<div class="c none"></div>';
      const wr = 100 * c[1] / c[0];
      if (metric === 'games') return `<div class="c" style="background:rgba(76,141,255,${(0.12 + 0.75 * c[0] / maxN).toFixed(2)})">${c[0]}<small>${wr.toFixed(0)}%</small></div>`;
      if (metric === 'gold') return c[2] == null ? `<div class="c faint" style="background:rgb(${NEUTRAL})">-<small>${c[0]}</small></div>`
        : `<div class="c${c[0] < 10 ? ' faint' : ''}" style="background:${heat(c[2], 0, 1800)}">${gold(c[2])}<small>${c[0]}</small></div>`;
      return `<div class="c${c[0] < 10 ? ' faint' : ''}" style="background:${heat(wr, 50, 14)}">${wr.toFixed(0)}%<small>${c[0]}</small></div>`;
    }).join('');
  });
  const titles = { wr: 'Winrate by day and hour', games: 'Games played by day and hour', gold: 'Team gold lead at 15 by day and hour' };
  const main = card(titles[metric], 'UK time, by game start. Games after midnight sit on the row of the evening they belong to. Faded cells have under ten games; the small number is games.',
    `<div class="scroll">${grid}</div></div>` + (metric === 'wr' ? `<div class="legend"><span><i class="sw" style="background:${heat(36, 50, 14)}"></i>35%</span>` +
      `<span><i class="sw" style="background:${heat(50, 50, 14)}"></i>50%</span><span><i class="sw" style="background:${heat(65, 50, 14)}"></i>65%+</span></div>` : ''));
  const t = V.tiles, side = '<div class="stack">' +
    (t.best ? tile('Best time to queue', esc(t.best.label), `<span class="pos">${t.best.wr}% over ${t.best.games} games</span>`) : '') +
    (t.worst ? tile('Worst time to queue', esc(t.worst.label), `<span class="neg">${t.worst.wr}% over ${t.worst.games} games</span>`) : '') +
    (t.busiest ? tile('Busiest slot', esc(t.busiest.label), `${t.busiest.games} games`) : '') +
    tile('Weekday vs weekend', `${t.weekday == null ? '-' : Math.round(t.weekday) + '%'} · ${t.weekend == null ? '-' : Math.round(t.weekend) + '%'}`, 'Mon–Fri · Sat–Sun') + '</div>';
  out += `<div class="grid" style="grid-template-columns:minmax(0,3.4fr) minmax(220px,1fr)">${main}${side}</div>`;

  const Sx = T.sessions[me], bn = Sx.byNumber, W = 760, H = 380, base = 250, bw = 82, gap = (W - 60 - 7 * bw) / 6;
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Winrate by game number in a session">`;
  const rates = bn.map(b => b[0] ? 100 * b[1] / b[0] : null), lo = 30;
  bn.forEach((b, i) => {
    const x = 30 + i * (bw + gap);
    svg += `<text class="lbl" x="${x + bw / 2}" y="${base + 20}" text-anchor="middle" style="font-size:13px;fill:#f2f4f8">${i === 6 ? '7+' : 'Game ' + (i + 1)}</text>` +
      `<text x="${x + bw / 2}" y="${base + 36}" text-anchor="middle">${b[0]} games</text>`;
    if (rates[i] == null) return;
    const hgt = Math.max(4, (rates[i] - lo) / (70 - lo) * (base - 30));
    svg += `<rect x="${x}" y="${base - hgt}" width="${bw}" height="${hgt}" rx="8" fill="${heat(rates[i], 50, 9)}"${b[0] < 10 ? ' opacity=".55"' : ''}/>` +
      `<text class="lbl" x="${x + bw / 2}" y="${base - hgt - 8}" text-anchor="middle" style="font-size:13px;fill:#f2f4f8">${rates[i].toFixed(1)}%</text>`;
  });
  svg += `<line x1="20" x2="${W - 20}" y1="${base}" y2="${base}" class="axis"/>`;
  const gs = bn.map(b => b[2]), have = gs.filter(v => v != null);
  let note = '';
  if (have.length >= 2) {
    const m = Math.max(200, ...have.map(Math.abs)), y = v => 330 - 34 * v / m;
    svg += `<line x1="30" x2="${W - 30}" y1="330" y2="330" class="axis"/><text x="24" y="${y(m) + 4}" text-anchor="end">${gold(Math.round(m))}</text>` +
      `<text x="24" y="334" text-anchor="end">0</text><text x="24" y="${y(-m) + 4}" text-anchor="end">${gold(-Math.round(m))}</text>`;
    const pts = gs.map((v, i) => v == null ? null : [30 + i * (bw + gap) + bw / 2, y(v)]).filter(Boolean);
    svg += `<path d="${pts.map((p, i) => `${i ? 'L' : 'M'}${p[0]} ${p[1].toFixed(1)}`).join(' ')}" fill="none" stroke="#b08cff" stroke-width="2"/>` +
      pts.map(p => `<circle cx="${p[0]}" cy="${p[1].toFixed(1)}" r="4" fill="#b08cff" stroke="#10131a" stroke-width="1.5"/>`).join('');
    const first = gs.find(v => v != null), last = gs.slice().reverse().find(v => v != null);
    note = `Own lane gold diff @15 goes from ${gold(first)} in game 1 to ${gold(last)} by the last bucket with data.`;
  }
  const sess = card('Game number in a session', 'A session ends after an hour with no game. Bars are winrate; the line is the average lane gold diff at 15, where the game is stored.',
    svg + '</svg>' + (note ? `<p class="muted small">${note}</p>` : ''));
  const af = Sx.after, at = (lab, k, good) => {
    const v = af[k], wr = v[0] ? 100 * v[1] / v[0] : null;
    return tile(lab, wr == null ? '-' : `<span class="${wr >= 52 ? 'pos' : wr < 47 ? 'neg' : ''}">${wr.toFixed(1)}%</span>`, `${v[0]} games`, 'inner');
  };
  const after = card('After a win vs after a loss', 'Winrate of the next game in the same session.',
    `<div class="tiles" style="margin:0;grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">${at('After a win', 'win')}${at('After 1 loss', 'l1')}${at('After 2 losses', 'l2')}${at('After 3+ losses', 'l3')}</div>`);
  const fade = card('Who fades in long sessions', 'Winrate by game number for each player. The number is the fitted change, in points, from game 1 to game 7. Flatter is steadier.',
    T.fade.length ? `<div class="fade-grid">${T.fade.map(f => `<div class="fade"><div class="t">${fn(f.label)}<span class="${f.delta <= -8 ? 'neg' : 'muted'}">${f.delta > 0 ? '+' : ''}${f.delta}</span></div>${spark(f.pts, col(f.label))}</div>`).join('')}` +
      (T.steadiest ? `<div class="fade" style="text-align:center"><div class="muted small">Steadiest</div><div style="font-size:17px;margin-top:8px">${fn(T.steadiest)}</div></div>` : '') + '</div>'
      : '<div class="empty">Needs more long sessions.</div>');
  out += `<div class="grid g2">${sess}<div class="stack">${after}${fade}</div></div>`;
  return out;
}

/* ---- Duos & stacks -------------------------------------------------------------- */
function tabDuos() {
  const U = D.duos, names = FR.filter(n => Object.keys(U.matrix[n] || {}).length);
  let grid = `<div class="hm" style="grid-template-columns:86px repeat(${names.length}, minmax(64px, 1fr))"><div></div>` +
    names.map(n => `<div class="h" style="color:${col(n)}">${esc(n)}</div>`).join('');
  names.forEach(a => {
    grid += `<div class="r">${fn(a)}</div>` + names.map(b => {
      const v = (U.matrix[a] || {})[b];
      if (!v) return '<div class="c none muted">-</div>';
      if (a === b) return `<div class="c" style="background:rgb(${blend(NEUTRAL, [20, 24, 34], 0.5)})">${v[0].toFixed(0)}%<small>${v[1]}g alone</small></div>`;
      return `<div class="c${v[1] < 10 ? ' faint' : ''}" style="background:${heat(v[2] == null ? 0 : v[2], 0, 10)}">${v[0].toFixed(0)}%<small>${v[1]}g</small></div>`;
    }).join('');
  });
  const syn = card('Duo synergy', "Ranked Solo/Duo winrate together, coloured by how far it beats the two players' winrates apart. The diagonal is each player queuing alone.", `<div class="scroll">${grid}</div></div>`);

  const q = U.queues.includes(S.queue) ? S.queue : 'All', st = U.stacks[q], sizes = ['Solo', 'Duo', 'Trio', 'Four', 'Five'];
  const stack = card('Winrate by stack size', 'How many tracked friends were on the team.',
    `<div class="pills" style="margin-bottom:14px">${U.queues.map(x => pill(x === 'All' ? 'All queues' : esc(x.replace('Ranked ', '')), x === q, set({ queue: x }), ' sm')).join('')}</div>` +
    st.map((v, i) => {
      if (!v[0]) return `<div class="stackrow"><span>${sizes[i]}</span><div class="track"><em></em></div><span class="num muted">-</span><span class="num muted small">0 games</span></div>`;
      const wr = 100 * v[1] / v[0];
      return `<div class="stackrow"><span>${sizes[i]}</span><div class="track"><i style="width:${wr.toFixed(1)}%;background:${heat(wr, 50, 8)}"></i><em></em></div>` +
        `<span class="num">${wr.toFixed(1)}%</span><span class="num muted small">${v[0]} games</span></div>`;
    }).join('') + '<p class="muted small" style="margin-top:10px">Dashed line is 50%. A stack of four can only be four of you plus one untracked friend.</p>');

  let rp = `<div class="hm" style="grid-template-columns:76px repeat(4, minmax(60px, 1fr))"><div></div>` + ROLES.slice(1).map(r => `<div class="h">${RN[r]}</div>`).join('');
  ROLES.slice(0, 4).forEach((a, i) => {
    rp += `<div class="r">${RN[a]}</div>` + ROLES.slice(1).map((b, j) => {
      if (j < i) return '<div class="c none"></div>';
      const v = U.rolePairs[a + '|' + b];
      if (!v) return '<div class="c none muted">-</div>';
      return `<div class="c${v[1] < 10 ? ' faint' : ''}" style="background:${heat(v[0], 50, 9)}">${v[0].toFixed(1)}%<small>${v[1]}g</small></div>`;
    }).join('');
  });
  const pairs = card('Role pairings', 'Two friends on the same team in these roles. Number is winrate, small is games.', `<div class="scroll">${rp}</div></div>`);
  const upper = `<div class="grid g-5-4">${syn}<div class="stack">${stack}${pairs}</div></div>`;

  const cp = card('Champion pairs', '"vs usual" is against what those two players normally win on those champions.',
    U.champPairs.length ? `<div class="scroll"><table class="tbl"><thead><tr><th>Pair</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">vs usual</th></tr></thead><tbody>` +
      U.champPairs.map(p => `<tr><td><span class="cell-champ">${cicon(p.a[1])}<b>${esc(C(p.a[1]).n)}</b> <span class="muted">(${esc(p.a[0])})</span>` +
        `<span class="muted">+</span>${cicon(p.b[1])}<b>${esc(C(p.b[1]).n)}</b> <span class="muted">(${esc(p.b[0])})</span></span></td>` +
        `<td class="num">${p.games}${p.games < 10 ? ' <span class="tag low">low</span>' : ''}</td><td class="heat" style="background:${heat(p.wr, 50, 14)}">${pc1(p.wr)}</td>` +
        `<td class="num ${gcls(p.vs)}">${p.vs == null ? '-' : (p.vs > 0 ? '+' : p.vs < 0 ? '−' : '') + Math.abs(p.vs).toFixed(1) + ' pts'}</td></tr>`).join('') + '</tbody></table></div>'
      : '<div class="empty">No pair has five games together yet.</div>');
  const bl = card('Bot lane pairs', 'ADC and support champion combinations. Lane @15 is the two of them against the two opposite, where the game is stored.',
    U.botPairs.length ? `<div class="scroll"><table class="tbl"><thead><tr><th>ADC</th><th>Support</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">Lane @15</th></tr></thead><tbody>` +
      U.botPairs.map(p => `<tr><td><span class="cell-champ">${cicon(p.adc[1])}${esc(C(p.adc[1]).n)} ${fn(p.adc[0])}</span></td>` +
        `<td><span class="cell-champ">${cicon(p.sup[1])}${esc(C(p.sup[1]).n)} ${fn(p.sup[0])}</span></td>` +
        `<td class="num">${p.games}${p.games < 10 ? ' <span class="tag low">low</span>' : ''}</td><td class="num strong">${pc1(p.wr)}</td>` +
        `<td class="num strong ${gcls(p.lane)}">${gold(p.lane)}</td></tr>`).join('') + '</tbody></table></div>'
      : '<div class="empty">No bot lane pair has three games yet.</div>');
  return upper + `<div class="grid g-5-4">${cp}${bl}</div>`;
}

/* ---- Game flow ------------------------------------------------------------------ */
const sig = x => 1 / (1 + Math.exp(-x));
function storyCard(title, X, comeback) {
  if (!X) return card(title, '', '<div class="empty">None yet.</div>');
  const f = X.friends.map(p => `${esc(p[0])} (${esc(C(p[1]).n)})`).join(', ');
  const baron = X.baron ? ` Baron ${X.baron.stolen ? 'stolen ' : ''}at ${mmss(X.baron.t)} ${comeback ? 'turned it' : 'went the other way'}.` : '';
  const hint = `${f} · ${DS.format(new Date(X.t0))} · ${comeback ? 'won from' : 'lost from'} ${gold(X.from)}`;
  return `<section class="card"><h2>${title}</h2><p class="hint">${hint}</p>` +
    leadChart(X.lead, X.dur, { h: 260, w: 560, objs: X.objs.filter(o => o[1] === 'B') }) +
    (X.chance ? `<p class="muted small">${comeback ? 'Lowest' : 'Highest'} win chance: ${X.chance.p}% at ${X.chance.minute}:00.${baron}</p>` : '') +
    `<button type="button" class="pill sm" style="margin-top:6px" ${set({ tab: 'game', game: X.id })}>Open this game →</button></section>`;
}
function tabFlow() {
  const F = D.flow, t = F.tiles;
  if (!t.games) return empty('No stored game has reached fifteen minutes yet.');
  let out = '<div class="tiles">' +
    tile('Comebacks this season', t.comebacks, 'won after 3k+ behind') +
    tile('Throws this season', `<span class="neg">${t.throws}</span>`, 'lost after 3k+ ahead') +
    tile('Lead conversion', pc1(t.conv), `<span class="${t.conv >= t.convLobby ? 'pos' : 'neg'}">${t.conv >= t.convLobby ? '▲' : '▼'} all teams ${pc1(t.convLobby)}</span> · ahead 2k+ at 15`) +
    tile('Games ahead at 15', pc1(t.ahead15), `of ${t.games} games`) +
    tile('Matches behind the model', t.modelGames.toLocaleString('en-GB'), 'every stored game, both teams') + '</div>';
  const c = F.curve;
  let curve = '<div class="empty">The model needs forty games at this minute.</div>', line = '';
  if (c.b15 != null) {
    const xs = []; for (let x = -6; x <= 6.001; x += 0.25) xs.push(x);
    const lines = [{ pts: xs.map(x => [x, 100 * sig(c.b15 * x)]), color: '#b08cff', width: 2.5 }];
    if (c.b20 != null) lines.push({ pts: xs.map(x => [x, 100 * sig(c.b20 * x)]), color: '#2ec4b6', dash: '6 5' });
    const se = c.se15 || 0;
    curve = lineChart(lines, { x0: -6, x1: 6, y0: 0, y1: 100, xt: [-6, -4, -2, 0, 2, 4, 6], xf: v => v === 0 ? '0' : gold(v * 1000), yt: [0, 25, 50, 75, 100], yf: v => v + '%', vline: 0, h: 380, label: 'Win chance from gold lead',
      band: { hi: xs.map(x => [x, 100 * sig((c.b15 + 1.96 * se * Math.sign(x || 1)) * x)]), lo: xs.map(x => [x, 100 * sig((c.b15 - 1.96 * se * Math.sign(x || 1)) * x)]) },
      dots: c.dots.map(d => [d[0], d[1]]) }) +
      `<div class="legend"><span><i class="sw" style="background:#b08cff"></i>Lead at 15 min</span>${c.b20 != null ? '<span><i class="sw" style="background:#2ec4b6"></i>Lead at 20 min</span>' : ''}` +
      '<span><i class="sw round" style="background:#fff"></i>Our games (actual)</span></div>';
    line = `<p class="muted small">A 2k lead at 15 wins about ${Math.round(100 * sig(c.b15 * 2))}% of the time` +
      (c.b20 != null ? `; the same lead at 20 is worth about ${Math.round(100 * sig(c.b20 * 2))}%.` : '.') + '</p>';
  }
  const model = card('Win chance from gold lead', 'Built from our own games: each match gives both teams’ gold lead and the result. The shaded band is the uncertainty at 15 minutes; dots are the actual winrate in each 1k bucket.', curve + line);
  const table = card('Leads, throws and comebacks', 'Flow is wins above or below what the win-chance model expected at 15 minutes, per ten games.',
    `<div class="scroll"><table class="tbl"><thead><tr><th>Player</th><th class="num">2k+ ahead</th><th class="num">Converted</th><th class="num">Throws</th><th class="num">Comebacks</th><th class="num">Flow</th></tr></thead><tbody>` +
    F.players.map(p => `<tr><td>${who(p.label)}</td><td class="num">${p.ahead}</td><td class="heat" style="${p.conv == null ? '' : 'background:' + heat(p.conv, t.convLobby || 70, 14)}">${p.conv == null ? '-' : Math.round(p.conv) + '%'}</td>` +
      `<td class="num neg">${p.throws}</td><td class="num pos">${p.comebacks}</td><td class="num strong">${p.flow > 0 ? '+' : p.flow < 0 ? '−' : ''}${Math.abs(p.flow).toFixed(1)}</td></tr>`).join('') + '</tbody></table></div>');
  out += `<div class="grid g-5-4">${model}${table}</div>`;
  const top = Math.max(200, ...F.spill.map(s => Math.abs(s.v)), Math.abs(F.spillBase || 0)) * 1.15;
  const spill = card('Lane spillover', "When this player's lane is 1k+ ahead at 15, the average gold diff of the other four lanes on their team.",
    F.spill.length ? F.spill.map(s => `<div class="hbar" style="grid-template-columns:150px 1fr 64px"><span>${fn(s.label)} <span class="muted" style="font-weight:500">${RN[s.role]}</span></span>` +
      `<div class="track"><i style="width:${Math.max(2, 100 * Math.max(0, s.v) / top).toFixed(1)}%;background:${col(s.label)}"></i>` +
      (F.spillBase != null ? `<em style="left:${(100 * Math.max(0, F.spillBase) / top).toFixed(1)}%"></em>` : '') + `</div><span class="num ${gcls(s.v)}">${gold(s.v)}</span></div>`).join('') +
      '<div class="legend"><span><i class="sw" style="background:#fff;width:2px;height:12px"></i>typical when any lane is ahead</span></div><p class="muted small">These are patterns, not proof of cause.</p>'
      : '<div class="empty">Needs eight games with a 1k+ lane lead.</div>');
  out += `<div class="grid g3">${spill}${storyCard('Biggest comeback', F.comeback, true)}${storyCard('Biggest throw', F.throw, false)}</div>`;
  return out;
}
