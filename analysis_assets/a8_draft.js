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
   planning, not something to share or keep.

   Two formats:
     Ranked draft   (solo/duo and flex) all ten bans in one phase, then
                    B1 · R1 R2 · B2 B3 · R3 R4 · B4 B5 · R5
     Ranked 5s      tournament draft, in two segments: three bans each,
                    B1 · R1 R2 · B2 B3 · R3, two more bans each, then
                    R4 · B4 B5 · R5
   A step is [side, 'ban' or 'pick', slot on that side]. */
const DRAFT_KEY = 'league-dashboard/draft';
const DRAFT_MODES = {
  ranked: { name: 'Ranked draft', steps: [
    ...[0, 1, 2, 3, 4].flatMap(i => [['B', 'ban', i], ['R', 'ban', i]]),
    ['B', 'pick', 0], ['R', 'pick', 0], ['R', 'pick', 1], ['B', 'pick', 1], ['B', 'pick', 2],
    ['R', 'pick', 2], ['R', 'pick', 3], ['B', 'pick', 3], ['B', 'pick', 4], ['R', 'pick', 4]] },
  fives: { name: 'Ranked 5s', steps: [
    ['B', 'ban', 0], ['R', 'ban', 0], ['B', 'ban', 1], ['R', 'ban', 1], ['B', 'ban', 2], ['R', 'ban', 2],
    ['B', 'pick', 0], ['R', 'pick', 0], ['R', 'pick', 1], ['B', 'pick', 1], ['B', 'pick', 2], ['R', 'pick', 2],
    ['R', 'ban', 3], ['B', 'ban', 3], ['R', 'ban', 4], ['B', 'ban', 4],
    ['R', 'pick', 3], ['B', 'pick', 3], ['B', 'pick', 4], ['R', 'pick', 4]] },
};
const blankDraft = () => ({ v: 2, mode: 'ranked', side: 'blue', focus: null, pool: false,
  us: ROLES.map(r => ({ p: '', r, c: '' })), them: [0, 1, 2, 3, 4].map(() => ({ c: '', r: '' })),
  bans: { us: ['', '', '', '', ''], them: ['', '', '', '', ''] } });
function draftState() {
  if (UI.dr) return UI.dr;
  let st = null;
  try { st = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch (e) { st = null; }
  /* A draft saved by the first version of this tool is simply started again. */
  if (!st || st.v !== 2) st = blankDraft();
  UI.dr = st;
  return st;
}
function saveDraft() { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(UI.dr)); } catch (e) { /* private window: it lasts until the tab closes */ } }
function slugOf(name) {
  const q = String(name || '').trim().toLowerCase();
  if (!q) return '';
  return D.champIndex.find(s => C(s).n.toLowerCase() === q) || D.champIndex.find(s => C(s).n.toLowerCase().startsWith(q)) || null;
}
/* Blue or red, as us or them, for the side this draft is on. */
const teamOf = (st, s) => (s === 'B') === (st.side === 'blue') ? 'us' : 'them';
const stepFilled = (st, [s, kind, i]) => kind === 'ban' ? !!st.bans[teamOf(st, s)][i] : !!st[teamOf(st, s)][i].c;
/* Whose turn: the step after the last one filled in. Anything left empty
   before it was skipped (a ban not used, or not entered). */
function draftNow(st) {
  const steps = DRAFT_MODES[st.mode].steps;
  let last = -1;
  steps.forEach((x, k) => { if (stepFilled(st, x)) last = k; });
  return last + 1 < steps.length ? last + 1 : null;
}
/* A pick's number in the whole draft, 1 to 10. */
function pickNumber(st, team, i) {
  const s = (team === 'us') === (st.side === 'blue') ? 'B' : 'R';
  return DRAFT_MODES[st.mode].steps.filter(x => x[1] === 'pick').findIndex(x => x[0] === s && x[2] === i) + 1;
}
const stepLabel = (st, [s, kind, i]) => kind === 'ban' ? `${s === 'B' ? 'Blue' : 'Red'} ban ${i + 1}` : `${s}${i + 1}`;

function draftChange(path, value) {
  const st = draftState(), [part, a, b] = path.split('.');
  if (part === 'ban') {
    const s = slugOf(value);
    if (s === null) return render();
    st.bans[a][+b] = s;
  } else if (b === 'c') {
    const s = slugOf(value);
    if (s === null) return render();
    st[part][+a].c = s;
    if (s && part === 'us') st.focus = null;
  } else {
    st[part][+a][b] = value;
  }
  saveDraft();
  render();
}
function draftAction(a) {
  const st = draftState(), us = st.us;
  const movable = i => i >= 0 && i < 5 && !us[i].c;
  if (a.a === 'up' && movable(a.i) && movable(a.i - 1)) [us[a.i - 1], us[a.i]] = [us[a.i], us[a.i - 1]];
  else if (a.a === 'down' && movable(a.i) && movable(a.i + 1)) [us[a.i + 1], us[a.i]] = [us[a.i], us[a.i + 1]];
  else if (a.a === 'focus') st.focus = a.i;
  else if (a.a === 'pick') { const f = draftFocus(st); if (f != null) us[f].c = a.c; st.focus = null; }
  else if (a.a === 'unpick') st[a.side][a.i].c = '';
  else if (a.a === 'unban') st.bans[a.side][a.i] = '';
  else if (a.a === 'side') st.side = a.v;
  else if (a.a === 'mode') st.mode = a.v;
  else if (a.a === 'pool') st.pool = !st.pool;
  else if (a.a === 'order') {
    const o = pickOrder(st);
    if (o) o.forEach(([slot, pos]) => { us[pos] = slot; });
  } else if (a.a === 'reset') { const m = st.mode, s = st.side; UI.dr = Object.assign(blankDraft(), { mode: m, side: s }); }
  saveDraft();
  render();
}
/* The pick suggestions are for: one clicked, or our next empty pick. */
function draftFocus(st) {
  if (st.focus != null && !st.us[st.focus].c) return st.focus;
  const order = [0, 1, 2, 3, 4].filter(i => !st.us[i].c).sort((x, y) => pickNumber(st, 'us', x) - pickNumber(st, 'us', y));
  return order.length ? order[0] : null;
}

/* ---- Which lane each enemy pick is in -----------------------------------------------
   From how often each champion plays each role in the stored lobbies, the
   most likely way to give the enemy's picks one lane each (every way is
   tried; five picks is 120). A lane set by hand is kept. */
let ROLE_SHARE = null;
function roleShare(ci) {
  if (!ROLE_SHARE) {
    ROLE_SHARE = {};
    D.cube.forEach(c => { const v = ROLE_SHARE[c[0]] || (ROLE_SHARE[c[0]] = [0, 0, 0, 0, 0]); v[c[1]] += c[6]; });
  }
  const v = ROLE_SHARE[ci] || [0, 0, 0, 0, 0], n = v.reduce((t, x) => t + x, 0);
  return v.map(x => (x + 0.2) / (n + 1));
}
function enemyRoles(st) {
  const picks = st.them.map((x, i) => ({ i, c: x.c, r: x.r })).filter(x => x.c);
  const fixed = new Set(picks.filter(x => x.r).map(x => x.r));
  const free = ROLES.filter(r => !fixed.has(r)), auto = picks.filter(x => !x.r);
  let best = null, bestP = -1;
  const go = (k, used, p, asg) => {
    if (k === auto.length) { if (p > bestP) { bestP = p; best = asg.slice(); } return; }
    const sh = roleShare(CIX[auto[k].c]);
    free.forEach(r => { if (!used.has(r)) { used.add(r); asg.push(r); go(k + 1, used, p * sh[ROLES.indexOf(r)], asg); asg.pop(); used.delete(r); } });
  };
  go(0, new Set(), 1, []);
  const out = {};
  picks.forEach(x => { if (x.r) out[x.i] = { r: x.r, p: 1, set: true }; });
  auto.forEach((x, k) => { const r = best ? best[k] : null; if (r) out[x.i] = { r, p: roleShare(CIX[x.c])[ROLES.indexOf(r)], set: false }; });
  return out;
}
/* The enemy champion in a lane: set by hand, or guessed with an even chance or better. */
function laneFoeOf(st, role, ER) {
  const k = Object.keys(ER).find(i => ER[i].r === role && (ER[i].set || ER[i].p >= 0.5));
  return k != null ? st.them[k].c : '';
}

/* Who should pick when, among the players who have not picked yet; the
   picks already made keep their places. A narrow pool goes early, so its
   champion is not taken or countered; a deep pool goes late, to answer the
   enemy laner. A player whose enemy laner is already showing goes first of
   all: they can answer it whenever they pick, so the late slots are better
   spent on someone still facing a blind lane. Roles break ties the usual
   way: supports and junglers early, solo lanes last. */
const ROLE_LATE = { UTILITY: 0, JUNGLE: 0.5, BOTTOM: 1, MIDDLE: 2, TOP: 2.5 };
function poolDepth(label, role) {
  if (!label) return 0;
  const pool = poolOf(label, role);
  return Object.values(pool).filter(v => v[0] >= 5 && shrink(v[1], v[0], 0.5, 10) >= 0.5).length;
}
function pickOrder(st) {
  const open = [0, 1, 2, 3, 4].filter(i => !st.us[i].c);
  if (open.length < 2 || open.some(i => !st.us[i].p)) return null;
  const ER = enemyRoles(st);
  const players = open.map(i => {
    const x = st.us[i], depth = poolDepth(x.p, x.r), seen = !!laneFoeOf(st, x.r, ER);
    return { x, depth, seen, key: seen ? -10 + depth * 0.01 : depth + ROLE_LATE[x.r] };
  }).sort((a, b) => a.key - b.key);
  const slots = open.slice().sort((a, b) => pickNumber(st, 'us', a) - pickNumber(st, 'us', b));
  return players.map((pl, k) => [pl.x, slots[k], pl]);
}

/* ---- Blind safety ---------------------------------------------------------------
   How safe a champion is to pick before seeing the enemy laner, 0 to 100,
   against the other champions in the same role. Three parts, equal weight,
   each a percentile in the role:
     steady     its gold @15 moves little with who it faces (low spread)
     uncounted  little chance of meeting a lane counter (500+ behind at 15)
                once counters that are banned, or already picked by either
                team, are taken out, and the rest are discounted by how
                often they are banned
     resilient  it still wins when 500+ behind at 15 (pulled toward the
                role's usual, twenty games' worth)
   Built per draft, because what is still available changes the middle one. */
const draftGone = st => new Set([...st.us.map(x => x.c), ...st.them.map(x => x.c), ...st.bans.us, ...st.bans.them].filter(Boolean));
function blindTable(st) {
  const B = D.blind || { rows: [], behind: {} }, R = metaRates(() => true);
  const gone = new Set([...draftGone(st)].map(s => CIX[s]));
  const byRole = {};
  B.rows.forEach(([ci, ri, n, spread, nb, wb, counters]) => {
    const live = counters.filter(c => !gone.has(c[0]));
    const expo = live.reduce((t, c) => t + c[3] * (1 - (R.ban(c[0]) || 0) / 100), 0);
    const bwr = (wb + (B.behind[ri] || 0.4) * 20) / (nb + 20);
    (byRole[ri] = byRole[ri] || []).push({ ci, n, spread, expo, bwr, nb, live });
  });
  /* Where a value sits among the role's champions, 0 to 1, ties shared. */
  const pctIn = (list, key, v) => (list.filter(x => x[key] < v).length + 0.5 * list.filter(x => x[key] === v).length) / list.length;
  const out = {};
  Object.entries(byRole).forEach(([ri, list]) => list.forEach(x => {
    const parts = [1 - pctIn(list, 'spread', x.spread), 1 - pctIn(list, 'expo', x.expo), pctIn(list, 'bwr', x.bwr)];
    out[x.ci + '|' + ri] = Object.assign(x, { parts, score: Math.round(100 * (parts[0] + parts[1] + parts[2]) / 3) });
  }));
  return out;
}
const safeCls = v => v >= 65 ? 'pos' : v <= 35 ? 'neg' : '';
function safeCell(b) {
  if (!b) return '<span class="muted" title="Fewer than twenty lanes with gold at fifteen">-</span>';
  const t = `Steady ${Math.round(100 * b.parts[0])} (gold @15 swing ±${b.spread}) · Uncounted ${Math.round(100 * b.parts[1])} (meets a counter ${pc1(100 * b.expo)} of the time) · ` +
    `Resilient ${Math.round(100 * b.parts[2])} (${pc1(100 * b.bwr)} won when 500+ behind) · ${b.n} lanes`;
  return `<b class="${safeCls(b.score)}" title="${esc(t)}">${b.score}</b>`;
}

/* Suggestions for the pick in focus: every champion its player has played
   in that role, and every champion with enough games there in the lobbies,
   each scored as an expected winrate:
     the lobby winrate in the role (pulled toward 50%)
     -> the player's own winrate on it (pulled toward that)
     + how it has done beside each ally already locked in
     + how it has done against each enemy already shown
     + how it has done against the enemy in the same lane, counted half again
   Each of the last three is a difference from the champion's own winrate,
   pulled hard toward nothing (fifty games' worth, thirty for the lane) and
   held within four points, and the totals are held too: all the allies
   together within three points, all the enemies within three, the lane
   within four. Pairings are thin even across a few thousand games, a 4-0
   together is luck far more than synergy, and nine small nudges added up
   would otherwise swamp the champion's own record. */
const capv = (v, c) => Math.max(-c, Math.min(c, v));
const pickTotal = (own, syn, vsE, lane) => own + capv(syn.reduce((t, x) => t + x.d, 0), 0.03) + capv(vsE.reduce((t, x) => t + x.d, 0), 0.03) + (lane ? capv(1.5 * lane.d, 0.04) : 0);
function draftSuggest(st, f, ER) {
  const slot = st.us[f], ri = ROLES.indexOf(slot.r), L = lobbyStats();
  const gone = draftGone(st);
  const allies = st.us.filter((x, i) => i !== f && x.c).map(x => x.c), enemies = st.them.map(x => x.c).filter(Boolean);
  const laneFoe = laneFoeOf(st, slot.r, ER);
  const pool = poolOf(slot.p, slot.r);
  const cand = new Set(Object.keys(pool).filter(s => pool[s][0] >= 2));
  if (!st.pool || !slot.p) L.base.forEach((v, k) => { const [ci, i] = k.split('|'); if (+i === ri && v[0] >= 25) cand.add(D.champIndex[+ci]); });
  /* Blind safety matters most for the first pick and not at all once the
     enemy laner is known: up to four points of winrate at pick one, none
     by pick ten. */
  const BT = blindTable(st), pickNo = pickNumber(st, 'us', f), blindW = laneFoe ? 0 : (10 - pickNo) / 9;
  const delta = (v, b, k = 50, cap = 0.04) => v ? { d: Math.max(-cap, Math.min(cap, shrink(v[1], v[0], b, k) - b)), n: v[0] } : null;
  const out = [];
  cand.forEach(s => {
    if (gone.has(s)) return;
    const ci = CIX[s], b0 = L.base.get(ci + '|' + ri) || [0, 0], base = shrink(b0[1], b0[0], 0.5, 20);
    /* The player's own record, pulled toward the champion's (fifteen games' worth). */
    const me = pool[s] || [0, 0], own = slot.p ? shrink(me[1], me[0], base, 15) : base;
    const syn = allies.map(a => ({ c: a, ...(delta(L.pair.get(ci + '+' + CIX[a]), base) || { d: 0, n: 0 }) }));
    const vsE = enemies.map(e => ({ c: e, ...(delta(L.vs.get(ci + '>' + CIX[e]), base) || { d: 0, n: 0 }) }));
    const lane = laneFoe ? delta(L.lane.get(ci + '>' + CIX[laneFoe] + '|' + ri), base, 30, 0.06) : null;
    const exp = pickTotal(own, syn, vsE, lane);
    const safe = BT[ci + '|' + ri] || null;
    const rank = exp + (safe ? blindW * 0.04 * (safe.score - 50) / 50 : 0);
    out.push({ s, exp, base, b0, own, me, syn, vsE, lane, safe, rank });
  });
  const top = out.sort((a, b) => b.rank - a.rank).slice(0, 10);
  top.blindW = blindW; top.laneFoe = laneFoe; top.pickNo = pickNo;
  return top;
}

/* A role inside a sentence: lower case, except ADC. */
const roleWord = r => r === 'BOTTOM' ? 'ADC' : RN[r].toLowerCase();
const dpp = v => (v >= 0 ? '+' : '−') + Math.abs(100 * v).toFixed(1);
const dra = o => `data-dra='${esc(JSON.stringify(o))}'`;
function tabDraft() {
  const st = draftState(), M = DRAFT_MODES[st.mode], steps = M.steps, now = draftNow(st), cur = now == null ? null : steps[now];
  const ER = enemyRoles(st), f = draftFocus(st);
  const isNow = (team, kind, i) => cur && teamOf(st, cur[0]) === team && cur[1] === kind && cur[2] === i;
  const names = `<datalist id="dr-champs">${D.champIndex.map(s => `<option value="${esc(C(s).n)}">`).join('')}</datalist>`;
  const letter = team => (team === 'us') === (st.side === 'blue') ? 'B' : 'R';

  /* One team: its bans, then its five picks in pick order. Both teams are
     drawn by this, so the two columns have the same rows at the same size. */
  const teamCard = team => {
    const L = letter(team), mine = team === 'us', blue = L === 'B';
    const banSlot = i => {
      const c = st.bans[team][i], on = isNow(team, 'ban', i);
      return `<span class="dr-ban${on ? ' now' : ''}">` + (c
        ? `${cicon(c, 30, true)}<button type="button" class="x" ${dra({ a: 'unban', side: team, i })} aria-label="Remove ban">✕</button>`
        : `<input class="search dr-in" list="dr-champs" data-dr="ban.${team}.${i}" placeholder="${on ? 'Now' : 'Ban'}" aria-label="${blue ? 'Blue' : 'Red'} ban ${i + 1}">`) + '</span>';
    };
    const rows = [0, 1, 2, 3, 4].map(i => {
      const x = st[team][i], on = isNow(team, 'pick', i), focused = mine && f === i, n = pickNumber(st, team, i);
      const champCell = x.c ? `<span class="dr-c">${champ(x.c, 26)}<button type="button" class="x" ${dra({ a: 'unpick', side: team, i })} aria-label="Clear">✕</button></span>`
        : `<input class="search dr-in" list="dr-champs" data-dr="${team}.${i}.c" placeholder="${on ? 'Picking now…' : 'Champion'}" aria-label="${L}${i + 1} champion">`;
      let rest;
      if (mine) {
        rest = `<select class="sel" data-dr="us.${i}.p" aria-label="Player"><option value="">Other</option>${FR.map(l => `<option${l === x.p ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>` +
          `<select class="sel" data-dr="us.${i}.r" aria-label="Role">${ROLES.map(r => `<option value="${r}"${r === x.r ? ' selected' : ''}>${RN[r]}</option>`).join('')}</select>`;
      } else {
        const g = ER[i];
        rest = `<select class="sel span2" data-dr="them.${i}.r" aria-label="Lane"><option value="">${g && !g.set ? `Lane: ${RN[g.r]} ${Math.round(100 * g.p)}%` : 'Lane: guess'}</option>` +
          ROLES.map(r => `<option value="${r}"${r === x.r ? ' selected' : ''}>${RN[r]}</option>`).join('') + '</select>';
      }
      const mv = mine ? `<span class="dr-mv"><button type="button" class="x" ${dra({ a: 'up', i })} aria-label="Move up"${i && !x.c && !st.us[i - 1].c ? '' : ' disabled'}>▲</button>` +
        `<button type="button" class="x" ${dra({ a: 'down', i })} aria-label="Move down"${i < 4 && !x.c && !st.us[i + 1].c ? '' : ' disabled'}>▼</button></span>` : '<span class="dr-mv"></span>';
      const label = mine ? `<button type="button" class="dr-no" ${dra({ a: 'focus', i })} title="Suggest for this pick">${L}${i + 1}<small>pick ${n}</small></button>`
        : `<span class="dr-no">${L}${i + 1}<small>pick ${n}</small></span>`;
      return `<div class="dr-row${on ? ' now' : ''}${focused ? ' on' : ''}">${label}${champCell}${rest}${mv}</div>`;
    }).join('');
    return `<section class="card dr-team ${blue ? 'blue' : 'red'}${mine ? ' mine' : ''}"><h2>${mine ? 'Your team' : 'Enemy team'} · ${blue ? 'blue side, first pick' : 'red side, second pick'}</h2>` +
      (st.mode === 'fives' ? `<div class="dr-bans split">${[0, 1, 2].map(banSlot).join('')}<span class="dr-sep" title="Second ban phase"></span>${[3, 4].map(banSlot).join('')}</div>`
        : `<div class="dr-bans">${[0, 1, 2, 3, 4].map(banSlot).join('')}</div>`) + `${rows}</section>`;
  };

  /* The whole sequence, with the step that is up marked. */
  const strip = `<div class="dr-steps">${steps.map((x, k) => { const team = teamOf(st, x[0]), c = x[1] === 'ban' ? st.bans[team][x[2]] : st[team][x[2]].c;
    return `<span class="dr-step ${x[0] === 'B' ? 'b' : 'r'} ${x[1]}${k === now ? ' now' : ''}${c ? ' done' : ''}" title="${esc(stepLabel(st, x))}${team === 'us' ? ' (you)' : ''}">${c ? cicon(c, 18) : x[1] === 'ban' ? '⊘' : x[0] + (x[2] + 1)}</span>`; }).join('')}</div>`;
  let nowTxt = 'The draft is complete.';
  if (cur) {
    const team = teamOf(st, cur[0]);
    if (cur[1] === 'ban') nowTxt = `<b>${st.mode === 'ranked' ? 'Ban phase' : stepLabel(st, cur)}</b>: ${team === 'us' ? 'your team bans' : 'the enemy bans'}${st.mode === 'ranked' ? ' (all ten bans happen together)' : ''}.`;
    else if (team === 'us') { const x = st.us[cur[2]]; nowTxt = `<b>Your pick, ${stepLabel(st, cur)}</b>: ${x.p ? `<b style="color:${col(x.p)}">${esc(x.p)}</b>` : 'someone'}, ${RN[x.r]}.`; }
    else nowTxt = `<b>Enemy pick, ${stepLabel(st, cur)}</b>.${f != null ? ` Next for you: ${stepLabel(st, [letter('us'), 'pick', f])}${st.us[f].p ? ' (' + esc(st.us[f].p) + ')' : ''}.` : ''}`;
  }
  const head = `<section class="card" style="margin-bottom:20px"><div class="filters">` +
    `<span class="pill-label">Format</span>${Object.entries(DRAFT_MODES).map(([k, m]) => pill(m.name, st.mode === k, dra({ a: 'mode', v: k }), ' sm')).join('')}` +
    `<span class="pill-label">You are</span>${pill('Blue side · first pick', st.side === 'blue', dra({ a: 'side', v: 'blue' }), ' sm')}${pill('Red side · second pick', st.side === 'red', dra({ a: 'side', v: 'red' }), ' sm')}` +
    `<button type="button" class="linkbtn" style="margin-left:auto" ${dra({ a: 'reset' })}>Start again</button></div>` +
    `${strip}<p class="dr-now">${nowTxt}</p>` +
    `<p class="hint">${st.mode === 'ranked' ? 'Solo/duo and flex: every player bans once, all at the same time, then picks go B1 · R1 R2 · B2 B3 · R3 R4 · B4 B5 · R5.'
      : 'Tournament draft: three bans each, B1 · R1 R2 · B2 B3 · R3, two more bans each, then R4 · B4 B5 · R5.'} Fill in picks and bans as they happen; the highlighted slot is the one that is up. ` +
    `Enemy lanes are guessed from how often each champion plays each role; set one by hand if the guess is wrong.</p></section>`;

  const order = pickOrder(st);
  const orderTxt = order ? `<div class="dr-order"><b>Suggested order for the picks still to come:</b> ${order.map(([x, pos, pl]) => `<span>${stepLabel(st, [letter('us'), 'pick', pos])} <b style="color:${col(x.p)}">${esc(x.p)}</b> <span class="muted">${RN[x.r]} · ${pl.seen ? 'enemy laner showing' : pl.depth + ' strong pick' + (pl.depth === 1 ? '' : 's')}</span></span>`).join('')}` +
    `<button type="button" class="pill sm" ${dra({ a: 'order' })}>Use this order</button><p class="muted small">Picks already made keep their places. Anyone whose enemy laner is already showing goes first, since they can answer it whenever they pick; ` +
    `then fewest strong champions, so a narrow pool is not taken or countered, and the deepest pool last. A strong pick is five or more games at a winrate that holds up.</p></div>`
    : st.us.some((x, i) => !x.c && !x.p) ? '<p class="muted small">Choose a player for every pick still to come to get a suggested order.</p>' : '';

  let sugCard = '';
  if (f != null) {
    const slot = st.us[f], sug = draftSuggest(st, f, ER);
    const who = slot.p ? `<b style="color:${col(slot.p)}">${esc(slot.p)}</b>` : 'someone else';
    const chip = (x, tag) => x && x.n ? `<span class="dchip ${x.d > 0.004 ? 'pos' : x.d < -0.004 ? 'neg' : ''}" title="${x.n} games">${tag} ${dpp(x.d)}</span>` : '';
    const rows = sug.map(r => `<tr><td>${champ(r.s, 24)}</td><td class="num"><b class="${r.exp >= 0.52 ? 'pos' : r.exp <= 0.48 ? 'neg' : ''}">${pc1(100 * r.exp)}</b></td>` +
      `<td class="num muted">${pc1(100 * r.base)} <small>(${r.b0[0]})</small></td>` +
      `<td class="num">${slot.p ? (r.me[0] ? `${pc1(100 * r.me[1] / r.me[0])} <small class="muted">(${r.me[0]})</small>` : '<span class="muted">new</span>') : '-'}</td>` +
      `<td class="num">${safeCell(r.safe)}</td>` +
      `<td>${r.syn.map(x => chip(x, cicon(x.c, 16))).join('')}${r.vsE.map(x => chip(x, 'vs ' + cicon(x.c, 16))).join('')}${r.lane && r.lane.n ? chip(r.lane, '<b>lane</b>') : ''}` +
      (!sug.laneFoe && r.safe && r.safe.live.length ? `<span class="dchip warn" title="Its worst lane still available: ${r.safe.live[0][2]} games">⚠ ${cicon(D.champIndex[r.safe.live[0][0]], 16)} ${gold(r.safe.live[0][1])}</span>` : '') + `</td>` +
      `<td><button type="button" class="pill sm" ${dra({ a: 'pick', c: r.s })}>Pick</button></td></tr>`).join('');
    sugCard = card(`Suggestions for ${who} · ${stepLabel(st, [letter('us'), 'pick', f])} · ${RN[slot.r]}`,
      `Expected winrate: the champion's winrate as ${/^[AEIOU]/.test(roleWord(slot.r)) ? 'an' : 'a'} ${roleWord(slot.r)} in the stored lobbies, then ${slot.p ? esc(slot.p) + "'s own games on it, " : ''}then how it has done beside your locked picks and against the enemy's, with the lane matchup counted half again` +
      `${sug.laneFoe ? ` (against ${esc(C(sug.laneFoe).n)})` : ''}. Each adjustment is pulled toward nothing when it rests on few games; hover one for its sample. These are the group's lobbies (${lobbyStats().games.toLocaleString('en-GB')} games), not the whole server.` +
      `<br><b>Blind safety</b> (0 to 100 among ${RLS[slot.r]}; hover for its parts): steady lane gold whoever it faces, little chance of meeting a counter that is still available, and still winning from behind. ` +
      (sug.blindW > 0 ? `This is pick ${sug.pickNo} of 10 with the enemy ${roleWord(slot.r)} unknown, so safety moves the order by up to ${(4 * sug.blindW).toFixed(1)} points of winrate.`
        : sug.laneFoe ? 'The enemy laner is known, so the lane matchup counts instead and safety does not change the order.' : 'Last pick: safety does not change the order.'),
      (slot.p ? `<div class="filters" style="margin-bottom:10px">${pill('Their champions only', st.pool, dra({ a: 'pool' }), ' sm')}</div>` : '') +
      (rows ? tableWrap(`<thead><tr><th>Champion</th><th class="num">Expected</th><th class="num">${RN[slot.r]} WR</th><th class="num">${slot.p ? esc(slot.p) : 'Player'}</th><th class="num" title="How safe to pick before seeing the enemy laner, 0 to 100">Blind safety</th><th>With allies · vs enemies</th><th></th></tr></thead><tbody>${rows}</tbody>`)
        : '<div class="empty">Nothing to suggest: every candidate is picked or banned.</div>'));
  } else sugCard = card('Suggestions', '', '<div class="empty">All five of your picks are in.</div>');

  /* Your team always on the left, the enemy on the right. The side you
     choose only decides who picks first: blue has pick 1, red picks second. */
  const left = 'us', right = 'them';
  return names + head + `<div class="grid g2 dr-board">${teamCard(left)}${teamCard(right)}</div>` + draftPrediction(st, ER) +
    (orderTxt ? `<section class="card" style="margin-bottom:20px">${orderTxt}</section>` : '') + sugCard + draftBuilds(st, ER) + multisearchCard(st);
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
