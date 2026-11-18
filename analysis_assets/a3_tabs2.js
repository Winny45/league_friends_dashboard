/* ---- Roles & classes ----------------------------------------------------------- */
const classPlural = c => c.toLowerCase() + 's';
function tabRoles() {
  const role = ROLES.includes(S.rtab) ? S.rtab : 'UTILITY', R = D.roles.roles[role], rl = RN[role].toLowerCase(), rls = RLS[role];
  const cls = R.views[S.cls] ? S.cls : 'All', V = R.views[cls];
  /* With a class picked, everything on the card is about that class: the
     heading, the two comparison rows and what a cell is coloured against. */
  const group = cls === 'All' ? rls : classPlural(cls) + (role === 'UTILITY' && ['Enchanter', 'Catcher', 'Warden'].includes(cls) ? '' : ' in ' + rl);
  let out = `<div class="pillrow"><div class="pills">${ROLES.map(r => pill(ricon(r) + RN[r], r === role, set({ rtab: r, cls: 'All' }))).join('')}</div>` +
    `<div class="pills"><span class="pill-label">Class filter</span>${pill(`All ${rls}`, cls === 'All', set({ cls: 'All' }), ' sm')}` +
    R.classes.map(c => pill(esc(c[0]), cls === c[0], set({ cls: c[0] }), ' sm')).join('') + '</div></div>';
  const cols = R.cols, short = { kp: 'Kill part.', vpm: 'Vision/min', hs: 'Heal+shield', cc: 'CC score', roam: 'Roam %', deaths: 'Deaths', g15: 'Gold@15',
    cspm: 'CS/min', dshare: 'Dmg share', dpm: 'Dmg/min', solo: 'Solo kills', objp: 'Obj part.', epics: 'Obj dmg %', ejg: 'Enemy camps', tur: 'Turret dmg',
    dpg: 'Dmg/gold', botg15: 'Bot lane@15', wkc: 'Wards+ctrl' };
  const cell = (k, v, n, colour) => `<td class="heat${colour && n < LOW ? ' thin' : ''}" style="${colour && v[1] != null ? 'background:' + heatN(v[1], n, 50, 28) : ''}">${stat(k, v[0])}</td>`;
  const line = (r, name, colour, klass) =>
    `<tr class="${klass}"><td>${name}</td><td class="num">${r.games}${colour ? low(r.games) : ''}</td>` +
    `<td class="heat${colour && r.games < LOW ? ' thin' : ''}" style="${colour ? 'background:' + heatN(r.wr, r.games, 50, 12) : ''}">${pc1(r.wr)}</td>${cell('kda', r.vals.kda, r.games, colour)}` +
    cols.map(k => cell(k, r.vals[k], r.games, colour)).join('') + '</tr>';
  out += card(`${esc(RN[role])}${cls === 'All' ? '' : ' · ' + esc(cls)} · everyone side by side`,
    `Cell colour is the percentile against lobby ${esc(group)}: red below, grey average, green above. Under five games a cell has no colour; under ten it is greyed.`,
    V.rows.length ? tableWrap(`<thead><tr><th>Player</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">KDA</th>` +
      cols.map(k => `<th class="num" title="${esc(STAT[k].label)}">${short[k] || STAT[k].label}</th>`).join('') + '</tr></thead><tbody>' +
      V.rows.map(r => line(r, who(r.label), true, '')).join('') +
      (V.group ? line(V.group, `<b class="muted">Group ${esc(group)}</b>`, false, 'dim') : '') +
      (V.lobby ? line(V.lobby, `<b class="muted">Lobby ${esc(group)}</b>`, false, 'dim') : '') + '</tbody>')
      : '<div class="empty">Nobody has stored games here.</div>');

  const M = D.roles.matrix, names = FR;
  let grid = `<div class="hm fit" style="grid-template-columns:104px repeat(${names.length}, minmax(52px, 1fr))"><div></div>` +
    names.map(n => `<div class="h" style="color:${col(n)}">${esc(n)}</div>`).join('');
  Object.keys(M).forEach(c => {
    grid += `<div class="r">${esc(c)}</div>` + names.map(n => {
      const v = M[c][n];
      if (!v) return '<div class="c none muted">-</div>';
      const wr = 100 * v[1] / v[0];
      return `<div class="c${v[0] < LOW ? ' faint' : ''}" style="background:${heatN(wr, v[0], 50, 14)}">${wr.toFixed(0)}%<small>${v[0]}g</small></div>`;
    }).join('');
  });
  const matrix = card('Winrate by class', 'Every role, whole season. Under five games a cell has no colour; under ten it is faded. The small number is games.', `<div class="scroll">${grid}</div></div>`);
  const objs = card('Objective participation by role', "Share of the team's dragons, grubs, heralds, barons and Atakhans each role was part of. Junglers are part of nearly all of them, which is why they are compared on objective damage instead.",
    D.roles.objectives.map(o => `<div class="hbar"><span class="cell-champ">${ricon(o.role)}${RN[o.role]}</span><div class="track"><i style="width:${Math.round((o.group || 0) * 100)}%"></i>` +
      (o.lobby != null ? `<em style="left:${Math.round(o.lobby * 100)}%"></em>` : '') + `</div><span class="num">${o.group == null ? '-' : Math.round(o.group * 100) + '%'}</span></div>`).join('') +
    '<div class="legend"><span><i class="sw" style="background:#8b6cf6"></i>Group</span><span><i class="sw" style="background:#fff;width:2px;height:12px"></i>lobby average</span></div>');
  const ins = card('Class insights', 'Worked out from the stored games; each appears once it has thirty or more to stand on.',
    D.roles.insights.length ? D.roles.insights.map(i => `<div class="insight"><span style="font-size:19px">${i[0]}</span><span>${esc(i[1])}</span></div>`).join('')
      : '<div class="empty">Not enough stored games for any of these yet.</div>');
  out += `<div class="grid g-3-2">${matrix}<div class="stack">${objs}${ins}</div></div>`;
  return out;
}

/* ---- Time patterns -------------------------------------------------------------- */
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const hourLabel = h => ((h % 12) || 12) + (h < 12 ? 'am' : 'pm');
function sessionModal(me) {
  const bn = D.time.sessions[me].byNumber;
  /* Half the game numbers in each column rather than one long column, so a
     late game can be read against an early one without scrolling. */
  const table = (from, to) => {
    const body = bn.slice(from, to).map((b, k) => {
      const i = from + k;
      if (!b[0]) return `<tr class="thin"><td class="strong">Game ${i + 1}</td><td class="num">0</td><td></td><td></td><td></td></tr>`;
      const wr = 100 * b[1] / b[0];
      return `<tr class="${b[0] < 30 ? 'thin' : ''}"><td class="strong">Game ${i + 1}${i === bn.length - 1 ? '+' : ''}</td><td class="num">${b[0]}</td>` +
        `<td><div class="wrrow" style="margin:0"><div class="wrbar"><i style="width:${Math.min(100, wr)}%;background:${heat(wr, 50, 9)}"></i><em></em></div><b>${pc1(wr)}</b></div></td>` +
        `<td class="num strong ${gcls(b[2])}">${gold(b[2])}</td><td class="num">${b[3] == null ? '-' : b[3].toFixed(1)}</td></tr>`;
    }).join('');
    return `<div class="scroll"><table class="tbl"><thead><tr><th>Game in session</th><th class="num">Games</th>` +
      `<th style="min-width:110px">Winrate</th><th class="num">Lane gold @15</th><th class="num">Deaths</th></tr></thead><tbody>${body}</tbody></table></div>`;
  };
  const half = Math.ceil(bn.length / 2);
  const rows = `<div class="grid g2" style="margin:0;gap:18px">${table(0, half)}${table(half, bn.length)}</div>`;
  const late = bn.slice(8).reduce((a, b) => [a[0] + b[0], a[1] + b[1]], [0, 0]), early = bn.slice(0, 3).reduce((a, b) => [a[0] + b[0], a[1] + b[1]], [0, 0]);
  const note = late[0] >= 30 && early[0] >= 30 ? `Games 1 to 3 are won ${pc0(100 * early[1] / early[0])} of the time; from game 9 on it is ${pc0(100 * late[1] / late[0])} over ${late[0]} games.` : '';
  openModal(`<div class="modal-head"><div><h2>Game number in a session · full breakdown</h2>` +
    `<p class="hint">${me === 'All' ? 'All friends' : esc(me)} · every game number, to game ${bn.length} and beyond. A session ends after an hour with no game. Rows under 30 games are faded.</p></div>` +
    `<button type="button" class="pill sm" data-close>✕ Close</button></div>` +
    rows +
    (note ? `<p class="muted small" style="margin-top:12px">${note}</p>` : ''));
}
/* `fixed` is a player whose profile this is drawn on: their games only, and
   no picker for whose games. */
function tabTime(fixed) {
  const T = D.time, names = FR.filter(l => T.views[l] && T.views[l].games);
  const me = fixed && T.views[fixed] ? fixed : T.views[S.who] && S.who !== 'All' ? S.who : 'All', V = T.views[me], metric = ['wr', 'games', 'gold'].includes(S.metric) ? S.metric : 'wr';
  let out = `<div class="pillrow">${fixed ? `<span class="muted">${esc(fixed)}'s games only, UK time.</span>` : friendPills('who', me, names, true)}<div class="pills">` +
    [['wr', 'Winrate'], ['games', 'Games played'], ['gold', 'Gold @15']].map(m => pill(m[1], metric === m[0], set({ metric: m[0] }), ' sm')).join('') + '</div></div>';
  const t = V.tiles;
  out += '<div class="tiles">' +
    (t.best ? tile('Best time to queue', esc(t.best.label), `<span class="pos">${t.best.wr}% over ${t.best.games} games</span>`) : tile('Best time to queue', '-', 'no three-hour slot has 30 games yet')) +
    (t.worst ? tile('Worst time to queue', esc(t.worst.label), `<span class="neg">${t.worst.wr}% over ${t.worst.games} games</span>`) : tile('Worst time to queue', '-', 'no three-hour slot has 30 games yet')) +
    (t.busiest ? tile('Busiest hour', esc(t.busiest.label), `${t.busiest.games} games`) : '') +
    tile('Weekday vs weekend', `${t.weekday == null ? '-' : Math.round(t.weekday) + '%'} · ${t.weekend == null ? '-' : Math.round(t.weekend) + '%'}`, 'Mon–Fri · Sat–Sun') + '</div>';

  /* every hour of the day, starting where a night's games stop being last night's */
  const hours = []; for (let i = 0; i < 24; i++) hours.push((T.dayStarts + i) % 24);
  const maxN = Math.max(1, ...V.cells.flatMap(r => r.map(c => c[0])));
  let grid = `<div class="hm day" style="grid-template-columns:48px repeat(24, minmax(44px, 1fr))"><div></div>` +
    hours.map(h => `<div class="h">${hourLabel(h)}</div>`).join('');
  DAYS.forEach((dname, d) => {
    grid += `<div class="r">${dname}</div>` + hours.map(h => {
      const c = V.cells[d][h];
      if (!c[0]) return '<div class="c none"></div>';
      const wr = 100 * c[1] / c[0];
      if (metric === 'games') return `<div class="c" style="background:rgba(76,141,255,${(0.12 + 0.75 * c[0] / maxN).toFixed(2)})">${c[0]}<small>${c[0] < BLANK ? '' : wr.toFixed(0) + '%'}</small></div>`;
      /* Under five games the cell is there, so the hour reads as played, but says nothing. */
      if (c[0] < BLANK) return `<div class="c blank" title="${c[0]} game${c[0] === 1 ? '' : 's'}"><small>${c[0]}</small></div>`;
      if (metric === 'gold') return c[2] == null ? `<div class="c faint" style="background:rgb(${NEUTRAL})">-<small>${c[0]}</small></div>`
        : `<div class="c${c[0] < LOW ? ' faint' : ''}" style="background:${heat(c[2], 0, 1800)}">${gold(c[2])}<small>${c[0]}</small></div>`;
      return `<div class="c${c[0] < LOW ? ' faint' : ''}" style="background:${heat(wr, 50, 14)}">${wr.toFixed(0)}%<small>${c[0]}</small></div>`;
    }).join('');
  });
  const titles = { wr: 'Winrate by day and hour', games: 'Games played by day and hour', gold: 'Team gold lead at 15 by day and hour' };
  out += `<div class="grid">${card(titles[metric], `UK time, all 24 hours from ${T.dayStarts}am. Games after midnight sit on the row of the evening they belong to. Cells under five games are left blank; under ten are faded.`,
    `<div class="scroll">${grid}</div></div>` + (metric === 'wr' ? `<div class="legend"><span><i class="sw" style="background:${heat(36, 50, 14)}"></i>35%</span>` +
      `<span><i class="sw" style="background:${heat(50, 50, 14)}"></i>50%</span><span><i class="sw" style="background:${heat(65, 50, 14)}"></i>65%+</span></div>` : ''))}</div>`;

  /* game number in a session: six bars and the rest, which opens the full table */
  const Sx = T.sessions[me], all = Sx.byNumber;
  const rest = all.slice(6).reduce((a, b) => [a[0] + b[0], a[1] + b[1]], [0, 0]);
  const bn = all.slice(0, 6).concat([rest]);
  const W = 760, H = 420, base = 356, bw = 84, gap = (W - 40 - 7 * bw) / 6, lo = 30, hi = 70;
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Winrate by game number in a session">`;
  [40, 50, 60].forEach(v => { const y = base - (v - lo) / (hi - lo) * (base - 34); svg += `<line x1="14" x2="${W - 14}" y1="${y}" y2="${y}" class="axis"${v === 50 ? ' stroke="#56607a" stroke-dasharray="4 4"' : ''}/><text x="${W - 16}" y="${y - 4}" text-anchor="end">${v}%</text>`; });
  bn.forEach((b, i) => {
    const x = 20 + i * (bw + gap), last = i === 6;
    svg += `<g class="sbar" data-session="${esc(me)}" tabindex="0" role="button" aria-label="Open the full breakdown">`;
    if (b[0]) {
      const wr = 100 * b[1] / b[0], hgt = Math.max(6, (Math.max(lo, Math.min(hi, wr)) - lo) / (hi - lo) * (base - 34));
      svg += `<rect x="${x}" y="${base - hgt}" width="${bw}" height="${hgt}" rx="8" fill="${heat(wr, 50, 9)}"${b[0] < LOW ? ' opacity=".5"' : ''}${last ? ' stroke="#c4b5fd" stroke-width="2"' : ''}/>` +
        `<text class="lbl" x="${x + bw / 2}" y="${base - hgt - 9}" text-anchor="middle" style="font-size:14px;fill:#f2f4f8">${wr.toFixed(1)}%</text>`;
    }
    svg += `<rect x="${x}" y="20" width="${bw}" height="${H - 24}" fill="transparent"/>` +
      `<text class="lbl" x="${x + bw / 2}" y="${base + 24}" text-anchor="middle" style="font-size:14px;fill:${last ? '#c4b5fd' : '#f2f4f8'}">${last ? '7+ ↗' : 'Game ' + (i + 1)}</text>` +
      `<text x="${x + bw / 2}" y="${base + 42}" text-anchor="middle">${b[0]} games</text></g>`;
  });
  svg += `<line x1="14" x2="${W - 14}" y1="${base}" y2="${base}" class="axis"/></svg>`;
  const sess = card('Game number in a session', 'A session ends after an hour with no game. Click any bar, or "7+", for every game number with its gold and deaths.', svg);
  const af = Sx.after, at = (lab, k) => {
    const v = af[k], wr = v[0] ? 100 * v[1] / v[0] : null;
    return tile(lab, wr == null ? '-' : `<span class="${v[0] < 30 ? '' : wr >= 52 ? 'pos' : wr < 47 ? 'neg' : ''}">${wr.toFixed(1)}%</span>`, `${v[0]} games`, 'inner' + (v[0] < LOW ? ' thin' : ''));
  };
  const after = card('After a win vs after a loss', 'Winrate of the next game in the same session.',
    `<div class="tiles" style="margin:0;grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">${at('After a win', 'win')}${at('After 1 loss', 'l1')}${at('After 2 losses', 'l2')}${at('After 3+ losses', 'l3')}</div>`);
  const hidden = T.fadeHidden.map(h => `${esc(h[0])} (${h[1]})`).join(', ');
  const fade = card('Who fades in long sessions', 'Winrate by game number, game 1 to 7+. The number is the fitted change in points across them; flatter is steadier. Shown for anyone with ten sessions that reached a fifth game.',
    (T.fade.length ? `<div class="fade-grid">${T.fade.map(f => `<div class="fade"><div class="t">${fn(f.label)}<span class="${f.delta <= -8 ? 'neg' : 'muted'}">${f.delta > 0 ? '+' : ''}${f.delta}</span></div>${spark(f.pts, col(f.label))}<div class="muted small">${f.sessions} long sessions</div></div>`).join('')}` +
      (T.steadiest ? `<div class="fade" style="text-align:center"><div class="muted small">Steadiest</div><div style="font-size:17px;margin-top:8px">${fn(T.steadiest)}</div></div>` : '') + '</div>'
      : '<div class="empty">Nobody has ten sessions that reached a fifth game yet.</div>') +
    (hidden ? `<p class="muted small" style="margin-top:12px">Not shown, with too few long sessions to draw a line through: ${hidden}.</p>` : ''));
  out += `<div class="grid g-5-4">${sess}<div class="stack">${after}${fade}</div></div>`;
  return out;
}

/* ---- Duos & stacks -------------------------------------------------------------- */
function duoPartners(fixed) {
  const PT = D.duos.partners, names = FR.filter(n => PT[n]);
  if (fixed && !PT[fixed]) return empty(`${esc(fixed)} has no champion with fifteen stored games yet.`);
  if (!names.length) return empty('Nobody has fifteen stored games on one champion yet.');
  const me = fixed || (names.includes(S.dwho) ? S.dwho : names[0]), list = PT[me];
  const E = list.find(e => e.champ + '|' + e.role === S.dchamp) || list[0];
  const proles = Object.keys(E.with), prole = proles.includes(S.drole) ? S.drole : (proles.includes('UTILITY') ? 'UTILITY' : proles.includes('BOTTOM') ? 'BOTTOM' : proles[0]);
  const X = E.with[prole], onlyRandoms = S.dshow === 'randoms', lane = X.partners.some(p => p[5] != null);
  const rows = X.partners.filter(p => !onlyRandoms || !p[1]);
  let out = `<section class="card" style="margin-bottom:20px">${fixed ? '' : `<div class="filters"><span class="pill-label">Player</span>${names.map(n => pill(av(n) + esc(n), n === me, set({ dwho: n, dchamp: '', drole: '' }), ' sm')).join('')}</div>`}` +
    `<div class="filters"><span class="pill-label">Champion</span>${list.map(e => pill(`${cicon(e.champ, 18)}${esc(C(e.champ).n)} · ${RN[e.role]} · ${e.games}g`, e === E, set({ dchamp: e.champ + '|' + e.role, drole: '' }), ' sm')).join('')}</div>` +
    `<div class="filters"><span class="pill-label">Partner role</span>${proles.map(r => pill(ricon(r) + RN[r], r === prole, set({ drole: r }), ' sm')).join('')}` +
    `<span class="pill-label" style="margin-left:10px">Show</span>${pill('Friends + randoms', !onlyRandoms, set({ dshow: '' }), ' sm')}${pill('Randoms only', onlyRandoms, set({ dshow: 'randoms' }), ' sm')}</div></section>`;
  const pr = RN[prole].toLowerCase();
  const table = card(`${esc(me)}'s ${esc(C(E.champ).n)} with each ${pr}`,
    `Every game where this ${pr} was on ${esc(me)}'s team, friend or random. Compared with ${esc(me)}'s ${esc(C(E.champ).n)} overall (${pc1(E.wr)}). Under ten games: greyed.`,
    rows.length ? tableWrap(`<thead><tr><th>${RN[prole]}</th><th>Played by</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">vs usual</th>${lane ? '<th class="num">Bot lane @15</th>' : ''}</tr></thead><tbody>` +
      rows.map(p => `<tr class="${p[2] < LOW ? 'thin' : ''}"><td>${champ(p[0])}</td><td>${p[1] ? fn(p[1]) : '<span class="muted">random</span>'}</td><td class="num">${p[2]}${low(p[2])}</td>` +
        `<td class="heat" style="background:${p[2] < LOW ? 'transparent' : heat(p[4], 0, 14)}">${pc1(p[3])}</td><td class="num ${gcls(p[4])}">${signed(p[4], ' pts')}</td>` +
        (lane ? `<td class="num strong ${gcls(p[5])}">${gold(p[5])}</td>` : '') + '</tr>').join('') + '</tbody>')
      : '<div class="empty">No partner here has three games.</div>');
  const byClass = card(`By ${pr} class`, `${esc(me)}'s ${esc(C(E.champ).n)} winrate with each kind of ${pr}.`,
    X.classes.map(c => `<div class="wrrow${c[1] < LOW ? ' thin' : ''}"><span class="l">${esc(c[0])}</span><div class="wrbar"><i style="width:${Math.min(100, c[2])}%;background:${heat(c[2], E.wr, 9)}"></i><u style="left:${Math.min(100, E.wr)}%"></u></div>` +
      `<b>${pc1(c[2])}</b><span class="muted small num">${c[1]}g</span></div>`).join('') +
    `<div class="legend"><span><i class="sw" style="background:#fff;width:2px;height:12px"></i>${esc(me)}'s ${esc(C(E.champ).n)} overall (${pc1(E.wr)})</span></div>`);
  const solid = X.classes.filter(c => c[1] >= 30).sort((a, b) => b[2] - a[2]);
  const mates = X.partners.filter(p => p[1] && p[2] >= LOW).sort((a, b) => b[3] - a[3]);
  const lines = [];
  if (solid.length >= 2) lines.push(['✨', `${esc(me)}'s ${esc(C(E.champ).n)} wins <b class="pos">${pc0(solid[0][2])}</b> with ${esc(classPlural(solid[0][0]))} and <b class="neg">${pc0(solid[solid.length - 1][2])}</b> with ${esc(classPlural(solid[solid.length - 1][0]))}.`]);
  if (mates.length) lines.push(['🤝', `${esc(mates[0][1])}'s ${esc(C(mates[0][0]).n)} is the best regular partner: <b>${pc0(mates[0][3])}</b> over ${mates[0][2]} games.`]);
  const take = card('Takeaway', 'Only from groups with thirty games, and partners with ten.',
    lines.length ? lines.map(l => `<div class="insight"><span style="font-size:19px">${l[0]}</span><span>${l[1]}</span></div>`).join('') : '<div class="empty">Not enough games in any one group yet.</div>');
  return out + `<div class="grid g-3-2">${table}<div class="stack">${byClass}${take}</div></div>`;
}
function tabDuos() {
  const U = D.duos, view = S.dview === 'partners' ? 'partners' : 'overview';
  const head = `<div class="pillrow"><div class="pills">${pill('Friends together', view === 'overview', set({ dview: '' }))}${pill('Champion pairs with randoms', view === 'partners', set({ dview: 'partners' }))}</div></div>`;
  if (view === 'partners') return head + duoPartners();
  const names = FR.filter(n => Object.keys(U.matrix[n] || {}).length);
  /* Columns shrink to fit rather than scroll: with eleven accounts the last
     two used to sit off the edge of the card, and read as missing. */
  let grid = `<div class="hm fit" style="grid-template-columns:80px repeat(${names.length}, minmax(46px, 1fr))"><div></div>` +
    names.map(n => `<div class="h" style="color:${col(n)}">${esc(n)}</div>`).join('');
  names.forEach(a => {
    grid += `<div class="r">${fn(a)}</div>` + names.map(b => {
      const v = (U.matrix[a] || {})[b];
      if (!v) return '<div class="c none muted">-</div>';
      if (a === b) return `<div class="c" style="background:rgb(${blend(NEUTRAL, [20, 24, 34], 0.5)})">${v[0].toFixed(0)}%<small>${v[1]}g alone</small></div>`;
      return `<div class="c${v[1] < LOW ? ' faint' : ''}" style="background:${heatN(v[2] == null ? 0 : v[2], v[1], 0, 10)}">${v[0].toFixed(0)}%<small>${v[1]}g</small></div>`;
    }).join('');
  });
  const syn = card('Duo synergy', "Ranked Solo/Duo winrate together, coloured by how far it beats the two players' winrates apart. The diagonal is each player queuing alone. Under five games a cell has no colour.", `<div class="scroll">${grid}</div></div>`);

  const q = U.queues.includes(S.queue) ? S.queue : 'All', st = U.stacks[q], sizes = ['Solo', 'Duo', 'Trio', 'Four', 'Five'], sn = U.stackNote;
  const stack = card('Winrate by stack size', 'How many tracked accounts were on the team.',
    `<div class="pills" style="margin-bottom:14px">${U.queues.map(x => pill(x === 'All' ? 'All queues' : esc(x.replace('Ranked ', '')), x === q, set({ queue: x }), ' sm')).join('')}</div>` +
    st.map((v, i) => {
      if (!v[0]) return `<div class="stackrow"><span>${sizes[i]}</span><div class="track"><em></em></div><span class="num muted">-</span><span class="num muted small">0 games</span></div>`;
      const wr = 100 * v[1] / v[0];
      return `<div class="stackrow${v[0] < LOW ? ' thin' : ''}"><span>${sizes[i]}</span><div class="track"><i style="width:${wr.toFixed(1)}%;background:${heat(wr, 50, 8)}"></i><em></em></div>` +
        `<span class="num">${wr.toFixed(1)}%</span><span class="num muted small">${v[0]} games</span></div>`;
    }).join('') + `<p class="muted small" style="margin-top:10px">Dashed line is 50%. ` +
    (sn.trios === 0 ? 'There are no trios because no game this season has exactly three tracked accounts on a team: it has been solo, duo, or a full five. ' : '') +
    (sn.fours ? `A "four" is a five with one account the site does not follow; the same player was the fifth in ${sn.sameFifth} of the ${sn.fours}.` : '') + '</p>');

  let rp = `<div class="hm" style="grid-template-columns:76px repeat(4, minmax(60px, 1fr))"><div></div>` + ROLES.slice(1).map(r => `<div class="h">${RN[r]}</div>`).join('');
  ROLES.slice(0, 4).forEach((a, i) => {
    rp += `<div class="r">${RN[a]}</div>` + ROLES.slice(1).map((b, j) => {
      if (j < i) return '<div class="c none"></div>';
      const v = U.rolePairs[a + '|' + b];
      if (!v) return '<div class="c none muted">-</div>';
      return `<div class="c${v[1] < LOW ? ' faint' : ''}" style="background:${heatN(v[0], v[1], 50, 9)}">${v[0].toFixed(1)}%<small>${v[1]}g</small></div>`;
    }).join('');
  });
  const pairs = card('Role pairings', 'Two friends on the same team in these roles. Number is winrate, small is games.', `<div class="scroll">${rp}</div></div>`);
  const upper = `<div class="grid g-5-4">${syn}<div class="stack">${stack}${pairs}</div></div>`;

  const cp = card('Champion pairs', '"vs usual" is against what those two players normally win on those champions.',
    U.champPairs.length ? tableWrap('<thead><tr><th>Pair</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">vs usual</th></tr></thead><tbody>' +
      U.champPairs.map(p => `<tr class="${p.games < LOW ? 'thin' : ''}"><td><span class="cell-champ">${cicon(p.a[1])}<b>${esc(C(p.a[1]).n)}</b> <span class="muted">(${esc(p.a[0])})</span>` +
        `<span class="muted">+</span>${cicon(p.b[1])}<b>${esc(C(p.b[1]).n)}</b> <span class="muted">(${esc(p.b[0])})</span></span></td>` +
        `<td class="num">${p.games}${low(p.games)}</td><td class="heat" style="background:${p.games < LOW ? 'transparent' : heat(p.wr, 50, 14)}">${pc1(p.wr)}</td>` +
        `<td class="num ${gcls(p.vs)}">${signed(p.vs, ' pts')}</td></tr>`).join('') + '</tbody>')
      : '<div class="empty">No pair has five games together yet.</div>');
  const bl = card('Bot lane pairs', 'ADC and support together. Lane @15 is their gold minus the enemy ADC and support at fifteen minutes; "usual" is that ADC\'s lane across all their games.',
    (U.botPairs.length ? tableWrap('<thead><tr><th>ADC</th><th>Support</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">Lane @15</th><th class="num">ADC\'s usual</th></tr></thead><tbody>' +
      U.botPairs.map(p => `<tr class="${p.games < LOW ? 'thin' : ''}"><td><span class="cell-champ">${cicon(p.adc[1])}${esc(C(p.adc[1]).n)} ${fn(p.adc[0])}</span></td>` +
        `<td><span class="cell-champ">${cicon(p.sup[1])}${esc(C(p.sup[1]).n)} ${fn(p.sup[0])}</span></td>` +
        `<td class="num">${p.games}${low(p.games)}</td><td class="num strong">${pc1(p.wr)}</td>` +
        `<td class="num strong ${gcls(p.lane)}">${gold(p.lane)}</td><td class="num muted">${gold(p.usual)}</td></tr>`).join('') + '</tbody>')
      : '<div class="empty">No bot lane pair has three games yet.</div>') +
    (U.botCheck.n ? `<p class="muted small" style="margin-top:10px">The minus signs are real, not a sign error: across all ${U.botCheck.n.toLocaleString('en-GB')} bot lanes in the stored games the figure averages ${gold(U.botCheck.all)}, as it must, ` +
      'and the group\'s lanes sit below that because its ADCs mostly play champions that are behind at fifteen and win later. The Game breakdown lane table shows the same numbers for any one game.</p>' : ''));
  return head + upper + `<div class="grid g-5-4">${cp}${bl}</div>`;
}

/* ---- Game flow ------------------------------------------------------------------ */
const sig = x => 1 / (1 + Math.exp(-x));
function storyCard(title, X, comeback) {
  if (!X) return card(title, '', '<div class="empty">None yet.</div>');
  const f = X.friends.map(p => `${esc(p[0])} (${esc(C(p[1]).n)})`).join(', ');
  const baron = X.baron ? ` Baron ${X.baron.stolen ? 'stolen ' : ''}at ${mmss(X.baron.t)} ${comeback ? 'turned it' : 'went the other way'}.` : '';
  const hint = `${f} · ${DS.format(new Date(X.t0))} · ${comeback ? 'won from' : 'lost from'} ${gold(X.from)}`;
  return `<section class="card fill"><h2>${title}</h2><p class="hint">${hint}</p>` +
    leadChart(X.lead, X.dur, { h: 300, w: 560, objs: X.objs.filter(o => o[1] === 'B' || o[1] === 'E' || o[1] === 'A') }) +
    (X.chance ? `<p class="muted small">${comeback ? 'Lowest' : 'Highest'} win chance: ${X.chance.p}% at ${X.chance.minute}:00` +
      `${X.scalers.length ? ` (the team had ${X.scalers.map(c => esc(C(c).n)).join(' and ')})` : ''}.${baron}</p>` : '') +
    `<button type="button" class="pill sm" style="margin-top:6px" ${set({ tab: 'game', game: X.id, team: X.team })}>Open this game →</button></section>`;
}
function tabFlow() {
  const F = D.flow, t = F.tiles;
  if (!t.games) return empty('No stored game has reached fifteen minutes yet.');
  let out = '<div class="tiles">' +
    tile('Comebacks this season', t.comebacks, 'won from 5k+ behind') +
    tile('Throws this season', `<span class="neg">${t.throws}</span>`, 'lost from 5k+ ahead') +
    tile('Lead conversion', pc1(t.conv), `<span class="${t.conv >= t.convLobby ? 'pos' : 'neg'}">${t.conv >= t.convLobby ? '▲' : '▼'} all teams ${pc1(t.convLobby)}</span> · ahead by 2k or more at 15`) +
    tile('Games ahead at 15', pc1(t.ahead15), `of ${t.games.toLocaleString('en-GB')} games`) +
    tile('Matches behind the model', t.modelGames.toLocaleString('en-GB'), 'every stored game, both teams') + '</div>';
  const c = F.curve, scale = UI.fmode === 'scale' && c.s15[0] != null;
  let curve = '<div class="empty">The model needs forty games at this minute.</div>', line = '';
  if (c.b15 != null) {
    const xs = []; for (let x = -6; x <= 6.001; x += 0.25) xs.push(x);
    let lines, legend, o = { x0: -6, x1: 6, y0: 0, y1: 100, xt: [-6, -4, -2, 0, 2, 4, 6], xf: v => v === 0 ? '0' : gold(v * 1000), yt: [0, 25, 50, 75, 100], yf: v => v + '%', vline: 0, h: 380, label: 'Win chance from gold lead', dots: c.dots.map(d => [d[0], d[1]]) };
    if (scale) {
      const [b, d] = c.s15, g = c.gap;
      lines = [{ pts: xs.map(x => [x, 100 * sig(b * x - d * g)]), color: '#f59e0b', width: 2 }, { pts: xs.map(x => [x, 100 * sig(b * x + d * g)]), color: '#2ec4b6', width: 2 },
        { pts: xs.map(x => [x, 100 * sig(b * x)]), color: '#b08cff', width: 2.5 }];
      legend = '<span><i class="sw" style="background:#b08cff"></i>Evenly matched teams, lead at 15</span><span><i class="sw" style="background:#2ec4b6"></i>The team that scales better</span>' +
        '<span><i class="sw" style="background:#f59e0b"></i>The team that scales worse</span>';
      line = `<p class="muted small">Level on gold at 15, the better-scaling of two typical teams wins about ${Math.round(100 * sig(d * g))}%. ` +
        `2k behind, it still wins about ${Math.round(100 * sig(-2 * b + d * g))}%, where an evenly matched team wins ${Math.round(100 * sig(-2 * b))}%.</p>`;
    } else {
      const se = c.se15 || 0;
      lines = [{ pts: xs.map(x => [x, 100 * sig(c.b15 * x)]), color: '#b08cff', width: 2.5 }];
      if (c.b20 != null) lines.push({ pts: xs.map(x => [x, 100 * sig(c.b20 * x)]), color: '#2ec4b6', dash: '6 5' });
      o.band = { hi: xs.map(x => [x, 100 * sig((c.b15 + 1.96 * se * Math.sign(x || 1)) * x)]), lo: xs.map(x => [x, 100 * sig((c.b15 - 1.96 * se * Math.sign(x || 1)) * x)]) };
      legend = `<span><i class="sw" style="background:#b08cff"></i>Lead at 15 min</span>${c.b20 != null ? '<span><i class="sw" style="background:#2ec4b6"></i>Lead at 20 min</span>' : ''}`;
      line = `<p class="muted small">A 2k lead at 15 wins about ${Math.round(100 * sig(c.b15 * 2))}% of the time` +
        (c.b20 != null ? `; the same lead at 20 is worth about ${Math.round(100 * sig(c.b20 * 2))}%.` : '.') + '</p>';
    }
    curve = lineChart(lines, o) + `<div class="legend">${legend}<span><i class="sw round" style="background:#fff"></i>Our games (actual)</span></div>`;
  }
  const toggle = `<span class="pills" style="margin-left:auto">${pill('Gold only', !scale, ui({ fmode: 'gold' }), ' sm')}${pill('Gold + team scaling', scale, ui({ fmode: 'scale' }), ' sm')}</span>`;
  const model = card('Win chance from gold lead', scale
    ? "With team scaling on, each team's champions shift the curve: late scalers lose less from an early deficit. Built from our own games. Dots are the actual winrate in each 1k bucket."
    : 'Built from our own games: each match gives both teams’ gold lead and the result. The shaded band is the uncertainty at 15 minutes; dots are the actual winrate in each 1k bucket.', curve + line, toggle);
  const table = card('Leads, throws and comebacks', 'A throw or comeback needs a 5k swing and a win chance that said otherwise (under 40%, counting team scaling). Flow is wins above or below what the model expected at 15 minutes, per ten games.',
    tableWrap('<thead><tr><th>Player</th><th class="num">2k+ ahead</th><th class="num">Converted</th><th class="num">Throws</th><th class="num">Comebacks</th><th class="num">Flow</th></tr></thead><tbody>' +
    F.players.map(p => `<tr><td>${who(p.label)}</td><td class="num">${p.ahead}</td><td class="heat${p.ahead < LOW ? ' thin' : ''}" style="${p.conv == null || p.ahead < LOW ? '' : 'background:' + heat(p.conv, t.convLobby || 70, 14)}">${p.conv == null ? '-' : Math.round(p.conv) + '%'}</td>` +
      `<td class="num neg">${p.throws}</td><td class="num pos">${p.comebacks}</td><td class="num strong">${p.flow > 0 ? '+' : p.flow < 0 ? '−' : ''}${Math.abs(p.flow).toFixed(1)}</td></tr>`).join('') + '</tbody>'));
  out += `<div class="grid g-5-4">${model}${table}</div>`;
  const top = Math.max(200, ...F.spill.map(s => Math.abs(s.v)), Math.abs(F.spillBase || 0)) * 1.15;
  const spill = card('Lane spillover', "When this player's lane is 1k+ ahead at 15, the average gold diff of the other four lanes on their team.",
    F.spill.length ? F.spill.map(s => `<div class="hbar" style="grid-template-columns:150px 1fr 64px"><span>${fn(s.label)} <span class="muted" style="font-weight:500">${RN[s.role]}</span></span>` +
      `<div class="track"><i style="width:${Math.max(2, 100 * Math.max(0, s.v) / top).toFixed(1)}%;background:${col(s.label)}"></i>` +
      (F.spillBase != null ? `<em style="left:${(100 * Math.max(0, F.spillBase) / top).toFixed(1)}%"></em>` : '') + `</div><span class="num ${gcls(s.v)}">${gold(s.v)}</span></div>`).join('') +
      '<div class="legend"><span><i class="sw" style="background:#fff;width:2px;height:12px"></i>typical when any lane is ahead</span></div><p class="muted small">These are patterns, not proof of cause.</p>'
      : '<div class="empty">Needs ten games with a 1k+ lane lead.</div>');
  const sc = l => l.map(r => `<div class="kv"><span class="cell-champ">${cicon(r[0], 20)}${esc(C(r[0]).n)}</span><span><b class="${r[1] >= 0 ? 'pos' : 'neg'}">${r[1] > 0 ? '+' : r[1] < 0 ? '−' : ''}${Math.abs(r[1]).toFixed(1)}</b> <span class="muted small">${r[2]}g</span></span></div>`).join('');
  const scalers = card('Which champions scale', "Points of winrate a champion's team gets beyond what its gold at 15 said, pulled toward its class until it has thirty games. This is what the scaling switch feeds in.",
    F.late.length ? `<div class="grid g2" style="margin:0;gap:18px"><div><h3 style="margin-top:0">Better later</h3>${sc(F.late)}</div><div><h3 style="margin-top:0">Better early</h3>${sc(F.early)}</div></div>` : '<div class="empty">Needs thirty games of a champion.</div>');
  out += `<div class="grid g2">${storyCard('Biggest comeback', F.comeback, true)}${storyCard('Biggest throw', F.throw, false)}</div><div class="grid g2">${spill}${scalers}</div>`;
  return out;
}
