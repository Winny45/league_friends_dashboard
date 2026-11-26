/* ---- Overview: the site's front page -------------------------------------------
   Who everyone is and how they are doing, then the two rank charts, the last
   day of games, the best champions and the week so far. Every account card
   opens that player's profile. */

const QKEY = { 420: 'solo', 440: 'flex', 710: 'fives' };
const QNAME = { solo: 'Solo/Duo', flex: 'Flex', fives: '5s' };
/* A person's own login: on the merged page the first of their accounts. */
const primary = label => ((D.meta.friends.find(f => f.label === label) || {}).accounts || [label])[0];
const ACC = label => D.acc[primary(label)] || {};
/* A rank as one number, so it can be sorted and drawn: four hundred a tier,
   a hundred a division, and Master and above carrying on from Diamond I. */
function ladder(r) {
  if (!r) return -1;
  return r[0] >= 7 ? r[0] * 400 + r[2] : r[0] * 400 + (4 - r[1]) * 100 + r[2];
}
const rankLp = r => !r ? 'Unranked' : `${rankName(r)} · ${r[2]} LP`;
const ladderName = v => { const t = Math.min(9, Math.floor(v / 400)); return t >= 7 ? TIERS[t] : `${TSHORT[t]} ${DIV[4 - Math.floor((v - t * 400) / 100)]}`; };
const signedInt = v => v == null ? '-' : (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(Math.round(v));
const lpSpan = v => v == null ? '<span class="muted">-</span>' : `<b class="${v > 0 ? 'pos' : v < 0 ? 'neg' : ''}">${signedInt(v)}</b>`;
/* The predicted gain and loss for a queue, or nothing when there is no basis. */
function predOf(label, q = 'solo') {
  const p = ((ACC(label).q || {})[q] || {}).pred;
  return p && p.win != null ? p : null;
}
/* The last ten solo games, newest on the left, the way a match history reads. */
const formDots = f => `<span class="form" title="Last ${(f || []).length} solo games, newest first">${(f || []).slice().reverse().map(w => `<i class="${w ? 'w' : 'l'}"></i>`).join('')}</span>`;

/* A run of three or more solo games won or lost sets the picture alight:
   green for wins, gold at ten; smoke for losses, and worse at ten. */
function streakFire(label, s, html) {
  const n = Math.abs(s || 0);
  if (n < 3) return html;
  const kind = s > 0 ? (n >= 10 ? 'gold' : 'green') : (n >= 10 ? 'doom' : 'smoke');
  return fire(kind, html, 44, `${n} solo games ${s > 0 ? 'won' : 'lost'} in a row`);
}
const streakTag = s => Math.abs(s || 0) < 3 ? '' : `<span class="stk ${s > 0 ? (s >= 10 ? 'gold' : 'w') : 'l'}">${Math.abs(s)}${s > 0 ? 'W' : 'L'} streak</span>`;
function accountCard(label) {
  const a = ACC(label), r = (a.ranked || {}).solo, pr = predOf(label), PL = D.players[label] || {};
  const games = r ? r[3] + r[4] : 0;
  const main = PL.main ? RN[PL.main] : '';
  return `<button type="button" class="acct" ${openP(label)}>` +
    `<div class="acct-top">${streakFire(label, a.streak, av(label, 44))}<div class="acct-id"><b style="color:${col(label)}">${esc(label)}</b>` +
    `<span style="color:${r ? TCOL[r[0]] : 'var(--muted)'}">${esc(rankLp(r))}</span></div><span class="muted small acct-role">${esc(main)}</span></div>` +
    `<div class="acct-mid"><span>${games ? `<b>${pc1(100 * r[3] / games)}</b> <span class="muted">${r[3]}W ${r[4]}L</span>` : '<span class="muted">no solo games</span>'}</span>` +
    `${a.lp7 != null ? `<span class="${a.lp7 >= 0 ? 'pos' : 'neg'}">${a.lp7 >= 0 ? '▲' : '▼'} ${signedInt(a.lp7)} LP 7d</span>` : ''}</div>` +
    `<div class="acct-low"><span class="acct-form">${formDots(a.form)}${streakTag(a.streak)}</span><span class="muted small">${pr ? `next <b class="pos">${signedInt(pr.win)}</b> / <b class="neg">${signedInt(pr.loss)}</b>${pr.est ? ' <span title="Too few measured games; this is the older estimate">≈</span>' : ''}` : 'next: not enough games'}</span></div></button>`;
}

/* Rank after every game, on the same ladder as the daily chart: a gridline
   at each tier and the tier's colour behind it. */
function rankChangeChart(q) {
  const lines = [];
  let lo = Infinity, hi = -Infinity, n = 0;
  FR.forEach(label => {
    const Q = (ACC(label).q || {})[q] || {}, seq = Q.seq;
    if (!seq || seq.length < 2 || seq[0][5] == null) return;
    const pts = [[0, Q.start]].concat(seq.map((g, i) => [i + 1, g[5]])).filter(p => p[1] != null);
    pts.forEach(p => { lo = Math.min(lo, p[1]); hi = Math.max(hi, p[1]); });
    n = Math.max(n, pts.length - 1);
    lines.push({ pts, color: col(label), end: label, width: 1.8 });
  });
  if (!lines.length) return '<div class="empty">No ranked games recorded in this queue yet.</div>';
  const { y0, y1, yt } = rankAxis(lo, hi);
  const xstep = n > 300 ? 100 : n > 120 ? 50 : n > 40 ? 20 : 10, xt = [];
  for (let x = 0; x <= n; x += xstep) xt.push(x);
  return lineChart(lines, { x0: 0, x1: Math.max(n, 1), y0, y1, xt, yt, yf: v => ladderName(v), tiers: true, r: 70, l: 70, h: 360, label: 'Rank by game' });
}
/* A gridline at the start of every tier, and one division of padding. */
function rankAxis(lo, hi) {
  const y0 = Math.floor((lo - 50) / 400) * 400, y1 = Math.ceil((hi + 50) / 400) * 400, yt = [];
  for (let v = y0; v <= y1; v += 400) yt.push(v);
  return { y0, y1, yt };
}

function dailyRankChart(q, days) {
  const lines = [];
  const end = D.meta.generatedAtMs || Date.now(), from = days ? end - days * 86400000 : 0;
  let lo = Infinity, hi = -Infinity, x0 = Infinity, x1 = -Infinity;
  FR.forEach(label => {
    const daily = ((ACC(label).q || {})[q] || {}).daily;
    if (!daily || daily.length < 2) return;
    const pts = daily.map(d => [Date.parse(d[0] + 'T12:00:00Z'), d[1]]).filter(p => p[0] >= from);
    if (pts.length < 2) return;
    pts.forEach(p => { lo = Math.min(lo, p[1]); hi = Math.max(hi, p[1]); x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); });
    lines.push({ pts, color: col(label), end: label, width: 1.8 });
  });
  if (!lines.length) return '<div class="empty">No daily ranks recorded in this queue yet.</div>';
  const { y0, y1, yt } = rankAxis(lo, hi);
  const span = x1 - x0, xt = [0, 1, 2, 3].map(k => x0 + span * k / 3);
  const MON = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' });
  return lineChart(lines, { x0, x1, y0, y1, xt, yt, yf: v => ladderName(v), xf: v => MON.format(new Date(v)), tiers: true, r: 70, l: 70, h: 360, label: 'Rank by day' });
}

function last24() {
  const since = (D.meta.generatedAtMs || Date.now()) - 86400000;
  const rows = [];
  GAMES.forEach(g => { if (g[1] >= since) g[6].forEach(f => rows.push([g, f])); });
  if (!rows.length) return '<div class="empty">Nobody has played ranked since this time yesterday.</div>';
  return `<div class="g24">${rows.slice(0, 14).map(([g, f]) => `<button type="button" class="g24c ${g[5] ? 'w' : 'l'}" ${set({ tab: 'game', game: g[0], team: g[4], p: '' })}>` +
    `<div class="g24h">${cicon(f[1], 34, true)}<span><b>${esc(C(f[1]).n)}</b><br><span style="color:${col(f[0])};font-weight:600">${esc(f[0])}</span></span></div>` +
    `<div class="g24m"><span class="tag ${g[5] ? 'win' : 'loss'}">${g[5] ? 'WIN' : 'LOSS'}</span><b>${f[3]}/${f[4]}/${f[5]}</b></div>` +
    `<div class="g24m"><span class="muted small">@15 <b class="${gcls(f[6])}">${gold(f[6])}</b></span><span class="g24s"><small>score</small>${f[7] == null ? '<b>-</b>' : scoreNum(f[7], false)}</span></div></button>`).join('')}</div>` +
    (rows.length > 14 ? `<p class="muted small" style="margin-top:10px">and ${rows.length - 14} more.</p>` : '');
}

const WEEK_ICON = { streak: '🔥', climber: '📈', promo: '🎖️', best: '🏅', grinder: '⏳', newpick: '🆕', objective: '🐉', night: '🌙', duo: '🤝', comeback: '🔄' };
const WEEK_TITLE = { streak: 'Hottest streak', climber: 'Climber of the week', promo: 'Promoted', best: 'Best game of the week', grinder: 'Grinder',
  newpick: 'New pick', objective: 'Objective hog', night: 'Late-night games', duo: 'Duo of the week', comeback: 'Comeback' };
function weekItem(it) {
  const [kind, who, text, extra] = it;
  const game = (kind === 'comeback' || kind === 'best') && extra ? set({ tab: 'game', game: extra[0], team: extra[1], p: '' }) : '';
  const link = game || (kind === 'duo' ? set({ tab: 'duos', p: '' }) : kind === 'night' ? set({ tab: 'time', p: '' })
    : kind === 'objective' ? set({ tab: 'roles', p: '' }) : kind === 'newpick' && extra ? set({ tab: 'champions', champ: extra, crole: '', p: '' })
      : who ? openP(who) : '');
  const to = game ? 'Open game' : { duo: 'Duos & stacks', night: 'Time patterns', objective: 'Roles & classes', newpick: extra ? esc(C(extra).n) : '' }[kind] || (who ? esc(who) + "'s profile" : '');
  const lead = kind === 'newpick' && extra ? cicon(extra, 26) : `<span class="wk-i">${WEEK_ICON[kind] || '•'}</span>`;
  const score = kind === 'best' && extra ? ` <span class="wk-sc">${scoreNum(extra[2])}</span>` : '';
  return `<div class="week">${lead}<div><b>${WEEK_TITLE[kind] || ''}</b>${score}<div class="muted small">${esc(text)}</div></div>` +
    (link ? `<button type="button" class="linkbtn" ${link}>${to} →</button>` : '') + '</div>';
}

function tabHome() {
  const people = FR.slice().sort((a, b) => ladder((ACC(b).ranked || {}).solo) - ladder((ACC(a).ranked || {}).solo));
  /* What the group comes to, from every season game rather than the stored ones. */
  let g = 0, w = 0;
  D.time.views.All.cells.forEach(row => row.forEach(c => { g += c[0]; w += c[1]; }));
  const st = D.duos.stacks.All, sides = st.reduce((s, v) => s + v[0], 0), together = sides ? 100 * (sides - st[0][0]) / sides : null;
  const champs = new Set(D.cube.filter(c => c[4] > 0).map(c => c[0])).size;
  const summary = `<div class="acct sum"><div>${tile('Games this season', (D.meta.seasonGames || 0).toLocaleString('en-GB'), '', 'flat')}${tile('Group winrate', pc1(g ? 100 * w / g : null), '', 'flat')}</div>` +
    `<div>${tile('Champions', champs, '', 'flat')}${tile('Played together', together == null ? '-' : Math.round(together) + '%', '', 'flat')}</div></div>`;
  let out = `<div class="sec-head"><h2>Accounts</h2><span class="muted small">Click an account to open its profile · sorted by rank</span></div>` +
    `<div class="accts">${people.map(accountCard).join('')}${summary}</div>`;

  const q = ['solo', 'flex', 'fives'].includes(UI.hq) ? UI.hq : 'solo', dq = ['solo', 'flex', 'fives'].includes(UI.dq) ? UI.dq : 'solo';
  const days = UI.dd === 'season' ? 0 : 90;
  const qp = (key, cur) => ['solo', 'flex', 'fives'].map(k => pill(QNAME[k], cur === k, ui({ [key]: k }), ' sm')).join('');
  const since = esc(D.meta.rankTrackingSince || '');
  out += `<div class="grid g2">` +
    card('Rank change by game', `Rank after every game since ranks were first tracked${since ? ' on ' + since : ''}, on the same scale as the daily chart. Each band is a tier.`, rankChangeChart(q) +
      '<p class="muted small">Each line ends at that player\'s rank after their latest game. Across is games played, not days.</p>', `<span class="pills" style="margin-left:auto">${qp('hq', q)}</span>`) +
    card('Daily rank', 'Rank at the end of each day. Each band is a tier; one division is a hundred LP of height.', dailyRankChart(dq, days),
      `<span class="pills" style="margin-left:auto">${qp('dq', dq)}${pill('90 days', days === 90, ui({ dd: '90' }), ' sm')}${pill('Season', days === 0, ui({ dd: 'season' }), ' sm')}</span>`) + '</div>';

  out += `<div class="grid">${card('Last 24 hours', 'Every game since yesterday. Click one for its breakdown.', last24())}</div>`;

  const top = D.top10;
  const topCard = card('Top 10 champions across everyone', 'Top champions score: game score × rank weight × games played × winrate against the champion at that rank.',
    top.length ? tableWrap('<thead><tr><th class="num">#</th><th>Champion</th><th>Player</th><th>Role</th><th style="min-width:180px">Score</th><th class="num">Games</th><th class="num">Winrate</th></tr></thead><tbody>' +
      top.map((t, i) => `<tr class="click" ${openP(t[0], 'champions')}><td class="num muted">${i + 1}</td><td>${champ(t[1])}</td><td>${fn(t[0])}</td>` +
        `<td class="muted">${esc(RN[t[2]] || '-')}</td><td>${scoreBar(t[3])}</td><td class="num">${t[4]}</td><td class="num">${pc1(t[5])}</td></tr>`).join('') + '</tbody>')
      : '<div class="empty">Nobody has ten games on one champion yet.</div>');
  const wk = D.week, weekCard = card('This week', `${esc(wk.from)} to now · each links to its page`,
    wk.items.length ? wk.items.map(weekItem).join('') : '<div class="empty">Quiet so far.</div>');
  out += `<div class="grid g-3-2">${topCard}${weekCard}</div>`;
  return out;
}
