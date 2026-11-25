/* ---- Profile tabs after Overview ---------------------------------------------------
   Each is the site's own section filtered to one player, plus Roaming, which
   only makes sense for one player at a time. */

function lpByChamp(label, champSlug) {
  const tot = [0, 0, 0];
  accountsOf(label).forEach(a => { const v = ((D.acc[a] || {}).champLp || {})[champSlug]; if (v) v.forEach((x, i) => { tot[i] += x; }); });
  return tot;
}
const lpBox = v => `<b class="${gcls(v)}">${v ? signedInt(v) : '0'}</b>`;

/* ---- Champions ---- */
function champCard(label, c) {
  const t = c.top, cls = C(c.champ).c, R = c.radar, lp = lpByChamp(label, c.champ), total = lp[0] + lp[1] + lp[2];
  const scope = R ? (R.scope === 'rank' ? `${C(c.champ).n} ${RN[c.role] ? RLS[c.role] : ''} at ${TIERS[R.tier]}` : R.scope === 'all' ? `every ${C(c.champ).n} ${RN[c.role] ? RLS[c.role] : ''}` : `${TIERS[R.tier] || 'all'} ${RLS[c.role] || ''}`) : '';
  const rad = R ? radar(R.axes.map(statName), [{ vals: R.axes.map(() => 50), color: '#e6b450', width: 1.6 }, { vals: R.vals, color: col(label), fill: true, width: 2.4 }],
    { label: `${label} on ${C(c.champ).n}`, w: 320, h: 260, r: 80 }) + `<div class="legend" style="justify-content:center"><span><i class="sw" style="background:${col(label)}"></i>${esc(label)}</span><span><i class="sw" style="background:#e6b450"></i>average ${esc(scope)}</span></div>`
    : '<div class="empty">Needs three games in one role.</div>';
  const box = (lab, v) => `<div class="cbox"><span>${lab}</span><b>${v}</b></div>`;
  const working = t ? `games ×${t.gamesMult.toFixed(2)} · ${esc(rankName(t.rank))}${t.ranks && t.ranks.length > 1 ? ' and others' : ''} ×${t.rankW.toFixed(2)}` +
    (t.champWr != null ? ` · WR vs ${esc(t.wrSource)} ${signed(t.adjWr - t.champWr, ' pts')}` : '') : 'No scored games yet.';
  return `<section class="card ccard2"><div class="cc-head">${cicon(c.champ, 56, true)}<div><b class="cc-n">${esc(C(c.champ).n)}</b>` +
    `<div class="muted small">${esc(RN[c.role] || '-')} · ${esc(cls)}</div></div><div class="cc-sc">${ring(t ? t.score : null, 56)}<span class="muted small">score</span></div></div>` +
    rad + `<div class="cboxes">${box('Games', c.games)}${box('Winrate', pc1(100 * c.wins / c.games))}${box('KDA', c.kda == null ? '-' : c.kda.toFixed(1))}${box('Avg game', c.score == null ? '-' : c.score)}</div>` +
    `<div class="cboxes lp">${box('Solo/Duo', lpBox(lp[0]))}${box('Flex', lpBox(lp[1]))}${box('5s', lpBox(lp[2]))}${box('Total LP', lpBox(total))}</div>` +
    `<p class="muted small cc-w">${working}${t ? ` · <button type="button" class="linkbtn" data-working="${esc(c.champ)}">how this was worked out</button>` : ''}</p></section>`;
}
function profChampions(label) {
  const cards = ((D.profiles[label] || {}).champs || []).slice(), sort = ['score', 'games', 'wr', 'lp'].includes(S.psort) ? S.psort : 'score';
  const key = {
    score: c => c.top ? c.top.score : -1, games: c => c.games, wr: c => c.wins / c.games,
    lp: c => { const v = lpByChamp(label, c.champ); return v[0] + v[1] + v[2]; },
  }[sort];
  cards.sort((a, b) => key(b) - key(a));
  const tier = (D.profiles[label] || {}).tier;
  return `<div class="sec-head"><div><h2>${esc(label)}'s champions</h2><p class="muted small" style="margin:4px 0 0">Every champion with ten or more games this season. ` +
    `The radar is a percentile against that champion in that role at ${esc(label)}'s rank${tier != null ? ' (' + TIERS[tier] + ')' : ''}, or every rank when there are too few. LP is the change across every game on it, shared out where a reading covered several games.</p></div>` +
    `<div class="pills">${[['score', 'Score'], ['games', 'Games'], ['wr', 'Winrate'], ['lp', 'LP gained']].map(s => pill(s[1], sort === s[0], set({ psort: s[0] }), ' sm')).join('')}</div></div>` +
    (cards.length ? `<div class="ccards">${cards.map(c => champCard(label, c)).join('')}</div>` : empty('No champion with ten games yet.'));
}
function showWorking(label, slug) {
  const c = ((D.profiles[label] || {}).champs || []).find(x => x.champ === slug);
  if (!c || !c.top) return;
  openModal(`<div class="modal-head"><div><h2>${esc(label)} on ${esc(C(slug).n)}: how ${c.top.score.toFixed(1)} is worked out</h2>` +
    `<p class="hint">Each game is scored against players in the same role at the same rank, weighted by the rank it was played at, then adjusted for how many games there are and for winrate against the champion's usual.</p></div>` +
    `<button type="button" class="pill sm" data-close>✕ Close</button></div>${scoreWorking({ label, score: c.top }, slug, c.role)}`);
}

/* ---- Roles & classes ---- */
function roleRadar(label, role) {
  const P = D.players[label].roles[role], tiers = Object.keys(P.radar.ranks).map(Number), mine = P.tier;
  const shown = UI.prt != null ? UI.prt : tiers.filter(t => t === mine || t === mine + 1);
  const series = tiers.filter(t => shown.includes(t)).map(t => ({ vals: P.radar.ranks[t], color: TCOL[t], width: 1.8 }));
  series.push({ vals: P.radar.me, color: col(label), fill: true, width: 2.4 });
  return card(`${RN[role]} radar`, `Percentile among all ${RLS[role]}. Lines show the average at each rank.`,
    `<div class="pills">${tiers.map(t => `<button type="button" class="pill sm${shown.includes(t) ? ' ton' : ''}" style="--tc:${TCOL[t]}" ${ui({ prt: shown.includes(t) ? shown.filter(x => x !== t) : shown.concat([t]) })}>${TSHORT[t]}</button>`).join('')}</div>` +
    radar(P.radar.axes.map(statName), series, { label: `${label} ${RN[role]} radar` }) +
    `<div class="legend"><span><i class="sw" style="background:${col(label)}"></i>${esc(label)}</span>${tiers.filter(t => shown.includes(t)).map(t => `<span><i class="sw" style="background:${TCOL[t]}"></i>${TSHORT[t]}</span>`).join('')}</div>`);
}
function profRoles(label) {
  const PL = D.players[label];
  if (!PL || !Object.keys(PL.roles).length) return empty('No role with three stored games yet.');
  const roles = ROLES.filter(r => PL.roles[r]), role = roles.includes(S.role) ? S.role : roles.includes(PL.main) ? PL.main : roles[0];
  const P = PL.roles[role], tier = P.tier, next = tier != null && tier < 9 ? tier + 1 : null;
  const avg = t => t == null ? {} : (((SC.avg[role] || {})[String(t)]) || {});
  const A = avg(tier), B = avg(next);
  let out = `<div class="rcards">${roles.map(r => { const x = PL.roles[r]; return `<button type="button" class="rcard${r === role ? ' on' : ''}" ${set({ role: r })}>` +
    `<div class="rc-h"><b>${ricon(r)} ${RN[r]}</b><span class="muted small">${x.games} games</span></div>` +
    `<div class="rc-h small"><span>Winrate <b>${pc1(100 * x.wins / x.games)}</b></span><span>Avg game score <b>${x.score == null ? '-' : Math.round(x.score)}</b></span></div></button>`; }).join('')}</div>`;
  const rows = P.compare.rows.map(r => `<tr><td class="strong">${esc(STAT[r.k].label)}</td><td class="num strong">${stat(r.k, r.me)}</td>` +
    `<td class="num muted">${stat(r.k, A[r.k])}</td>${next != null ? `<td class="num muted">${stat(r.k, B[r.k])}</td>` : ''}<td>${pcbar(r.pc)}</td></tr>`).join('');
  const tbl = card(`${esc(label)} as ${/^[AEIOU]/.test(RN[role]) ? 'an' : 'a'} ${RN[role].toLowerCase()}`,
    `The ${RLS[role]}' metrics used in the game score and the table stats, against ${tier != null ? TIERS[tier] : 'all'}${next != null ? ' and ' + TIERS[next] : ''} ${RLS[role]}.`,
    tableWrap(`<thead><tr><th>Metric</th><th class="num">${esc(label)}</th><th class="num">${tier != null ? TIERS[tier] : 'All'} ${RLS[role]}</th>` +
      (next != null ? `<th class="num">${TIERS[next]} ${RLS[role]}</th>` : '') + `<th style="min-width:170px">Percentile${tier != null ? ' at ' + TIERS[tier] : ''}</th></tr></thead><tbody>${rows}</tbody>`));
  out += `<div class="grid g-2-3">${roleRadar(label, role)}${tbl}</div>`;
  const cls = (D.profiles[label] || {}).classes || [], pt = (D.profiles[label] || {}).tier;
  const best = cls.filter(c => c[2] >= LOW && c[4] != null).map(c => [100 * c[3] / c[2] - c[4], c[0]]).sort((a, b) => b[0] - a[0]);
  out += card('By class', `${esc(label)}'s games grouped by the champion's wiki class, against that class at ${pt != null ? TIERS[pt] : 'their rank'} in everyone else's games. Rows under ten games are faded.`,
    tableWrap('<thead><tr><th>Class</th><th>Champions</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">' + (pt != null ? TIERS[pt] : 'Class') + ' average</th><th class="num">Difference</th><th class="num">Avg game score</th></tr></thead><tbody>' +
      cls.map(c => { const wr = 100 * c[3] / c[2], d = c[4] == null ? null : wr - c[4];
        return `<tr class="${c[2] < LOW ? 'thin' : ''}"><td class="strong">${esc(c[0])}</td><td class="muted">${c[1].map(x => esc(C(x).n)).join(', ')}</td><td class="num">${c[2]}</td>` +
          `<td class="num strong">${pc1(wr)}</td><td class="num muted">${pc1(c[4])}</td><td class="num ${gcls(d)}">${d == null ? '-' : signed(d, ' pts')}</td><td class="num">${c[5] == null ? '-' : c[5]}</td></tr>`; }).join('') + '</tbody>') +
    (best.length >= 2 ? `<p class="muted small" style="margin-top:10px">${esc(label)} is strongest on ${esc(classPlural(best[0][1]))} (${signed(best[0][0], ' pts')}) and weakest on ${esc(classPlural(best[best.length - 1][1]))} (${signed(best[best.length - 1][0], ' pts')}).</p>` : ''));
  out += learnCard(label, role);
  return out;
}

/* ---- Roaming ---- */
function profRoaming(label) {
  const PL = D.players[label];
  if (!PL) return empty('No stored games yet.');
  const roles = ROLES.filter(r => PL.roles[r]), role = roles.includes(S.role) ? S.role : roles.includes(PL.main) ? PL.main : roles[0];
  if (!role) return empty('No role with three stored games yet.');
  const P = PL.roles[role], R = P.roam, X = P.roamX || {}, ref = refName(P.refTier, role);
  const rolePills = `<div class="pillrow"><div class="pills"><span class="pill-label">Role</span>${roles.map(r => pill(`${ricon(r)}${RN[r]} · ${PL.roles[r].games}`, r === role, set({ role: r }), ' sm')).join('')}</div></div>`;
  /* where they play, the same map as the site's players view */
  const h = P.heat, ph = UI.hphase, phs = ph === 'all' ? [0, 1, 2] : [Number(ph)];
  const flat = k => phs.reduce((a, p) => a.concat(h[k][p]), []);
  const phases = [['0', 'Laning 0–15'], ['1', 'Mid 15–25'], ['2', 'Late 25+'], ['all', 'All']].map(m => pill(m[1], ph === m[0], ui({ hphase: m[0] }), ' sm')).join('');
  const map = `<section class="card"><h2>Where ${esc(label)} plays</h2><div class="pills" style="margin:12px 0 8px">${layerPills('hl', UI.hl)}</div>` +
    `<div class="pills" style="margin-bottom:12px">${phases}</div><div class="mapwrap">${mapSvg(layerDraw(UI.hl, flat, heatLayer(h, ph)))}</div>` +
    `<div class="legend">${layerLegend(UI.hl, 'time spent')}<span class="muted">shown as blue side</span></div></section>`;
  if (role === 'JUNGLE') {
    return rolePills + `<div class="grid g-2-3">${map}${roamCard(label, role, R, ref)}</div>` + (P.jungle ? jungleSection(label, P.jungle) : '');
  }
  if (!R) return rolePills + `<div class="grid g-2-3">${map}${card('Roaming', '', '<div class="empty">Not enough early takedowns stored yet.</div>')}</div>`;
  const sp = R.split, up = (a, b) => a == null || b == null ? '' : `<span class="${a >= b ? 'pos' : 'neg'}">${a >= b ? '▲' : '▼'} ${esc(ref)} ${Math.round(b)}%</span>`;
  const tiles = '<div class="tiles">' +
    tile('Roam takedown share', R.roamShare == null ? '-' : Math.round(R.roamShare) + '%', up(R.roamShare, R.refRoam)) +
    tile(role === 'UTILITY' ? 'Time out of lane (ADC still bot)' : 'Time out of lane', R.outLane == null ? '-' : Math.round(R.outLane) + '%', up(R.outLane, R.refOut)) +
    (sp ? tile('Winrate, high-roam games', `<span class="${sp.high.wr >= 50 ? 'pos' : 'neg'}">${pc0(sp.high.wr)}</span>`, `${sp.high.games} games · low-roam ${pc0(sp.low.wr)} (${sp.low.games})`) : '') +
    (X.ts && X.ts[0] != null ? tile('Team gold share @15', signed(100 * (X.ts[0] - X.ts[1]), ' pts'), "team's share of all gold, high-roam against low-roam games") : '') +
    (X.dead ? tile('Roams that end in a death', X.dead[0] == null ? '-' : Math.round(X.dead[0]) + '%', X.dead[1] == null ? '' : `${esc(ref)} ${Math.round(X.dead[1])}% · died within 30s of the takedown`) : '') + '</div>';
  const where = card('Where takedowns happen', 'Laning phase, 0–15 min. Point at River or Jungle for the split.',
    `<h3>${esc(label)}</h3>${zoneBar(R.bar, ref)}<h3>${esc(ref)}</h3>${zoneBar(R.bar, ref, 'ref')}${zoneLegend(R.bar)}`);
  let pay = '';
  if (sp) {
    const g = v => `<td class="num strong ${gcls(v)}">${gold(v)}</td>`, s = v => `<td class="num">${v == null ? '-' : (100 * v).toFixed(1) + '%'}</td>`;
    pay = card('Does roaming pay off?', 'High-roam games (the top half of roam share) against low-roam games. Gold diff at 15 for every lane, and each lane\'s share of its team\'s gold.',
      tableWrap('<thead><tr><th>Lane</th><th class="num">Gold @15 high-roam</th><th class="num">Gold @15 low-roam</th><th class="num">Gold share high</th><th class="num">Gold share low</th></tr></thead><tbody>' +
        ROLES.map(r => `<tr><td>${ricon(r)} ${RN[r]}${r === role ? ` <span class="muted">(${esc(label)})</span>` : ''}</td>${g(sp.high.lanes[r])}${g(sp.low.lanes[r])}` +
          `${s(((X.gs || {})[r] || [])[0])}${s(((X.gs || {})[r] || [])[1])}</tr>`).join('') +
        `<tr><td class="strong">Winrate</td><td class="num strong ${sp.high.wr >= 50 ? 'pos' : ''}">${pc0(sp.high.wr)}</td><td class="num strong">${pc0(sp.low.wr)}</td>` +
        `<td class="num strong">${X.ts ? (100 * X.ts[0]).toFixed(1) + '%' : '-'}</td><td class="num">${X.ts ? (100 * X.ts[1]).toFixed(1) + '%' : '-'}</td></tr></tbody>`) +
      '<p class="muted small" style="margin-top:10px">The last row is the team\'s share of all the gold in the game. These are patterns, not proof of cause.</p>');
  }
  const byChamp = card('Roaming by champion', 'Roam takedown share and winrate on each champion with ten or more games.',
    (X.byChamp || []).length ? tableWrap('<thead><tr><th>Champion</th><th class="num">Games</th><th style="min-width:180px">Roam share</th><th class="num">Winrate</th></tr></thead><tbody>' +
      X.byChamp.map(c => `<tr><td>${champ(c[0])}</td><td class="num">${c[1]}</td><td><div class="wrrow" style="margin:0;grid-template-columns:1fr 50px"><div class="wrbar"><i style="width:${Math.min(100, 100 * (c[2] || 0))}%;background:#8b5cf6"></i></div><b>${c[2] == null ? '-' : Math.round(100 * c[2]) + '%'}</b></div></td><td class="num">${pc1(c[3])}</td></tr>`).join('') + '</tbody>')
      : '<div class="empty">No champion with ten games in this role.</div>');
  const T = X.timing, labs = ['3–6 min', '6–9 min', '9–12 min', '12–15 min'];
  let timing = '<div class="empty">No roams recorded.</div>';
  if (T) {
    const W = 520, H = 230, base = 190, bw = 100, gap = (W - 4 * bw) / 5, top = Math.max(...T, 1);
    timing = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="When roams happen">` + T.map((v, i) => {
      const x = gap + i * (bw + gap), hgt = Math.max(4, (v / top) * (base - 40));
      return `<rect x="${x}" y="${base - hgt}" width="${bw}" height="${hgt}" rx="6" fill="#8b5cf6"/><text class="lbl" x="${x + bw / 2}" y="${base - hgt - 8}" text-anchor="middle" style="font-size:13px;fill:#f2f4f8">${Math.round(v)}%</text>` +
        `<text class="lbl" x="${x + bw / 2}" y="${base + 20}" text-anchor="middle">${labs[i]}</text>`;
    }).join('') + `<line x1="0" x2="${W}" y1="${base}" y2="${base}" class="axis"/></svg>`;
    const peak = T.indexOf(Math.max(...T));
    timing += `<p class="muted small">Most of ${esc(label)}'s roams come at ${labs[peak]}.</p>`;
  }
  return rolePills + tiles + `<div class="grid g-2-3">${map}<div class="stack">${where}${pay}</div></div>` +
    `<div class="grid g2">${byChamp}${card(`When ${esc(label)} roams`, 'Share of roam takedowns in each part of the laning phase.', timing)}</div>`;
}

/* ---- Duos & stacks ---- */
function profDuos(label) {
  const prof = D.profiles[label] || {}, W = prof.with || [];
  const best = W.filter(w => w[2] >= LOW && w[4] >= LOW).map(w => [100 * w[3] / w[2] - 100 * w[5] / w[4], w[0]]).sort((a, b) => b[0] - a[0]);
  const withCard = card(`${esc(label)} with each friend`, `Ranked games on the same team. "Without" is that friend's winrate in games ${esc(label)} wasn't in.`,
    W.length ? tableWrap('<thead><tr><th>Friend</th><th>Usual role</th><th class="num">Together</th><th class="num">Winrate</th><th class="num">Without</th><th style="min-width:150px">Difference</th></tr></thead><tbody>' +
      W.map(w => { const t = 100 * w[3] / w[2], o = w[4] ? 100 * w[5] / w[4] : null, d = o == null ? null : t - o;
        return `<tr class="${w[2] < LOW ? 'thin' : ''} click" ${openP(w[0], 'duos')}><td>${who(w[0])}</td><td class="muted">${w[1].map(r => RN[r]).join(' / ')}</td><td class="num">${w[2]}</td>` +
          `<td class="num strong">${pc1(t)}</td><td class="num muted">${pc1(o)}</td><td>${d == null ? '-' : `<div class="diffbar"><i style="${d >= 0 ? 'left:50%' : 'right:50%'};width:${Math.min(50, Math.abs(d) * 2)}%;background:${d >= 0 ? '#22c55e' : '#ef4444'}"></i><em></em></div>`}</td></tr>`; }).join('') + '</tbody>')
      + (best.length ? `<p class="muted small" style="margin-top:10px">${esc(label)} + ${esc(best[0][1])} is the strongest regular pairing (${signed(best[0][0], ' pts')}). Rows under ten games are faded.</p>` : '')
      : '<div class="empty">No games with a friend on the team yet.</div>');
  const sizes = ['Solo', 'Duo', 'Trio', 'Four', 'Five'];
  const stacks = card(`${esc(label)} by stack size`, `How many tracked accounts were on ${esc(label)}'s team.`,
    (prof.stacks || []).map((v, i) => {
      if (!v[0]) return `<div class="stackrow"><span>${sizes[i]}</span><div class="track"><em></em></div><span class="num muted">-</span><span class="num muted small">0 games</span></div>`;
      const wr = 100 * v[1] / v[0];
      return `<div class="stackrow${v[0] < LOW ? ' thin' : ''}"><span>${sizes[i]}</span><div class="track"><i style="width:${wr.toFixed(1)}%;background:${heat(wr, 50, 8)}"></i><em></em></div>` +
        `<span class="num">${wr.toFixed(1)}%</span><span class="num muted small">${v[0]} games</span></div>`;
    }).join('') + '<p class="muted small" style="margin-top:10px">Dashed line is 50%.</p>');
  return `<div class="grid g-3-2">${withCard}${stacks}</div>` + duoPartners(label);
}

/* ---- Game flow and records ---- */
function recordsFor(label) {
  const out = [];
  D.records.season.forEach(c => { const k = (c.top || []).indexOf(label); if (c.who === label || k >= 0) out.push({ icon: c.icon, title: c.title, text: c.text, place: c.who === label ? 0 : k, why: c.why }); });
  D.records.game.forEach(c => {
    const k = (c.how || []).findIndex(r => Array.isArray(r) && r[0] === label);
    if (c.who === label || (k >= 0 && k < 3)) out.push({ icon: c.icon, title: c.title, text: c.text, place: c.who === label ? 0 : k, game: c.game });
  });
  D.bests.forEach(b => { const k = b.top.findIndex(t => t[0] === label);
    if (k >= 0) { const t = b.top[k]; out.push({ icon: b.icon, title: b.title, place: k, game: [t[2], t[3]],
      text: `${esc(b.desc)}: <b>${typeof t[1] === 'number' ? Math.round(t[1]).toLocaleString('en-GB') : esc(t[1])}</b> on ${esc(C(t[4]).n)}, ${DS.format(new Date(t[5]))}${k ? ` · group #${k + 1}` : ''}.` }); } });
  return out.sort((a, b) => a.place - b.place);
}
const recordCard = r => `<div class="award" style="--stripe:${r.place === 0 ? 'var(--warn)' : 'var(--violet)'}"><div class="award-icon">${r.icon}</div><div class="award-body">` +
  `<div class="award-title">${esc(r.title)}${r.place > 0 ? ` <span class="tag low">#${r.place + 1}</span>` : ''}</div><div class="award-text">${r.text}</div>` +
  (r.game ? `<button type="button" class="linkbtn" ${set({ tab: 'game', game: r.game[0], team: r.game[1], p: '' })}>Open this game →</button>` : '') + (r.why || '') + '</div></div>';
function profFlow(label) {
  const F = D.flow, me = F.players.find(p => p.label === label), sp = F.spill.findIndex(s => s.label === label), prof = D.profiles[label] || {};
  const t = F.tiles;
  let out = '<div class="tiles">' +
    (me ? tile('Lead conversion', pc0(me.conv), `${me.ahead} games ahead 2k+ at 15 · group ${pc0(t.conv)}`) +
      tile('Comebacks', `<span class="pos">${me.comebacks}</span>`, 'won from 5k+ behind') + tile('Throws', `<span class="neg">${me.throws}</span>`, 'lost from 5k+ ahead') +
      tile('Game flow score', signed(me.flow), 'wins above expected per 10 games') : tile('Game flow', '-', 'needs five games that reached 15 minutes')) +
    (sp >= 0 ? tile('Lane spillover', `<span class="${gcls(F.spill[sp].v)}">${gold(F.spill[sp].v)}</span>`, `other lanes' gold when ${esc(label)}'s lane is 1k+ ahead · group #${sp + 1}`) : '') + '</div>';
  const recs = recordsFor(label);
  out += `<div class="grid g-5-4">${storyCard(`${esc(label)}'s biggest comeback`, prof.comeback, true)}` +
    `<section class="card"><h2>Records<button type="button" class="pill sm" style="margin-left:auto" ${set({ pt: 'records' })}>Records tab →</button></h2>` +
    `<p class="hint">Records ${esc(label)} holds or is in the top three for.</p>` +
    (recs.length ? `<div class="awards two">${recs.slice(0, 6).map(recordCard).join('')}</div>` : '<div class="empty">None yet.</div>') + '</section></div>';
  return out;
}
function profRecords(label) {
  const recs = recordsFor(label);
  return card(`${esc(label)}'s records`, `Every season award and game record ${esc(label)} holds or is in the top three for. Gold stripe: held outright.`,
    recs.length ? `<div class="awards">${recs.map(recordCard).join('')}</div>` : '<div class="empty">None yet.</div>');
}

/* ---- the page ---- */
const PVIEWS = { overview: profileOverview, champions: profChampions, roles: profRoles, roaming: profRoaming, time: l => tabTime(l), duos: profDuos, flow: profFlow, records: profRecords };
function viewProfile() {
  const label = FR.includes(S.p) ? S.p : null;
  if (!label) return empty(`There is no player called ${esc(S.p)} on this page.`);
  const pt = PVIEWS[S.pt] ? S.pt : 'overview';
  return profileHead(label) + PVIEWS[pt](label);
}
