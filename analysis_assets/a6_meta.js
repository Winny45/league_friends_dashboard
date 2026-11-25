/* ---- Pick, ban and win rates, and the champions' meta chart -------------------------
   Every rate here comes from the stored lobbies: all ten players of every game
   the group played, not Riot's own statistics. A pick rate is the share of
   those games a champion was in; a ban rate is the share of games with bans
   recorded in which either team banned it. */

/* Rates for the games a filter lets through. pred(tier, patch) sees a cube
   row's tier (the player's) or a ban row's tier (the game's middle tier). */
function metaRates(pred) {
  let rows = 0;
  const per = new Map(), any = new Map();
  D.cube.forEach(c => {
    if (!pred(c[2], c[3])) return;
    rows += c[6];
    if (!c[6]) return;
    const k = c[0] + '|' + c[1], v = per.get(k) || [0, 0];
    v[0] += c[6]; v[1] += c[7]; per.set(k, v);
    const a = any.get(c[0]) || [0, 0];
    a[0] += c[6]; a[1] += c[7]; any.set(c[0], a);
  });
  const B = D.banc || { bans: [], games: [] }, bans = new Map();
  let bg = 0;
  B.games.forEach(r => { if (pred(r[0], r[1])) bg += r[2]; });
  B.bans.forEach(r => { if (pred(r[1], r[2])) bans.set(r[0], (bans.get(r[0]) || 0) + r[3]); });
  const games = rows / 10;
  return {
    games, banGames: bg,
    /* [games, wins] for a champion in one role (ri) or in any (ri < 0). */
    gw: (ci, ri) => (ri < 0 ? any.get(ci) : per.get(ci + '|' + ri)) || [0, 0],
    pick: n => games ? 100 * n / games : 0,
    ban: ci => bg >= 30 ? 100 * (bans.get(ci) || 0) / bg : null,
    each: ri => ri < 0 ? [...any.entries()].map(([ci, v]) => [ci, v[0], v[1]])
      : [...per.entries()].filter(([k]) => +k.split('|')[1] === ri).map(([k, v]) => [+k.split('|')[0], v[0], v[1]]),
  };
}
/* A winrate pulled toward a prior by k games' worth of it, so ten games at
   70% do not outrank three hundred at 54%. Fractions in, fraction out. */
const shrink = (w, g, prior = 0.5, k = 20) => (w + prior * k) / (g + k);

/* The rank and patch filters of the champions page, as a predicate. */
function champFilter() {
  const rk = S.crk || 'all', pi = S.cpt ? D.patches.indexOf(S.cpt) : -1;
  return (tier, patch) => (rk === 'all' || (rk === 'd' ? tier >= 6 : String(tier) === rk)) && (pi < 0 || patch === pi);
}

function metaChart() {
  const ri = S.cvr ? ROLES.indexOf(S.cvr) : -1, R = metaRates(champFilter());
  const minG = Math.max(15, Math.round(R.games / 120));
  const pts = R.each(ri).filter(p => p[1] >= minG).map(([ci, g, w]) => ({
    ci, slug: D.champIndex[ci], g, wr: 100 * shrink(w, g), raw: 100 * w / g, pick: R.pick(g), ban: R.ban(ci) }));
  const rolePills = `<span class="pill-label">Role</span>${pill('All', !S.cvr, set({ cvr: '' }), ' sm')}` +
    ROLES.map(r => pill(ricon(r) + RN[r], S.cvr === r, set({ cvr: r }), ' sm')).join('');
  if (pts.length < 8) return `<section class="card"><div class="filters">${rolePills}</div><div class="empty">Too few games under these filters to place champions.</div></section>`;
  const picks = pts.map(p => p.pick).sort((a, b) => a - b), med = picks[Math.floor(picks.length / 2)], q3 = picks[Math.floor(picks.length * 0.75)];
  const hasBans = pts.some(p => p.ban != null);

  /* Pick rate on a log scale: the field runs from a fraction of a percent to
     a quarter of all games, and a straight scale crushes the left of it. */
  const W = 980, H = 560, L = 54, Rm = 20, T = 20, Bm = 40;
  const lx0 = Math.log10(Math.max(0.05, picks[0] * 0.8)), lx1 = Math.log10(picks[picks.length - 1] * 1.25);
  const wrs = pts.map(p => p.wr), y0 = Math.min(44, Math.floor(Math.min(...wrs) - 1)), y1 = Math.max(56, Math.ceil(Math.max(...wrs) + 1));
  const x = v => L + (W - L - Rm) * (Math.log10(Math.max(v, 0.05)) - lx0) / (lx1 - lx0), y = v => T + (H - T - Bm) * (y1 - v) / (y1 - y0);
  let s = `<svg class="chart meta" viewBox="0 0 ${W} ${H}" role="img" aria-label="Winrate against pick rate">`;
  /* The four corners, shaded a little and named. */
  const mx = x(med), my = y(50);
  s += `<rect x="${L}" y="${T}" width="${mx - L}" height="${my - T}" fill="#2ecc71" fill-opacity=".06"/>` +
    `<rect x="${mx}" y="${my}" width="${W - Rm - mx}" height="${H - Bm - my}" fill="#ff5f5f" fill-opacity=".06"/>`;
  for (let v = Math.ceil(y0 / 2) * 2; v <= y1; v += 2)
    s += `<line x1="${L}" x2="${W - Rm}" y1="${y(v)}" y2="${y(v)}" class="axis"${v === 50 ? ' stroke="#56607a"' : ''}/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`;
  [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50].filter(v => Math.log10(v) >= lx0 && Math.log10(v) <= lx1).forEach(v => {
    s += `<line x1="${x(v)}" x2="${x(v)}" y1="${T}" y2="${H - Bm}" class="axis"/><text x="${x(v)}" y="${H - Bm + 16}" text-anchor="middle">${v}%</text>`; });
  s += `<line x1="${mx}" x2="${mx}" y1="${T}" y2="${H - Bm}" stroke="#56607a" stroke-dasharray="4 4"/>` +
    `<text x="${W - Rm}" y="${H - 6}" text-anchor="end">pick rate (share of games), log scale →</text>` +
    `<text x="${L + 6}" y="${T + 14}" class="qlab" style="fill:#6ee7a0">Hidden gems</text>` +
    `<text x="${W - Rm - 6}" y="${T + 14}" text-anchor="end" class="qlab">Strong and popular</text>` +
    `<text x="${W - Rm - 6}" y="${H - Bm - 8}" text-anchor="end" class="qlab" style="fill:#ff8a8a">Underachievers</text>` +
    `<text x="${L + 6}" y="${H - Bm - 8}" class="qlab">Niche</text>`;
  /* Most banned drawn last, so they sit on top. */
  pts.slice().sort((a, b) => (a.ban || 0) - (b.ban || 0)).forEach(p => {
    const r = 9 + Math.min(9, Math.sqrt(p.ban || 0) * 2.4), banCol = p.ban == null ? '#56607a' : `rgb(${blend([86, 96, 122], [255, 95, 95], Math.min(1, (p.ban || 0) / 25))})`;
    const cx = x(p.pick).toFixed(1), cy = y(p.wr).toFixed(1);
    s += `<g class="mpt" ${set({ tab: 'champions', champ: p.slug, crole: S.cvr || '', p: '' })}><title>${esc(C(p.slug).n)}: ${pc1(p.raw)} over ${p.g.toLocaleString('en-GB')} games (${pc1(p.wr)} adjusted), picked in ${pc1(p.pick)}` +
      `${p.ban != null ? `, banned in ${pc1(p.ban)}` : ''}</title>` +
      `<clipPath id="mc${p.ci}"><circle cx="${cx}" cy="${cy}" r="${r - 2}"/></clipPath>` +
      `<image href="${champUrl(p.slug)}" x="${(cx - r + 2).toFixed(1)}" y="${(cy - r + 2).toFixed(1)}" width="${2 * r - 4}" height="${2 * r - 4}" clip-path="url(#mc${p.ci})"/>` +
      `<circle cx="${cx}" cy="${cy}" r="${r - 1}" fill="none" stroke="${banCol}" stroke-width="2.5"/></g>`;
  });
  s += '</svg>';

  const gems = pts.filter(p => p.pick < med && p.wr >= 51.5 && p.g >= 2 * minG).sort((a, b) => b.wr - a.wr).slice(0, 8);
  const under = pts.filter(p => p.pick >= q3 && p.wr <= 49).sort((a, b) => a.wr - b.wr).slice(0, 8);
  const banned = hasBans ? pts.filter(p => p.ban != null).sort((a, b) => b.ban - a.ban).slice(0, 8) : [];
  const list = (title, hint, rows) => `<section class="card"><h2>${title}</h2><p class="hint">${hint}</p>` + (rows.length ? tableWrap(
    `<thead><tr><th>Champion</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">Pick</th>${hasBans ? '<th class="num">Ban</th>' : ''}</tr></thead><tbody>` +
    rows.map(p => `<tr class="click" ${set({ tab: 'champions', champ: p.slug, crole: S.cvr || '', p: '' })}><td>${champ(p.slug, 20)}</td><td class="num muted">${p.g.toLocaleString('en-GB')}</td>` +
      `<td class="num ${p.raw >= 52 ? 'pos' : p.raw <= 48 ? 'neg' : ''}">${pc1(p.raw)}</td><td class="num">${pc1(p.pick)}</td>${hasBans ? `<td class="num">${p.ban == null ? '-' : pc1(p.ban)}</td>` : ''}</tr>`).join('') + '</tbody>', 'tight')
    : '<div class="empty">None under these filters.</div>') + '</section>';
  return `<section class="card" style="margin-bottom:20px"><div class="filters">${rolePills}</div>` +
    `<p class="hint" style="margin-top:12px">Every champion with ${minG}+ games in the stored lobbies (all ten players of the group's games) under the filters above. ` +
    `Up is winrate, pulled a little toward 50% when the sample is small; right is how often it is picked. The dashed line is the middle pick rate. ` +
    `${hasBans ? 'A thicker, redder ring is banned more often.' : 'Ban rates appear as games are fetched again with their bans.'} Hover for the numbers, click for the champion.</p>` +
    `<div class="scroll">${s}</div></section>` +
    `<div class="grid ${hasBans ? 'g3' : 'g2'}">${list('💎 Hidden gems', 'Picked less than most and winning anyway: worth a look before everyone notices.', gems)}` +
    list('📉 Underachievers', 'In the busiest quarter by pick rate and still losing more than they win.', under) +
    (hasBans ? list('🚫 Ban magnets', 'Banned most often in these games: plan for them not being there.', banned) : '') + '</div>';
}
