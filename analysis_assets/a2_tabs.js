/* ---- Players ------------------------------------------------------------------ */
const ZONE = { top: ['Top lane', '#e6b450'], mid: ['Mid', '#b08cff'], bot: ['Bot lane', '#4c8dff'], river: ['River', '#1fa5b3'], jungle: ['Jungle', '#2f9a5d'] };
const ZPART = { river_top: 'Top river', river_bot: 'Bot river', jungle_own: 'Own jungle', jungle_enemy: 'Enemy jungle' };
const ROLE_COL = { TOP: '#e6b450', JUNGLE: '#2f9a5d', MIDDLE: '#b08cff', BOTTOM: '#4c8dff', UTILITY: '#2ec4b6' };
const MODE_COL = { 'Ranked Solo': '#4c8dff', 'Ranked Duo': '#38bdf8', 'Ranked Solo/Duo': '#4c8dff', 'Ranked Flex': '#d6569c', 'Ranked 5s': '#e6b450' };
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
/* How one top-champions score was reached: the chain of multipliers, and the
   three things behind them. */
function scoreWorking(w, slug, role) {
  const s = w.score;
  if (!s) return '<div class="empty">None of these games could be scored yet.</div>';
  const box = (lab, big, sub, hi) => `<div class="swbox${hi ? ' hi' : ''}"><div class="lab">${lab}</div><div class="big">${big}</div><div class="sub">${sub}</div></div>`;
  const times = (v, lab) => `<div class="swx"><b>× ${v}</b><span>${lab}</span></div>`;
  const spread = (s.ranks || []).map(r => `${esc(rankName([r[0], r[1]]))} ×${r[2]}`).join(' · ');
  const chain = `<div class="swchain">${box('Average game score', s.raw.toFixed(1), `${s.scored} scored games`)}${times(s.rankW.toFixed(3), 'average rank weight')}` +
    `${box('Rank-weighted', s.weighted.toFixed(1), 'each game at the rank it was played at')}${times(s.gamesMult.toFixed(2), 'games played')}` +
    `${box('Games-weighted', (s.weighted * s.gamesMult).toFixed(1), `0.5 + ${s.games} × 0.01 · full at ${SC.full}`)}${times(s.wrMult.toFixed(3), 'vs usual winrate')}` +
    `${box('Top champions score', s.score.toFixed(1), s.champWr == null ? 'no winrate to compare with yet' : `adjusted WR ${s.adjWr}% vs ${s.champWr}%`, true)}</div>`;
  /* Every rank these games were played at is marked, not just the commonest:
     the score multiplies each game by its own rank's weight. */
  const used = {};
  (s.ranks || []).forEach(r => { used[r[0] + '-' + r[1]] = r[2]; });
  const weights = `<div class="swcard"><h3>Rank weight</h3>${SC.weights.filter(r => TIERS.indexOf(r[0]) >= 2).map(r => {
    const t = TIERS.indexOf(r[0]);
    return `<div class="kv"><span>${r[0]}${r[1].length > 1 ? ' I–IV' : ''}</span><span>${r[1].map((v, i) => used[t + '-' + (r[1].length === 1 ? 1 : i + 1)] ? `<b style="color:${TCOL[t]}">${v.toFixed(2)}</b>` : v.toFixed(2)).join(' · ')}</span></div>`;
  }).join('')}${spread ? `<p class="muted small" style="margin-top:8px">These games: ${spread}. Each is weighted on its own, and ${s.rankW.toFixed(3)} is what that came to on average.</p>` : ''}</div>`;
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
