/* ---- Champion pairings from the stored lobbies ---------------------------------------
   Every stored game seen from both sides: each team's five champions in role
   order, whether that team won, and the five it played against. Built once, on
   first use, from the game index the page already has. */
let LOBBY = null;
function lobbyStats() {
  if (LOBBY) return LOBBY;
  const base = new Map(), pair = new Map(), vs = new Map(), lane = new Map(), seen = new Set();
  const add = (m, k, w) => { const v = m.get(k); if (v) { v[0]++; v[1] += w; } else m.set(k, [1, w]); };
  GAMES.forEach(g => {
    const L = g[10];
    /* A game two of you played on opposite sides is in the index twice. */
    if (!L || L.length !== 10 || L.some(c => c < 0) || seen.has(g[0])) return;
    seen.add(g[0]);
    for (let side = 0; side < 2; side++) {
      const us = L.slice(side * 5, side * 5 + 5), them = L.slice(5 - side * 5, 10 - side * 5);
      const w = (side === 0) === !!g[5] ? 1 : 0;
      us.forEach((c, i) => {
        add(base, c + '|' + i, w);
        us.forEach((a, j) => { if (j !== i) add(pair, c + '+' + a, w); });
        them.forEach((e, j) => { add(vs, c + '>' + e, w); if (j === i) add(lane, c + '>' + e + '|' + i, w); });
      });
    }
  });
  LOBBY = { base, pair, vs, lane, games: seen.size };
  return LOBBY;
}
const CIX = {};
D.champIndex.forEach((s, i) => { CIX[s] = i; });

/* One person's champions in one role (or every role): slug -> [games, wins]. */
function poolOf(label, role) {
  const out = {};
  if (!label) return out;
  gamesOf(label).forEach(([g, f]) => {
    if (role && f[2] !== role) return;
    const v = out[f[1]] || (out[f[1]] = [0, 0]);
    v[0]++; v[1] += g[5] ? 1 : 0;
  });
  return out;
}

/* ---- The draft tool ------------------------------------------------------------------
   Kept in this browser only: a draft is a few minutes of one person's
   planning, not something to share or keep. */
const DRAFT_KEY = 'league-dashboard/draft';
/* Blue picks 1, 4, 5, 8, 9 of the ten; red picks 2, 3, 6, 7, 10. */
const PICK_NO = { blue: [1, 4, 5, 8, 9], red: [2, 3, 6, 7, 10] };
function draftState() {
  if (UI.dr) return UI.dr;
  let st = null;
  try { st = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch (e) { st = null; }
  if (!st || !Array.isArray(st.us) || st.us.length !== 5) {
    st = { side: 'blue', us: ROLES.map(r => ({ p: '', r, c: '' })), them: ['', '', '', '', ''], bans: [], focus: 0, pool: false };
  }
  UI.dr = st;
  return st;
}
function saveDraft() { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(UI.dr)); } catch (e) { /* private window: it lasts until the tab closes */ } }
function slugOf(name) {
  const q = String(name || '').trim().toLowerCase();
  if (!q) return '';
  return D.champIndex.find(s => C(s).n.toLowerCase() === q) || D.champIndex.find(s => C(s).n.toLowerCase().startsWith(q)) || null;
}
function draftChange(path, value) {
  const st = draftState(), [part, i, key] = path.split('.');
  if (part === 'ban') {
    const s = slugOf(value);
    if (s && !st.bans.includes(s) && st.bans.length < 10) st.bans.push(s);
  } else if (part === 'us') {
    if (key === 'c') { const s = slugOf(value); if (s === null) return render(); st.us[+i].c = s; if (s) st.focus = nextOpen(st, +i); }
    else st.us[+i][key] = value;
  } else if (part === 'them') {
    const s = slugOf(value); if (s === null) return render(); st.them[+i] = s;
  }
  saveDraft();
  render();
}
const nextOpen = (st, from) => { for (let k = 1; k <= 5; k++) { const j = (from + k) % 5; if (!st.us[j].c) return j; } return from; };
function draftAction(a) {
  const st = draftState();
  if (a.a === 'up' && a.i > 0) { [st.us[a.i - 1], st.us[a.i]] = [st.us[a.i], st.us[a.i - 1]]; if (st.focus === a.i) st.focus--; }
  else if (a.a === 'down' && a.i < 4) { [st.us[a.i + 1], st.us[a.i]] = [st.us[a.i], st.us[a.i + 1]]; if (st.focus === a.i) st.focus++; }
  else if (a.a === 'focus') st.focus = a.i;
  else if (a.a === 'pick') { st.us[st.focus].c = a.c; st.focus = nextOpen(st, st.focus); }
  else if (a.a === 'unpick') { if (a.side === 'us') st.us[a.i].c = ''; else st.them[a.i] = ''; }
  else if (a.a === 'unban') st.bans = st.bans.filter(b => b !== a.c);
  else if (a.a === 'side') st.side = a.v;
  else if (a.a === 'pool') st.pool = !st.pool;
  else if (a.a === 'order') { const o = pickOrder(st); if (o) { const f = st.us[st.focus]; st.us = o.map(x => x.slot); st.focus = Math.max(0, st.us.indexOf(f)); } }
  else if (a.a === 'reset') { UI.dr = null; try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* nothing kept */ } }
  if (a.a !== 'reset') saveDraft();
  render();
}

/* Who should pick when. A narrow pool picks early, so its one champion is
   not taken or countered; a deep pool picks late and gets to counter. Roles
   break ties the usual way: supports and junglers early, solo lanes last. */
const ROLE_LATE = { UTILITY: 0, JUNGLE: 0.5, BOTTOM: 1, MIDDLE: 2, TOP: 2.5 };
function poolDepth(label, role) {
  if (!label) return null;
  const pool = poolOf(label, role);
  return Object.values(pool).filter(v => v[0] >= 5 && shrink(v[1], v[0], 0.5, 10) >= 0.5).length;
}
function pickOrder(st) {
  if (st.us.some(x => !x.p)) return null;
  return st.us.map(slot => ({ slot, depth: poolDepth(slot.p, slot.r) }))
    .sort((a, b) => (a.depth + ROLE_LATE[a.slot.r]) - (b.depth + ROLE_LATE[b.slot.r]));
}

/* Suggestions for the slot being picked: every champion its player has played
   in that role, and every champion with enough games there in the lobbies,
   each scored as an expected winrate:
     the lobby winrate in the role (pulled toward 50%)
     -> the player's own winrate on it (pulled toward that)
     + how it has done beside each ally already locked in
     + how it has done against each enemy already shown
     + how it has done against the enemy in the same lane, counted half again
   Each of the last three is a difference from the champion's own winrate,
   pulled hard toward nothing (fifty games' worth, thirty for the lane) and
   held within four points (six for the lane): pairings are thin even across
   a few thousand games, and a 4-0 together is luck far more than synergy. */
function draftSuggest(st) {
  const slot = st.us[st.focus], ri = ROLES.indexOf(slot.r), L = lobbyStats();
  const gone = new Set([...st.us.map(x => x.c), ...st.them, ...st.bans].filter(Boolean));
  const allies = st.us.filter((x, i) => i !== st.focus && x.c).map(x => x.c), enemies = st.them.filter(Boolean);
  const laneFoe = st.them[ri] || '';
  const pool = poolOf(slot.p, slot.r);
  const cand = new Set(Object.keys(pool).filter(s => pool[s][0] >= 2));
  if (!st.pool || !slot.p) L.base.forEach((v, k) => { const [ci, i] = k.split('|'); if (+i === ri && v[0] >= 25) cand.add(D.champIndex[+ci]); });
  const delta = (v, b, k = 50, cap = 0.04) => v ? { d: Math.max(-cap, Math.min(cap, shrink(v[1], v[0], b, k) - b)), n: v[0] } : null;
  const out = [];
  cand.forEach(s => {
    if (gone.has(s)) return;
    const ci = CIX[s], b0 = L.base.get(ci + '|' + ri) || [0, 0], base = shrink(b0[1], b0[0], 0.5, 20);
    const me = pool[s] || [0, 0], own = slot.p ? shrink(me[1], me[0], base, 8) : base;
    const syn = allies.map(a => ({ c: a, ...(delta(L.pair.get(ci + '+' + CIX[a]), base) || { d: 0, n: 0 }) }));
    const vsE = enemies.map(e => ({ c: e, ...(delta(L.vs.get(ci + '>' + CIX[e]), base) || { d: 0, n: 0 }) }));
    const lane = laneFoe ? delta(L.lane.get(ci + '>' + CIX[laneFoe] + '|' + ri), base, 30, 0.06) : null;
    const sum = a => a.reduce((t, x) => t + x.d, 0);
    const exp = own + sum(syn) + sum(vsE) + (lane ? 1.5 * lane.d : 0);
    out.push({ s, exp, base, b0, own, me, syn, vsE, lane });
  });
  return out.sort((a, b) => b.exp - a.exp).slice(0, 10);
}

/* A role inside a sentence: lower case, except ADC. */
const roleWord = r => r === 'BOTTOM' ? 'ADC' : RN[r].toLowerCase();
const dpp = v => (v >= 0 ? '+' : '−') + Math.abs(100 * v).toFixed(1);
function tabDraft() {
  const st = draftState();
  const names = `<datalist id="dr-champs">${D.champIndex.map(s => `<option value="${esc(C(s).n)}">`).join('')}</datalist>`;
  const nums = PICK_NO[st.side];
  const usRows = st.us.map((x, i) => {
    const on = i === st.focus;
    return `<div class="dr-row${on ? ' on' : ''}">` +
      `<button type="button" class="dr-no" data-dra='{"a":"focus","i":${i}}' title="Suggest for this pick">${st.side === 'blue' ? 'B' : 'R'}${i + 1}<small>pick ${nums[i]}</small></button>` +
      `<select class="sel" data-dr="us.${i}.p" aria-label="Player"><option value="">Other</option>${FR.map(l => `<option${l === x.p ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>` +
      `<select class="sel" data-dr="us.${i}.r" aria-label="Role">${ROLES.map(r => `<option value="${r}"${r === x.r ? ' selected' : ''}>${RN[r]}</option>`).join('')}</select>` +
      (x.c ? `<span class="dr-c">${champ(x.c, 24)}<button type="button" class="x" data-dra='{"a":"unpick","side":"us","i":${i}}' aria-label="Clear">✕</button></span>`
        : `<input class="search dr-in" list="dr-champs" data-dr="us.${i}.c" placeholder="${on ? 'Picking now…' : 'Champion'}" aria-label="Champion">`) +
      `<span class="dr-mv"><button type="button" class="x" data-dra='{"a":"up","i":${i}}' aria-label="Move up"${i ? '' : ' disabled'}>▲</button>` +
      `<button type="button" class="x" data-dra='{"a":"down","i":${i}}' aria-label="Move down"${i < 4 ? '' : ' disabled'}>▼</button></span></div>`;
  }).join('');
  const themRows = st.them.map((c, i) => `<div class="dr-row"><span class="dr-no foe">${ricon(ROLES[i])}<small>${RN[ROLES[i]]}</small></span>` +
    (c ? `<span class="dr-c">${champ(c, 24)}<button type="button" class="x" data-dra='{"a":"unpick","side":"them","i":${i}}' aria-label="Clear">✕</button></span>`
      : `<input class="search dr-in" list="dr-champs" data-dr="them.${i}" placeholder="Enemy ${roleWord(ROLES[i])}" aria-label="Enemy ${RN[ROLES[i]]}">`) + '</div>').join('');
  const bans = `<div class="dr-bans">${st.bans.map(b => `<span class="chip">${cicon(b, 18)} ${esc(C(b).n)}<button type="button" class="x" data-dra='${esc(JSON.stringify({ a: 'unban', c: b }))}' aria-label="Remove ban">✕</button></span>`).join('')}` +
    (st.bans.length < 10 ? `<input class="search dr-in sm" list="dr-champs" data-dr="ban" placeholder="Add a ban" aria-label="Add a ban">` : '') + '</div>';

  const order = pickOrder(st);
  const orderTxt = order ? `<div class="dr-order"><b>Suggested order:</b> ${order.map((o, k) => `<span>${k + 1}. <b style="color:${col(o.slot.p)}">${esc(o.slot.p)}</b> <span class="muted">${RN[o.slot.r]} · ${o.depth} strong pick${o.depth === 1 ? '' : 's'}</span></span>`).join('')}` +
    `<button type="button" class="pill sm" data-dra='{"a":"order"}'>Use this order</button><p class="muted small">Fewest strong champions in their role first, so a narrow pool is not taken or countered; the deepest pool last, to answer the enemy laner. A strong pick is five or more games at a winrate that holds up.</p></div>`
    : '<p class="muted small">Choose a player for every pick to get a suggested order.</p>';

  const slot = st.us[st.focus], sug = draftSuggest(st);
  const who = slot.p ? `<b style="color:${col(slot.p)}">${esc(slot.p)}</b>` : 'someone else';
  const chip = (x, tag) => x && x.n ? `<span class="dchip ${x.d > 0.004 ? 'pos' : x.d < -0.004 ? 'neg' : ''}" title="${x.n} games">${tag} ${dpp(x.d)}</span>` : '';
  const rows = sug.map(r => `<tr><td>${champ(r.s, 24)}</td><td class="num"><b class="${r.exp >= 0.52 ? 'pos' : r.exp <= 0.48 ? 'neg' : ''}">${pc1(100 * r.exp)}</b></td>` +
    `<td class="num muted">${pc1(100 * r.base)} <small>(${r.b0[0]})</small></td>` +
    `<td class="num">${slot.p ? (r.me[0] ? `${pc1(100 * r.me[1] / r.me[0])} <small class="muted">(${r.me[0]})</small>` : '<span class="muted">new</span>') : '-'}</td>` +
    `<td>${r.syn.map(x => chip(x, cicon(x.c, 16))).join('')}${r.vsE.map(x => chip(x, 'vs ' + cicon(x.c, 16))).join('')}${r.lane && r.lane.n ? chip(r.lane, '<b>lane</b>') : ''}</td>` +
    `<td><button type="button" class="pill sm" data-dra='${esc(JSON.stringify({ a: 'pick', c: r.s }))}'>Pick</button></td></tr>`).join('');
  const sugCard = card(`Suggestions for ${who} · ${RN[slot.r]}`,
    `Expected winrate: the champion's winrate as a ${roleWord(slot.r)} in the stored lobbies, then ${slot.p ? esc(slot.p) + "'s own games on it, " : ''}then how it has done beside your locked picks and against the enemy's, with the lane matchup counted half again. ` +
    `Each adjustment is pulled toward nothing when it rests on few games; hover one for its sample. These are the group's lobbies (${lobbyStats().games.toLocaleString('en-GB')} games), not the whole server.`,
    (slot.p ? `<div class="filters" style="margin-bottom:10px">${pill('Their champions only', st.pool, `data-dra='{"a":"pool"}'`, ' sm')}</div>` : '') +
    (rows ? tableWrap(`<thead><tr><th>Champion</th><th class="num">Expected</th><th class="num">${RN[slot.r]} WR</th><th class="num">${slot.p ? esc(slot.p) : 'Player'}</th><th>With allies · vs enemies</th><th></th></tr></thead><tbody>${rows}</tbody>`)
      : '<div class="empty">Nothing to suggest: every candidate is picked or banned.</div>'));

  return names + `<div class="grid g2">` +
    card('Your team', 'Put yourselves in pick order (B1 picks first on blue). Click a pick number to get suggestions for it.',
      `<div class="filters" style="margin-bottom:10px"><span class="pill-label">Side</span>${pill('Blue', st.side === 'blue', `data-dra='{"a":"side","v":"blue"}'`, ' sm')}${pill('Red', st.side === 'red', `data-dra='{"a":"side","v":"red"}'`, ' sm')}` +
      `<button type="button" class="linkbtn" style="margin-left:auto" data-dra='{"a":"reset"}'>Start again</button></div>${usRows}${orderTxt}`) +
    card('Enemy team', 'Fill these in as they lock in. The enemy in your lane counts most.', themRows + `<h3 class="dr-h">Bans</h3>` + bans) +
    `</div>` + sugCard;
}

/* ---- Champions to learn, on a profile's Roles & classes tab ------------------------
   For the role on show: champions this person has barely played there, scored
   by how they do in the lobbies near this person's rank, how close they are to
   the classes this person already plays there, and how contested they are.
   Rarely picked and rarely banned is a plus: a champion nobody takes is one
   you can rely on getting. */
function learnCard(label, role) {
  const ri = ROLES.indexOf(role), tier = (D.profiles[label] || {}).tier;
  const near = (t, p) => tier == null || t < 0 || Math.abs(t - tier) <= 1;
  const R = metaRates(near), pool = poolOf(label, role);
  const total = Object.values(pool).reduce((t, v) => t + v[0], 0);
  if (!total) return '';
  /* What this person plays here, as shares of their games by class. */
  const share = {}, byClass = {};
  Object.entries(pool).forEach(([s, v]) => (C(s).cs && C(s).cs.length ? C(s).cs : [C(s).c]).forEach(c => {
    share[c] = (share[c] || 0) + v[0] / total;
    if (!byClass[c] || v[0] > pool[byClass[c]][0]) byClass[c] = s;
  }));
  const minG = Math.max(20, Math.round(R.games / 150));
  const picks = R.each(ri).filter(([ci, g, w]) => g >= minG && (pool[D.champIndex[ci]] || [0])[0] < 5).map(([ci, g, w]) => {
    const s = D.champIndex[ci], cls = C(s).cs && C(s).cs.length ? C(s).cs : [C(s).c];
    const fitCls = cls.slice().sort((a, b) => (share[b] || 0) - (share[a] || 0))[0], fit = share[fitCls] || 0;
    const wr = 100 * shrink(w, g, 0.5, 30), pick = R.pick(g), ban = R.ban(ci);
    const contest = pick + (ban || 0);
    return { s, g, wr, raw: 100 * w / g, fit, fitCls, like: byClass[fitCls], pick, ban, score: (wr - 50) + 6 * fit - 0.15 * contest };
  }).sort((a, b) => b.score - a.score).slice(0, 6);
  if (!picks.length) return '';
  const pickMed = (() => { const a = R.each(ri).filter(p => p[1] >= minG).map(p => R.pick(p[1])).sort((x, y) => x - y); return a[Math.floor(a.length / 2)] || 0; })();
  return card(`Champions to learn as ${/^[AEIOU]/.test(RN[role]) ? 'an' : 'a'} ${roleWord(role)}`,
    `Champions ${esc(label)} has played fewer than five times here, ranked by winrate in the lobbies at ${tier != null ? TIERS[tier] + ' and the tiers either side' : 'every rank'}, ` +
    `by how much they share a class with what ${esc(label)} already plays here, and by how rarely they are picked or banned: an uncontested champion is one you can count on getting.`,
    `<div class="learn">${picks.map(p => `<button type="button" class="lcard" ${set({ tab: 'champions', champ: p.s, crole: role, p: '' })}>` +
      `<div class="lc-h">${cicon(p.s, 40, true)}<span><b>${esc(C(p.s).n)}</b><small class="muted">${esc((C(p.s).cs || [C(p.s).c]).join(' · '))}</small></span></div>` +
      `<div class="lc-t"><span class="dchip ${p.raw >= 52 ? 'pos' : p.raw <= 48 ? 'neg' : ''}">${pc1(p.raw)} WR · ${p.g} games</span>` +
      (p.fit >= 0.1 && p.like ? `<span class="dchip">${esc(p.fitCls)}, like ${esc(C(p.like).n)}</span>` : '<span class="dchip muted">a new class here</span>') +
      `<span class="dchip">picked ${pc1(p.pick)}${p.ban != null ? ` · banned ${pc1(p.ban)}` : ''}</span>` +
      (p.pick < pickMed && p.raw >= 52 ? '<span class="dchip gem">💎 hidden gem</span>' : '') + `</div></button>`).join('')}</div>` +
    `<p class="muted small" style="margin-top:10px">${R.banGames ? `Ban rates from ${R.banGames.toLocaleString('en-GB')} games with bans recorded.` : 'Ban rates will join this once games have been fetched again with their bans.'} Click one for its champion page.</p>`);
}
