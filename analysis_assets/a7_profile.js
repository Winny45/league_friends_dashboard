/* ---- Player profiles ------------------------------------------------------------
   One page per player, opened from a name anywhere on the site: a header with
   their rank and what the next game should be worth, then the site's sections
   filtered to them. The Overview tab is the quick view, in the shape of the
   big stats sites: stats stacked down the left, games down the right. */

const REGION = { euw1: 'euw', eun1: 'eune', na1: 'na', kr: 'kr', br1: 'br', la1: 'lan', la2: 'las', oc1: 'oce', tr1: 'tr', ru: 'ru', jp1: 'jp' };
const accountsOf = label => (D.meta.friends.find(f => f.label === label) || {}).accounts || [label];

/* Every game a person played: one row of the game index each, with their own
   line out of it. */
function gamesOf(label) {
  const out = [];
  GAMES.forEach(g => { const f = g[6].find(x => x[0] === label); if (f) out.push([g, f]); });
  return out;
}
/* LP for each game, keyed by match id, across every login the person has. */
const LPMAP = {};
function lpFor(label) {
  if (!LPMAP[label]) {
    const m = {};
    accountsOf(label).forEach(a => Object.values(((D.acc[a] || {}).q) || {}).forEach(q => (q.seq || []).forEach(s => { m[s[0]] = s; })));
    LPMAP[label] = m;
  }
  return LPMAP[label];
}
function agoText(ms) {
  const mins = Math.max(0, ((D.meta.generatedAtMs || Date.now()) - ms) / 60000);
  if (mins < 60) return Math.round(mins) + 'm ago';
  if (mins < 24 * 60) return Math.round(mins / 60) + 'h ago';
  if (mins < 48 * 60) return 'Yesterday';
  return Math.round(mins / 1440) + ' days ago';
}
const qShort = q => ({ 420: 'Ranked Solo', 440: 'Ranked Flex', 710: 'Ranked 5s' }[q] || 'Ranked');
function ring(v, s = 46) {
  if (v == null) return `<span class="ring muted" style="width:${s}px;height:${s}px">-</span>`;
  const r = s / 2 - 3, c = 2 * Math.PI * r, k = Math.max(0, Math.min(1, v / 100));
  const colr = `rgb(${blend([255, 122, 122], [110, 231, 160], Math.max(0, Math.min(1, (v - 25) / 50)))})`;
  return `<svg class="ring" width="${s}" height="${s}" viewBox="0 0 ${s} ${s}" role="img" aria-label="Score ${Math.round(v)}">` +
    `<circle cx="${s / 2}" cy="${s / 2}" r="${r}" fill="none" stroke="#2a3040" stroke-width="3"/>` +
    `<circle cx="${s / 2}" cy="${s / 2}" r="${r}" fill="none" stroke="${colr}" stroke-width="3" stroke-dasharray="${(c * k).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 ${s / 2} ${s / 2})" stroke-linecap="round"/>` +
    `<text x="${s / 2}" y="${s / 2 + 5}" text-anchor="middle" style="fill:#f2f4f8;font-size:${s > 40 ? 15 : 12}px;font-weight:800">${Math.round(v)}</text></svg>`;
}

/* ---- the header ---------------------------------------------------------------- */
function profileHead(label) {
  const a = ACC(label), r = (a.ranked || {}).solo, pk = (a.peak || {}).solo, pr = predOf(label), PL = D.players[label] || {};
  const [name, tag] = String(a.riot || '').split('#');
  const region = REGION[D.meta.platform] || 'euw', slug = name ? encodeURIComponent(name) + '-' + encodeURIComponent(tag || '') : '';
  const mainRole = PL.main, mainChamp = mainRole && PL.roles && PL.roles[mainRole] ? PL.roles[mainRole].compare.champ : null;
  const links = slug ? [['op.gg', `https://www.op.gg/summoners/${region}/${slug}`], ['u.gg', `https://u.gg/lol/profile/${D.meta.platform}/${slug}/overview`],
    ['League of Graphs', `https://www.leagueofgraphs.com/summoner/${region}/${slug}`]] : [];
  const acc = accountsOf(label);
  let mmr = '';
  if (pr) {
    const gap = pr.win - Math.abs(pr.loss);
    const where = gap > 2 ? 'above rank' : gap < -2 ? 'below rank' : 'around rank';
    mmr = `<div class="pred-note"><b>MMR ${where}</b><span>${signed(gap)} LP gap · approximate</span><span>${pr.est ? 'older estimate' : `last ${Math.min(15, pr.nw)}W / ${Math.min(15, pr.nl)}L measured`}</span></div>`;
  }
  const ranked = r ? `<div class="rankcard">${crest(r[0], 58)}<div><div class="rk-big" style="color:${TCOL[r[0]]}">${esc(rankLp(r))}</div>` +
    `<div class="muted small">Ranked Solo/Duo · ${r[3]}W ${r[4]}L · ${pc1(100 * r[3] / Math.max(1, r[3] + r[4]))}</div>` +
    (pk ? `<div class="muted small">Peak ${esc(rankLp(pk))}</div>` : '') + '</div></div>' : `<div class="rankcard">${crest(null, 58)}<div class="rk-big muted">Unranked in Solo/Duo</div></div>`;
  const predict = `<div class="predcard"><div class="muted small">Predicted next game</div>` +
    (pr ? `<div class="pred-row"><div><b class="pos">${signedInt(pr.win)}</b><span>win</span></div><div><b class="neg">${signedInt(pr.loss)}</b><span>loss</span></div>${mmr}</div>`
      : '<div class="muted" style="margin-top:8px">Not enough measured games yet: it needs five wins and five losses that each had a rank reading on both sides.</div>') + '</div>';
  const pt = PTABS.some(t => t[0] === S.pt) ? S.pt : 'overview';
  return `<section class="card phead"><div class="phead-top"><div class="pid"><span class="pav" data-av-edit="${esc(label)}" role="button" tabindex="0" title="Change ${esc(label)}'s icon">` +
    `${av(label, 96)}<i class="pen">✎</i>${a.level ? `<span class="lvl">${a.level}</span>` : ''}</span><div>` +
    `<div class="pname"><h2 style="color:${col(label)}">${esc(label)}</h2><span class="muted">${esc(a.riot || '')}</span></div>` +
    `<div class="pills" style="margin-top:10px">${mainRole ? `<span class="pill sm still">Main: ${esc(RN[mainRole])}${mainChamp ? ' · ' + esc(C(mainChamp).n) : ''}</span>` : ''}` +
    links.map(l => `<a class="pill sm" href="${esc(l[1])}" target="_blank" rel="noopener">${esc(l[0])} ↗</a>`).join('') +
    (acc.length > 1 ? `<span class="pill sm still" title="Games from every account are counted">Accounts: ${acc.map(esc).join(', ')}</span>` : '') +
    `</div></div></div><div class="pright">${ranked}${predict}</div></div>` +
    `<nav class="subtabs">${PTABS.map(t => `<button type="button" class="ptab${t[0] === pt ? ' on' : ''}" ${set({ pt: t[0] })}>${t[1]}</button>`).join('')}</nav></section>`;
}

/* ---- the left column ------------------------------------------------------------ */
function rankedPanel(label) {
  const a = ACC(label), R = a.ranked || {};
  const rows = ['solo', 'flex', 'fives'].filter(k => R[k]).map(k => {
    const r = R[k], g = r[3] + r[4], wr = g ? 100 * r[3] / g : 0;
    return `<div class="rq"><div class="rq-h"><b>${QNAME[k]}</b><span style="color:${TCOL[r[0]]}">${crest(r[0], 18)} ${esc(rankLp(r))}</span></div>` +
      `<div class="rq-b"><div class="bar"><i style="width:${wr}%;background:${MODE_COL['Ranked ' + (k === 'solo' ? 'Solo' : k === 'flex' ? 'Flex' : '5s')] || '#4c8dff'}"></i></div>` +
      `<b>${pc1(wr)}</b><span class="muted small">${r[3]}W ${r[4]}L</span></div></div>`;
  }).join('');
  return card('Ranked', '', rows || '<div class="empty">Not ranked this season.</div>');
}
function radarPanel(label) {
  const PL = D.players[label], role = PL && PL.main, P = role && PL.roles[role];
  if (!P) return '';
  const tiers = Object.keys(P.radar.ranks).map(Number), mine = P.tier;
  const shown = UI.prt != null ? UI.prt : (tiers.includes(mine) ? [mine] : tiers.slice(0, 1));
  const series = tiers.filter(t => shown.includes(t)).map(t => ({ vals: P.radar.ranks[t], color: TCOL[t], width: 1.8 }));
  series.push({ vals: P.radar.me, color: col(label), fill: true, width: 2.4 });
  const pills = tiers.map(t => `<button type="button" class="pill sm${shown.includes(t) ? ' ton' : ''}" style="--tc:${TCOL[t]}" ` +
    `${ui({ prt: shown.includes(t) ? shown.filter(x => x !== t) : shown.concat([t]) })}>${TSHORT[t]}</button>`).join('');
  const list = P.tiles.map(t => `<div class="statrow"><span>${esc(STAT[t.k].label)}</span><b>${stat(t.k, t.v)}</b>${pcbar(t.pc)}</div>`).join('');
  return card(`${RN[role]} · most played`, `Percentile among all ${RLS[role]}. Lines are the average at each rank; the percentiles below are at ${mine != null ? TIERS[mine] : 'their rank'}.`,
    `<div class="pills">${pills}</div>` + radar(P.radar.axes.map(statName), series, { label: `${label} radar`, w: 360, h: 300, r: 96 }) + `<div class="statlist">${list}</div>`);
}
function modesPanel(label) {
  const PL = D.players[label];
  if (!PL) return '';
  const total = PL.modes.reduce((s, m) => s + m[1], 0);
  const parts = PL.modes.map(m => [m[0].replace('Ranked ', ''), m[1], MODE_COL[m[0]] || '#788296', m[2]]);
  return card('Games by mode', 'This season. Duo is another tracked account on the team.',
    `<div class="drow">${donut(parts, total, 'games')}<div class="dlegend">${parts.map(p => `<div><i class="sw" style="background:${p[2]}"></i>${esc(p[0])}<b>${p[1]}</b><span class="muted small">${pc1(100 * p[3] / p[1])}</span></div>`).join('')}</div></div>`);
}
function rolesPanel(label) {
  const PL = D.players[label];
  if (!PL || !PL.positions.length) return '';
  const total = PL.positions.reduce((s, p) => s + p[1], 0) || 1;
  const parts = PL.positions.map(p => [RN[p[0]], p[1], ROLE_COL[p[0]], p[2]]);
  return card('Roles', '', `<div class="drow">${donut(parts, Math.round(100 * parts[0][1] / total) + '%', parts[0][0].toLowerCase())}` +
    `<div class="dlegend">${parts.map(p => `<div><i class="sw" style="background:${p[2]}"></i>${esc(p[0])}<b>${p[1]}</b><span class="muted small">${pc1(100 * p[3] / p[1])}</span></div>`).join('')}</div></div>`);
}
function lobbyPanel(label) {
  const PL = D.players[label];
  if (!PL || !PL.byRank.length) return '';
  const most = Math.max(...PL.byRank.map(r => r[1]));
  return card('By lobby rank', 'Average rank of the other nine players.',
    PL.byRank.map(r => `<div class="lr${r[1] < LOW ? ' thin' : ''}"><div class="lr-h">${tierText(r[0])}<span><b>${pc1(100 * r[2] / r[1])}</b> <span class="muted small">· ${r[1]} games</span></span></div>` +
      `<div class="bar thick"><i style="width:${100 * r[2] / r[1]}%;background:${TCOL[r[0]]}"></i></div><div class="bar thin"><i style="width:${100 * r[1] / most}%;background:#56607a"></i></div></div>`).join('') +
    '<p class="muted small" style="margin-top:8px">Thick bar is winrate, thin bar is games played.</p>');
}
function mmrPanel(label) {
  const a = ACC(label), qs = ['solo', 'flex', 'fives'].filter(k => ((a.q || {})[k] || {}).mmr);
  if (!qs.length) return '';
  const q = qs.includes(UI.mq) ? UI.mq : qs[0], M = a.q[q].mmr, s = M.season || {}, r = M.recent || {};
  const cell = (blk, k) => {
    if (!blk) return '<td class="num muted">-</td>';
    const v = blk[k];
    if (k === 'win') return `<td class="num pos">${v == null ? '-' : '+' + v.toFixed(1)}<small class="muted"> (${blk.nw})</small></td>`;
    if (k === 'loss') return `<td class="num neg">${v == null ? '-' : '−' + v.toFixed(1)}<small class="muted"> (${blk.nl})</small></td>`;
    if (k === 'gap') return `<td class="num ${gcls(v)}">${v == null ? '-' : signed(v)}</td>`;
    if (k === 'vs') { const g = blk.gap; return `<td class="num ${gcls(g)}">${g == null ? '-' : g > 2 ? 'above' : g < -2 ? 'below' : 'at rank'}</td>`; }
    if (k === 'wr') return `<td class="num">${pc1(v)}</td>`;
    return `<td class="num ${gcls(v)}">${signedInt(v)}</td>`;
  };
  const row = (lab, k) => `<tr><td>${lab}</td>${cell(s, k)}${cell(r, k)}</tr>`;
  const note = s.gap != null && r.gap != null ? (r.gap - s.gap > 1.5 ? 'The gap has grown over the last fifty games, so LP gains should be picking up.'
    : s.gap - r.gap > 1.5 ? 'The gap has shrunk over the last fifty games, so LP gains are likely to slow.' : 'Much the same over the last fifty games as over the season.') : '';
  return card('MMR', 'From LP per measured game. Approximate: Riot does not publish how LP maps to MMR.',
    `<div class="pills" style="margin-bottom:8px">${qs.map(k => pill(QNAME[k], k === q, ui({ mq: k }), ' sm')).join('')}</div>` +
    `<table class="tbl"><thead><tr><th></th><th class="num">Season</th><th class="num">Last 50</th></tr></thead><tbody>` +
    row('LP per win', 'win') + row('LP per loss', 'loss') + row('Gap', 'gap') + row('MMR vs rank', 'vs') + row('Winrate', 'wr') + row('Net LP', 'net') +
    `</tbody></table><p class="muted small" style="margin-top:8px">The number in brackets is how many games were measured on their own, with a rank reading straight before and after. ${note}</p>`);
}

/* ---- the game list ----------------------------------------------------------------- */
function filterGames(label) {
  let list = gamesOf(label);
  if (S.pq && QNAME[S.pq]) list = list.filter(([g]) => QKEY[g[3]] === S.pq);
  if (S.pc) list = list.filter(([, f]) => f[1] === S.pc);
  if (S.pr) list = list.filter(([, f]) => f[2] === S.pr);
  return list;
}
function summaryPanel(label, list) {
  const last = list.slice(0, 20);
  if (!last.length) return '';
  const w = last.filter(([g]) => g[5]).length, l = last.length - w;
  const avg = i => last.reduce((s, [, f]) => s + (f[i] || 0), 0) / last.length;
  const k = avg(3), d = avg(4), a = avg(5), kp = last.filter(([, f]) => f[12] != null), sc = last.filter(([, f]) => f[7] != null);
  const champs = {};
  last.forEach(([g, f]) => { const c = champs[f[1]] || (champs[f[1]] = [0, 0, 0, 0, 0]); c[g[5] ? 0 : 1]++; c[2] += f[3]; c[3] += f[4]; c[4] += f[5]; });
  const top = Object.entries(champs).sort((x, y) => (y[1][0] + y[1][1]) - (x[1][0] + x[1][1])).slice(0, 3);
  const lp = lpFor(label), deltas = last.slice().reverse().map(([g]) => (lp[g[0]] || [])[1]).filter(v => v != null);
  let run = 0;
  const pts = [0].concat(deltas.map(v => (run += v)));
  return `<section class="card psum"><div class="ps-a">${donut([['Wins', w, '#4c8dff'], ['Losses', l, '#ef5350']], Math.round(100 * w / last.length) + '%', `${w}W ${l}L`)}` +
    `<div><div class="muted small">Last ${last.length} games</div><div class="ps-kda">${k.toFixed(1)} / ${d.toFixed(1)} / ${a.toFixed(1)}</div>` +
    `<div class="small"><b class="pos">${((k + a) / Math.max(1, d)).toFixed(2)}</b> KDA · KP <b>${kp.length ? Math.round(kp.reduce((s, [, f]) => s + f[12], 0) / kp.length) : '-'}%</b>` +
    ` · avg score <b>${sc.length ? Math.round(sc.reduce((s, [, f]) => s + f[7], 0) / sc.length) : '-'}</b></div></div></div>` +
    `<div class="ps-b"><div class="muted small">Champions (last ${last.length})</div>${top.map(([c, v]) => `<div class="ps-c">${cicon(c, 22)}<b>${esc(C(c).n)}</b>` +
      `<span class="muted small">${v[0]}W ${v[1]}L · ${((v[2] + v[4]) / Math.max(1, v[3])).toFixed(1)} KDA</span></div>`).join('')}</div>` +
    `<div class="ps-c2"><div class="muted small">LP over the last ${last.length}</div>${pts.length > 2 ? spark(pts, '#22c55e') : '<div class="muted small">No LP recorded for these games.</div>'}` +
    `<div class="small">${pts.length > 1 ? `<b class="${gcls(run)}">${signedInt(run)} LP</b>` : ''}</div></div></section>`;
}
/* A player's name in a game: a friend by their label, anyone else by the name
   the game file gives once it has loaded, the champion until then. */
function lobbyName(G, champSlug) {
  if (!G) return null;
  const p = G.p.find(x => x.c === champSlug);
  return p ? (p.f && FR.includes(p.f) ? p.f : (p.n || '').split('#')[0]) : null;
}
function gameBar(label, g, f) {
  const lp = lpFor(label)[g[0]], doc = dayDocs[dayOf(g[1])], G = doc && doc[g[0]];
  const open = UI.pexp === g[0], win = g[5];
  const kda = ((f[3] + f[5]) / Math.max(1, f[4])).toFixed(2), mins = g[2] / 60;
  const lob = g[10] || [], ours = lob.slice(0, 5), theirs = lob.slice(5, 10);
  const pl = ci => {
    const slug = D.champIndex[ci];
    if (!slug) return '<div class="lp-p"></div>';
    const n = lobbyName(G, slug), fr = g[6].find(x => x[1] === slug);
    const nm = fr ? fn(fr[0]) : n ? `<span>${esc(n)}</span>` : `<span class="muted">${esc(C(slug).n)}</span>`;
    return `<div class="lp-p${fr && fr[0] === label ? ' me' : ''}">${cicon(slug, 16)}${nm}</div>`;
  };
  const it = f[13] || [];
  const lpCell = lp ? `<b class="${gcls(lp[1])}">${lp[2] ? '' : '≈'}${signedInt(lp[1])} LP</b>` +
    `<span class="muted small">${lp[3] != null ? 'pred ' + (win ? signedInt(lp[3]) : signedInt(lp[4])) : 'no prediction yet'}</span>` : '<span class="muted small">no LP</span>';
  return `<div class="gbar ${win ? 'w' : 'l'}${open ? ' open' : ''}"><div class="gb-row">` +
    `<div class="gb-meta"><b class="gb-q">${qShort(g[3])}</b><span class="muted small">${agoText(g[1] + g[2] * 1000)}</span><hr><b>${win ? 'Victory' : 'Defeat'}</b><span class="muted small">${mmss(g[2])}</span></div>` +
    `<div class="gb-champ"><span class="gb-ci">${cicon(f[1], 48, true)}${f[9] ? `<span class="lvl sm">${f[9]}</span>` : ''}</span>` +
    `<span class="gb-sr"><span>${sicon((f[14] || [])[0], 22)}${sicon((f[14] || [])[1], 22)}</span><span>${rnicon((f[15] || [])[0], 22)}${rnicon((f[15] || [])[2], 22, ' sub')}</span></span>` +
    `<span class="gb-cn muted small">${esc(C(f[1]).n)}</span></div>` +
    `<div class="gb-kda"><b>${f[3]} / <span class="neg">${f[4]}</span> / ${f[5]}</b><span class="small ${kda >= 3 ? 'pos' : kda < 1.5 ? 'neg' : 'muted'}">${kda} KDA</span></div>` +
    `<div class="gb-st small"><span>KP <b>${f[12] == null ? '-' : f[12] + '%'}</b></span><span>CS <b>${f[10] == null ? '-' : f[10]}</b> <span class="muted">(${f[10] == null ? '-' : (f[10] / mins).toFixed(1)})</span></span>` +
    `<span>Vision <b>${f[11] == null ? '-' : f[11]}</b></span><span>Lobby ${g[7] && g[7][0] != null ? tierText(g[7][0], rankName(g[7])) : '<span class="muted">-</span>'}</span></div>` +
    `<div class="gb-sc">${ring(f[7])}<span class="muted small">score</span></div>` +
    `<div class="gb-it"><span>${itemSlot(it[0])}${itemSlot(it[1])}${itemSlot(it[2])}${itemSlot(it[6])}</span><span>${itemSlot(it[3])}${itemSlot(it[4])}${itemSlot(it[5])}</span></div>` +
    `<div class="gb-lp">${lpCell}</div>` +
    `<div class="gb-pl"><div>${ours.map(pl).join('')}</div><div>${theirs.map(pl).join('')}</div></div>` +
    `<button type="button" class="gb-x" ${ui({ pexp: open ? null : g[0], pxt: 'overview' })} aria-label="${open ? 'Close' : 'Open'} this game">${open ? '▲' : '▼'}</button></div>` +
    (open ? gameExpand(label, g, f, G) : '') + '</div>';
}
function gameExpand(label, g, f, G) {
  if (!G) return '<div class="gx"><div class="empty">Loading this game…</div></div>';
  const team = g[4], P = G.p.map((p, i) => Object.assign({ pid: i + 1 }, p));
  const ours = P.filter(p => p.t === team).sort((a, b) => ROLES.indexOf(a.r) - ROLES.indexOf(b.r));
  const theirs = P.filter(p => p.t !== team).sort((a, b) => ROLES.indexOf(a.r) - ROLES.indexOf(b.r));
  const frames = P[0].g.length, at15 = frames - 2 >= 15;
  const sum = (list, m) => list.reduce((s, p) => s + (p.g[m] || 0), 0);
  const lead15 = at15 ? sum(ours, 15) - sum(theirs, 15) : null;
  const me = ours.find(p => p.c === f[1]), opp = me && theirs.find(p => p.r === me.r);
  const bot = r => (ours.find(p => p.r === r) || {}).g, ebot = r => (theirs.find(p => p.r === r) || {}).g;
  const botLead = at15 && bot('BOTTOM') && bot('UTILITY') && ebot('BOTTOM') && ebot('UTILITY')
    ? bot('BOTTOM')[15] + bot('UTILITY')[15] - ebot('BOTTOM')[15] - ebot('UTILITY')[15] : null;
  const objOurs = G.obj.filter(o => o[2] === team).length, objTheirs = G.obj.length - objOurs;
  const chance = at15 ? chanceAt(lead15, 15, g[9]) : null;
  const xt = UI.pxt || 'overview';
  const maxDmg = Math.max(1, ...P.map(p => p.dmg));
  const nameOf = p => p.f && FR.includes(p.f) ? fn(p.f) : `<span>${esc((p.n || '').split('#')[0] || C(p.c).n)}</span>`;
  const board = (list, blue) => `<thead><tr><th class="${blue ? 'pos' : 'neg'}">${(list[0] && list[0].t === G.win) ? 'Victory' : 'Defeat'} · ${list[0] && list[0].t === 100 ? 'Blue' : 'Red'}</th>` +
    '<th class="num">K/D/A</th><th>Damage</th><th class="num">CS</th><th class="num">Gold</th><th class="num">Vision</th></tr></thead><tbody>' +
    list.map(p => `<tr class="${p.c === f[1] ? 'me' : ''}"><td><span class="cell-champ">${cicon(p.c, 22)}${nameOf(p)}</span></td><td class="num">${p.k}/${p.d}/${p.a}</td>` +
      `<td><div class="dmg"><i style="width:${(100 * p.dmg / maxDmg).toFixed(0)}%;background:${p.t === team ? '#4c8dff' : '#ef5350'}"></i><span>${(p.dmg / 1000).toFixed(1)}k</span></div></td>` +
      `<td class="num">${p.cs}</td><td class="num">${(p.gold / 1000).toFixed(1)}k</td><td class="num">${p.vis}</td></tr>`).join('') + '</tbody>';
  let body;
  if (xt === 'laning') {
    body = tableWrap('<thead><tr><th>Lane</th><th>Matchup</th><th class="num">Gold @10</th><th class="num">Gold @15</th><th class="num">XP @15</th><th class="num">CS @15</th></tr></thead><tbody>' +
      ROLES.map(r => { const a = ours.find(p => p.r === r), b = theirs.find(p => p.r === r); if (!a || !b) return '';
        const gd = m => m <= frames - 2 ? a.g[m] - b.g[m] : null, d = (x, y) => x == null || y == null ? null : x - y;
        return `<tr><td>${ricon(r)} ${RN[r]}</td><td class="nowrap">${cicon(a.c, 20)} <span class="muted">vs</span> ${cicon(b.c, 20)}</td>` +
          `<td class="num ${gcls(gd(10))}">${gold(gd(10))}</td><td class="num ${gcls(gd(15))}">${gold(gd(15))}</td>` +
          `<td class="num ${gcls(d(a.x15, b.x15))}">${gold(d(a.x15, b.x15))}</td><td class="num">${signedInt(d(a.c15, b.c15))}</td></tr>`; }).join('') + '</tbody>');
  } else if (xt === 'objectives') {
    const lab = pid => { const p = P[pid - 1]; return p ? (p.f && FR.includes(p.f) ? fn(p.f) : esc(C(p.c).n)) : '-'; };
    body = G.obj.length ? `<div class="oblog">${G.obj.map(o => `<div class="row"><span class="muted">${mmss(o[0])}</span>${monBadge(o[1], monLetter(o[1]), o[2] === team)}` +
      `<div><b>${esc(MON[o[1]] || o[1])}${o[4] > 1 ? ' ×' + o[4] : ''}</b>${o[5] ? ' <span class="tag stolen">STOLEN</span>' : ''}` +
      `<div class="muted small">killer ${lab(o[3])} · assists ${o[6].length ? o[6].map(lab).join(', ') : 'none'}</div></div></div>`).join('')}</div>` : '<div class="empty">No epic monsters were taken.</div>';
  } else if (xt === 'builds') {
    const build = p => `<tr class="${p.c === f[1] ? 'me' : ''}"><td><span class="cell-champ">${cicon(p.c, 22)}${nameOf(p)}</span></td>` +
      `<td class="nowrap">${sicon((p.sp || [])[0], 20)}${sicon((p.sp || [])[1], 20)} ${rnicon((p.ru || [])[0], 20)}${rnicon((p.ru || [])[2], 20, ' sub')}</td>` +
      `<td class="nowrap">${(p.it || []).map(i => itemSlot(i, 22)).join('')}</td></tr>`;
    body = `<div class="grid g2" style="margin:0">${tableWrap('<tbody>' + ours.map(build).join('') + '</tbody>')}${tableWrap('<tbody>' + theirs.map(build).join('') + '</tbody>')}</div>` +
      ((P.some(p => p.sp)) ? '' : '<p class="muted small">Spells and runes appear once this game has been fetched again for them.</p>');
  } else {
    body = `<div class="grid g2" style="margin:0">${tableWrap(board(ours, team === 100), 'sb')}${tableWrap(board(theirs, team !== 100), 'sb')}</div>`;
  }
  const avgOn = (((D.usual[label] || {})[f[1] + '|' + f[2]]) || [0]);
  const w = rankWeight(f[8]);
  return `<div class="gx"><div class="gx-head"><div class="pills">${[['overview', 'Overview'], ['laning', 'Laning'], ['objectives', 'Objectives'], ['builds', 'Builds']]
    .map(t => pill(t[1], xt === t[0], ui({ pxt: t[0] }), ' sm')).join('')}</div>` +
    `<div class="gx-nums small"><span>Gold @15 <b class="${gcls(f[6])}">${gold(f[6])}</b></span><span>Bot lane @15 <b class="${gcls(botLead)}">${gold(botLead)}</b></span>` +
    `<span>Objectives <b>${objOurs} / ${objTheirs}</b></span><span>Win chance @15 <b>${chance == null ? '-' : Math.round(100 * chance) + '%'}</b></span></div></div>${body}` +
    `<div class="gx-foot"><span class="muted small">${f[7] != null ? `Game score ${Math.round(f[7])}` + (w ? ` · rank-weighted ${Math.round(Math.min(100, f[7] * w))}` : '') : 'No game score for this role'}` +
    `${avgOn[0] ? ` · ${esc(label)}'s ${esc(C(f[1]).n)} over ${avgOn[0]} games` : ''}</span>` +
    `<button type="button" class="pill sm on" ${set({ tab: 'game', game: g[0], team: g[4], p: '' })}>Open full game breakdown →</button></div></div>`;
}
/* Fetches the day files the visible games need, then redraws the list so the
   names fill in. Nothing waits on it: the bars are drawn straight away. */
function fillProfileGames(rows) {
  const need = [...new Set(rows.map(([g]) => dayOf(g[1])))].filter(d => !dayDocs[d]);
  if (!need.length) return;
  Promise.all(need.map(d => loadDay(d).catch(() => null))).then(() => {
    const host = document.getElementById('pgames');
    if (host && S.p && (S.pt || 'overview') === 'overview') host.innerHTML = profileGameList(S.p);
  });
}
function profileGameList(label) {
  const list = filterGames(label), n = UI.pn || 20, shown = list.slice(0, n);
  setTimeout(() => fillProfileGames(shown), 0);
  return (shown.length ? shown.map(([g, f]) => gameBar(label, g, f)).join('') : empty('No stored games match these filters.')) +
    (list.length > n ? `<div style="text-align:center;margin-top:12px"><button type="button" class="pill" ${ui({ pn: n + 20 })}>Show more games</button></div>` : '');
}
function profileOverview(label) {
  const all = gamesOf(label);
  const champs = {}, roles = {};
  all.forEach(([, f]) => { champs[f[1]] = (champs[f[1]] || 0) + 1; if (f[2]) roles[f[2]] = (roles[f[2]] || 0) + 1; });
  const qs = [['', 'All queues'], ['solo', 'Solo/Duo'], ['flex', 'Flex'], ['fives', '5s']];
  const filters = `<div class="pillrow" style="margin-bottom:12px"><div class="pills">${qs.map(q => pill(q[1], (S.pq || '') === q[0], set({ pq: q[0] }), ' sm')).join('')}</div>` +
    `<div class="pills"><select class="sel" data-pf="pc" aria-label="Champion"><option value="">Champion ▾</option>${Object.entries(champs).sort((a, b) => b[1] - a[1])
      .map(([c, n]) => `<option value="${esc(c)}"${S.pc === c ? ' selected' : ''}>${esc(C(c).n)} (${n})</option>`).join('')}</select>` +
    `<select class="sel" data-pf="pr" aria-label="Role"><option value="">Role ▾</option>${ROLES.filter(r => roles[r]).map(r => `<option value="${r}"${S.pr === r ? ' selected' : ''}>${RN[r]} (${roles[r]})</option>`).join('')}</select></div></div>`;
  const left = `<div class="pleft">${rankedPanel(label)}${radarPanel(label)}${modesPanel(label)}${rolesPanel(label)}${lobbyPanel(label)}${mmrPanel(label)}</div>`;
  const right = `<div class="pmain">${filters}${summaryPanel(label, filterGames(label))}<div id="pgames">${profileGameList(label)}</div></div>`;
  return `<div class="pgrid">${left}${right}</div>`;
}
