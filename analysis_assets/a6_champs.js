/* ---- Champions --------------------------------------------------------------------
   The index is built in the browser from one compact table (D.cube) so its
   filters need no round trip. A champion's own page loads a small file of its
   own, the way a game's breakdown does. */

const CHAMP_DOCS = {}, CHAMP_WAIT = {};
function loadChamp(slug) {
  if (!CHAMP_WAIT[slug]) {
    CHAMP_WAIT[slug] = fetch('c/' + encodeURIComponent(slug) + '.json').then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(doc => { CHAMP_DOCS[slug] = doc; return doc; });
  }
  return CHAMP_WAIT[slug];
}
const wrClass = (wr, n) => n < LOW ? 'muted' : wr >= 52 ? 'pos' : wr <= 48 ? 'neg' : '';

/* Which rank tiers have enough games to be worth a filter of their own. */
function rankTiers() {
  const n = {};
  D.cube.forEach(c => { if (c[2] >= 0) n[c[2]] = (n[c[2]] || 0) + c[6]; });
  return Object.keys(n).map(Number).filter(t => t < 6 && n[t] >= 300).sort((a, b) => a - b);
}
function champIndexData() {
  const rk = S.crk || 'all', pt = S.cpt || '', all = S.cshow === 'all';
  const pi = pt ? D.patches.indexOf(pt) : -1;
  const sums = {};
  D.cube.forEach(c => {
    if (rk !== 'all' && (rk === 'd' ? c[2] < 6 : String(c[2]) !== rk)) return;
    if (pt && c[3] !== pi) return;
    const g = all ? c[6] : c[4], w = all ? c[7] : c[5];
    if (!g) return;
    const k = c[0] + '|' + c[1], s = sums[k] || (sums[k] = [c[0], c[1], 0, 0]);
    s[2] += g; s[3] += w;
  });
  return Object.values(sums);
}
/* How the lists are ordered: A-Z, most games, or best winrate. Under ten
   games a winrate is noise, so those go to the bottom of a winrate sort. */
const CSORT = { '': 'A–Z', games: 'Games', wr: 'Winrate' };
function champSort(list) {
  const name = r => C(D.champIndex[r[0]]).n;
  if (S.csort === 'games') return list.sort((a, b) => b[2] - a[2] || name(a).localeCompare(name(b)));
  if (S.csort === 'wr') return list.sort((a, b) => ((b[2] >= LOW) - (a[2] >= LOW)) || b[3] / b[2] - a[3] / a[2] || b[2] - a[2]);
  return list.sort((a, b) => name(a).localeCompare(name(b)));
}
const sortTh = (key, label, cls = 'num') => `<th class="${cls} sortable${(S.csort || '') === key ? ' on' : ''}" ${set({ csort: key })} title="Sort by ${label.toLowerCase()}">${label}${(S.csort || '') === key ? ' ▾' : ''}</th>`;
function champColumn(title, key, rows, roleOf, accent) {
  const q = (UI.cq || '').toLowerCase();
  const list = champSort(rows.filter(r => !q || C(D.champIndex[r[0]]).n.toLowerCase().includes(q)));
  if (!list.length) return '';
  const open = UI.cexp[key], n = 16, shown = open || q ? list : list.slice(0, n);
  return `<section class="card ccol"><h2 style="--acc:${accent}">${esc(title)}<span class="muted small" style="margin-left:auto;font-weight:500">${CSORT[S.csort || ''] || 'A–Z'}</span></h2>` +
    `<table class="tbl tight"><thead><tr>${sortTh('', 'Champion', '')}${sortTh('games', 'Games')}${sortTh('wr', 'WR')}</tr></thead><tbody>` +
    shown.map(r => { const slug = D.champIndex[r[0]], wr = 100 * r[3] / r[2];
      return `<tr class="click" ${set({ tab: 'champions', champ: slug, crole: roleOf(r) || '', p: '' })}><td>${champ(slug, 20)}</td><td class="num muted">${r[2].toLocaleString('en-GB')}</td>` +
        `<td class="num ${wrClass(wr, r[2])}">${pc1(wr)}</td></tr>`; }).join('') + '</tbody></table>' +
    (list.length > n && !q ? `<button type="button" class="linkbtn center" ${ui({ cexp: Object.assign({}, UI.cexp, { [key]: !open }) })}>${open ? 'Show fewer' : `Show all ${list.length}`}</button>` : '') + '</section>';
}
function champIndex() {
  const by = S.cg === 'class' ? 'class' : 'role', rk = S.crk || 'all', all = S.cshow === 'all';
  const tiers = rankTiers();
  const meta = S.cview === 'meta';
  const head = `<section class="card" style="margin-bottom:20px"><div class="filters">` +
    `<span class="pill-label">View</span>${pill('Lists', !meta, set({ cview: '' }), ' sm')}${pill('Pick vs win', meta, set({ cview: 'meta' }), ' sm')}` +
    (meta ? '' : `<input class="search" type="search" placeholder="Search a champion…" aria-label="Search a champion" value="${esc(UI.cq || '')}" data-cq>` +
    `<span class="pill-label">Group by</span>${pill('Role', by === 'role', set({ cg: '' }), ' sm')}${pill('Class', by === 'class', set({ cg: 'class' }), ' sm')}`) +
    `<span class="pill-label">Rank</span>${pill('All', rk === 'all', set({ crk: '' }), ' sm')}${tiers.map(t => `<button type="button" class="pill sm${String(t) === rk ? ' on' : ''}" style="${String(t) === rk ? '' : 'color:' + TCOL[t]}" ${set({ crk: String(t) })}>${TIERS[t]}</button>`).join('')}` +
    `${pill('Diamond+', rk === 'd', set({ crk: 'd' }), ' sm')}` +
    `<span class="pill-label">Patch</span><select class="sel" data-cpt aria-label="Patch"><option value="">Season</option>${D.patches.slice().reverse().map(p => `<option value="${esc(p)}"${S.cpt === p ? ' selected' : ''}>${esc(p)}</option>`).join('')}</select>` +
    (meta ? '' : `<span class="pill-label">Show</span>${pill('Group', !all, set({ cshow: '' }), ' sm')}${pill('All lobbies', all, set({ cshow: 'all' }), ' sm')}` +
    `<span class="pill-label">Sort</span>${Object.entries(CSORT).map(([k, l]) => pill(l, (S.csort || '') === k, set({ csort: k }), ' sm')).join('')}`) + '</div></section>';
  return head + (meta ? metaChart() : champIndexCols());
}
/* The lists alone, so typing in the search box redraws them without taking
   the cursor out of the box. */
function champIndexCols() {
  const by = S.cg === 'class' ? 'class' : 'role', all = S.cshow === 'all', rows = champIndexData();
  let cols;
  if (by === 'role') {
    cols = ROLES.map(r => { const ri = ROLES.indexOf(r); return champColumn(RN[r], 'r' + r, rows.filter(x => x[1] === ri), () => r, ROLE_COL[r]); });
  } else {
    const merged = {};
    rows.forEach(r => { const m = merged[r[0]] || (merged[r[0]] = [r[0], -1, 0, 0, {}]); m[2] += r[2]; m[3] += r[3]; m[4][r[1]] = (m[4][r[1]] || 0) + r[2]; });
    const mainRole = r => { const e = Object.entries(r[4]).sort((a, b) => b[1] - a[1])[0]; return e ? ROLES[e[0]] : ''; };
    cols = D.meta.classes.map(cls => champColumn(cls, 'c' + cls, Object.values(merged).filter(m => C(D.champIndex[m[0]]).c === cls), mainRole, '#8b6cf6'));
  }
  const body = cols.join('');
  return `<div id="ccols"><div class="ccols ${by}">${body || '<div class="empty">No champion matches.</div>'}</div>` +
    `<p class="muted small">${by === 'role' ? 'A champion played in two roles appears in both lists, with separate numbers.' : 'Grouped by wiki class; each champion appears once, with its numbers across every role.'} ` +
    `${all ? 'Every player in the stored games.' : 'The group\'s own games.'} Winrates under ten games are greyed. Click a champion for its page.</p></div>`;
}

function champDetail(slug) {
  const doc = CHAMP_DOCS[slug];
  if (!doc) {
    loadChamp(slug).then(() => { if (S.tab === 'champions' && S.champ === slug && !S.p) render(); }).catch(() => {
      const v = document.getElementById('view');
      if (v && S.champ === slug) v.innerHTML = empty(`No page for ${esc(C(slug).n)} yet: it needs five games in one role in the stored lobbies.`);
    });
    return empty(`Loading ${esc(C(slug).n)}…`);
  }
  const roles = Object.keys(doc.roles).sort((a, b) => doc.roles[b].all[0] - doc.roles[a].all[0]);
  const role = roles.includes(S.crole) ? S.crole : roles[0], X = doc.roles[role], cm = C(slug), rl = RLS[role];
  const overall = 100 * X.all[1] / X.all[0];
  const gwr = X.group[0] ? 100 * X.group[1] / X.group[0] : null;
  const patches = X.patch.filter(p => p[1] >= 10), cur = X.patch[X.patch.length - 1];
  const curWr = cur ? 100 * cur[2] / cur[1] : null;
  const bestP = X.patch.filter(p => p[1] >= 30).map(p => [p, 100 * p[2] / p[1]]).sort((a, b) => b[1] - a[1])[0];
  let out = `<section class="card" style="margin-bottom:20px"><div class="champ-head"><button type="button" class="pill sm" ${set({ champ: '', crole: '' })}>← All champions</button>` +
    `<div class="id">${cicon(slug, 64, true)}<div><h2>${esc(cm.n)} <span class="muted" style="font-size:18px">· ${esc(RN[role])}</span></h2><div class="chips">${classChips(slug)}</div></div></div>` +
    `<div class="pills">${roles.map(r => pill(`${ricon(r)}${RN[r]} · ${doc.roles[r].all[0].toLocaleString('en-GB')}`, r === role, set({ crole: r }), ' sm')).join('')}</div></div></section>`;
  out += '<div class="tiles">' +
    tile('Overall winrate', pc1(overall), `${X.all[0].toLocaleString('en-GB')} ${esc(cm.n)} ${rl} in the stored lobbies`) +
    (cur ? tile(`This patch (${esc(cur[0])})`, pc1(curWr), cur[1] < 30 ? `${cur[1]} games so far` : `<span class="${gcls(curWr - overall)}">${curWr >= overall ? '▲' : '▼'} ${signed(curWr - overall)} vs season</span>`) : '') +
    tile('Group winrate', gwr == null ? '-' : pc1(gwr), gwr == null ? 'nobody in the group plays it here' : `<span class="${gcls(gwr - overall)}">${gwr >= overall ? '▲' : '▼'} ${signed(gwr - overall)} vs overall</span> · ${X.group[0]} games`) +
    (bestP ? tile('Best patch', esc(bestP[0][0]), `${pc1(bestP[1])} overall${bestP[0][3] >= 5 ? ` · group ${pc0(100 * bestP[0][4] / bestP[0][3])}` : ''}`) : '') +
    tile('Pick rate in lobbies', X.pick == null ? '-' : X.pick.toFixed(1) + '%', `of ${rl}`) + '</div>';

  let chart = '<div class="empty">Needs ten games in two patches.</div>';
  if (patches.length >= 2) {
    const xs = patches.map((p, i) => i), all = patches.map((p, i) => [i, 100 * p[2] / p[1]]);
    const grp = patches.map((p, i) => [i, p[3] >= 5 ? 100 * p[4] / p[3] : null]);
    const vals = all.map(p => p[1]).concat(grp.map(p => p[1]).filter(v => v != null));
    const y0 = Math.floor((Math.min(...vals) - 3) / 5) * 5, y1 = Math.ceil((Math.max(...vals) + 3) / 5) * 5, yt = [];
    for (let v = y0; v <= y1; v += 5) yt.push(v);
    const step = Math.max(1, Math.ceil(patches.length / 10));
    chart = lineChart([{ pts: all, color: '#b08cff', width: 2.4, end: 'All' }, { pts: grp, color: '#4c8dff', dash: '6 5', width: 2, end: 'Group' }],
      { x0: 0, x1: xs.length - 1, y0, y1, xt: xs.filter(i => i % step === 0 || i === xs.length - 1), xf: i => patches[i][0], yt, yf: v => v + '%', r: 56, h: 320,
        dots: all.map(p => [p[0], p[1]]), label: 'Winrate by patch' }) +
      `<div class="legend"><span><i class="sw" style="background:#b08cff"></i>Everyone in the stored lobbies</span><span><i class="sw" style="background:#4c8dff"></i>The group (five games or more that patch)</span></div>` +
      '<p class="muted small">Patches with fewer than ten games are left out. Buffs and nerfs are not marked: there is no list of champion changes per patch for the site to read them from.</p>';
  }
  const cs = X.counters.map(c => [c[0], c[1], 100 * c[2] / c[1]]).sort((a, b) => (b[1] >= 30) - (a[1] >= 30) || (a[2] - overall) - (b[2] - overall)).slice(0, COUNTER_ROWS);
  const solid = cs.filter(c => c[1] >= 30);
  const counters = card('Counters', `Matchup winrate minus ${esc(cm.n)}'s overall ${pc1(overall)}. Negative means that champion counters ${esc(cm.n)}. Under thirty games: faded.`,
    cs.length ? tableWrap(`<thead><tr><th>Enemy ${RN[role].toLowerCase()}</th><th class="num">Games</th><th class="num">${esc(cm.n)} WR</th><th style="min-width:160px">vs overall</th></tr></thead><tbody>` +
      cs.map(c => { const d = c[2] - overall;
        return `<tr class="${c[1] < 30 ? 'thin' : ''} click" ${set({ champ: c[0], crole: role })}><td>${champ(c[0])}</td><td class="num">${c[1]}</td><td class="num">${pc1(c[2])}</td>` +
          `<td><div class="diffbar"><i style="${d >= 0 ? 'left:50%' : 'right:50%'};width:${Math.min(50, Math.abs(d) * 3)}%;background:${d >= 0 ? '#22c55e' : '#ef4444'}"></i><em></em></div><span class="small ${gcls(d)}">${signed(d, ' pts')}</span></td></tr>`; }).join('') + '</tbody>') +
      (solid.length >= 2 ? `<p class="muted small" style="margin-top:10px">Hardest: ${esc(C(solid[0][0]).n)} (${signed(solid[0][2] - overall)}). Easiest: ${esc(C(solid[solid.length - 1][0]).n)} (${signed(solid[solid.length - 1][2] - overall)}).</p>` : '')
      : '<div class="empty">No lane opponents recorded.</div>');
  out += `<div class="grid g-3-2">${card('Winrate by patch', `Every ${esc(cm.n)} ${rl.replace(/s$/, '')} in the stored lobbies, and the group's.`, chart)}${counters}</div>`;

  const byRank = card(`Average ${esc(cm.n)} ${rl.replace(/s$/, '')} by rank`, 'Every player in the stored lobbies.',
    X.byRank.length ? tableWrap('<thead><tr><th>Rank</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">CS/min</th><th class="num">Dmg share</th><th class="num">Gold @15</th><th class="num">Roam %</th></tr></thead><tbody>' +
      X.byRank.map(r => `<tr class="${r[1] < LOW ? 'thin' : ''}"><td>${tierText(r[0])}</td><td class="num">${r[1]}</td><td class="num">${pc1(100 * r[2] / r[1])}</td><td class="num">${r[3] == null ? '-' : r[3].toFixed(1)}</td>` +
        `<td class="num">${r[4] == null ? '-' : Math.round(100 * r[4]) + '%'}</td><td class="num ${gcls(r[5])}">${gold(r[5])}</td><td class="num">${r[6] == null ? '-' : Math.round(100 * r[6]) + '%'}</td></tr>`).join('') + '</tbody>')
      : '<div class="empty">Not enough games at any rank.</div>');
  /* The file names accounts; on the merged page they are added up by person. */
  const fr = {};
  X.friends.forEach(r => { const who = OWNER[r[0]] || r[0]; if (!FR.includes(who)) return; const m = fr[who] || (fr[who] = [who, 0, 0, [], [], []]);
    m[1] += r[1]; m[2] += r[2]; m[3].push([r[3], r[1]]); m[4].push([r[4], r[1]]); m[5].push([r[5], r[1]]); });
  const wavg = l => { const k = l.filter(x => x[0] != null); const n = k.reduce((s, x) => s + x[1], 0); return n ? k.reduce((s, x) => s + x[0] * x[1], 0) / n : null; };
  const friends = Object.values(fr).sort((a, b) => b[1] - a[1]);
  const group = card(`The group on ${esc(cm.n)} ${RN[role].toLowerCase()}`, 'Click a name for their profile\'s Champions tab.',
    friends.length ? tableWrap('<thead><tr><th>Player</th><th class="num">Games</th><th class="num">Winrate</th><th class="num">KDA</th><th class="num">Gold @15</th><th class="num">Score</th></tr></thead><tbody>' +
      friends.map(f => { const k = wavg(f[3]), g = wavg(f[4]), sc = wavg(f[5]);
        return `<tr class="click${f[1] < LOW ? ' thin' : ''}" ${openP(f[0], 'champions')}><td>${who(f[0])}</td><td class="num">${f[1]}</td><td class="num">${pc1(100 * f[2] / f[1])}</td>` +
          `<td class="num">${k == null ? '-' : k.toFixed(1)}</td><td class="num ${gcls(g)}">${gold(g)}</td><td class="num strong">${sc == null ? '-' : Math.round(sc)}</td></tr>`; }).join('') + '</tbody>')
      : '<div class="empty">Nobody in the group has played it here.</div>');
  out += `<div class="grid g2">${byRank}${group}</div>`;

  const item = id => `<span class="chip">${iicon(id)}${esc(D.items[id] || 'Item ' + id)}</span>`;
  out += card('Builds', `The commonest first three finished items, with boots, across every ${esc(cm.n)} ${rl.replace(/s$/, '')} in the stored lobbies.`,
    (X.builds.length ? X.builds.map(bd => `<div class="build"><div class="items">${bd.items.map(item).join('<span class="muted">→</span>')}` +
      `${bd.boots ? '<span class="muted">+</span>' + item(bd.boots) : ''}</div><div class="muted small" style="margin-top:8px">${bd.games} games · <b class="${bd.wr >= 50 ? 'pos' : 'neg'}">${pc1(bd.wr)} winrate</b></div></div>`).join('')
      : '<div class="empty">No game here reached three finished items.</div>') +
    (X.skill ? `<h3>Skill order</h3><span class="chip" style="padding-left:11px">${esc(X.skill.order)}</span> <span class="muted">${X.skill.share}% of games</span>` : ''));
  return out;
}
const COUNTER_ROWS = 12;
function tabChampionsSite() {
  return S.champ ? champDetail(S.champ) : champIndex();
}
