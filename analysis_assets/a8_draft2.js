/* ---- After the picks: builds, a predicted winrate, and a multisearch ----------------
   Below the draft board, for both formats. */

/* What the enemy team brings, from the wiki's tags and classes. The named
   lists are the few things tags cannot say: who heals so much that anti-heal
   is a must, who suppresses (only a cleanse answers it), who slows all game. */
const BIG_HEAL = ['Aatrox', 'Soraka', 'Yuumi', 'Vladimir', 'DrMundo', 'Warwick', 'Sylas', 'Swain', 'Briar', 'Illaoi', 'Fiddlesticks',
  'Nami', 'Sona', 'Milio', 'Olaf', 'Volibear', 'Trundle', 'Fiora', 'Darius', 'Kayn', 'Samira', 'Seraphine', 'Senna', 'Renekton', 'Belveth'];
const SUPPRESS = ['Malzahar', 'Skarner', 'Warwick', 'Urgot'];
const SLOWS = ['Ashe', 'Nasus', 'Singed', 'Zilean', 'Lulu', 'Trundle', 'Anivia', 'Rylai', 'Cassiopeia', 'Ryze', 'Swain', 'Teemo', 'Nunu', 'Gragas', 'Seraphine', 'Mordekaiser', 'Nami'];
const tagsOf = s => C(s).tg || [], classesOf = s => (C(s).cs && C(s).cs.length ? C(s).cs : [C(s).c]);
const hasTag = (s, t) => tagsOf(s).includes(t), hasClass = (s, c) => classesOf(s).includes(c);
function compOf(slugs) {
  const by = f => slugs.filter(f);
  const phys = by(s => hasTag(s, 'Physical')), magic = by(s => hasTag(s, 'Magic')), mixed = by(s => hasTag(s, 'Mixed'));
  return {
    n: slugs.length, phys, magic, mixed,
    physN: phys.length + mixed.length / 2, magicN: magic.length + mixed.length / 2,
    auto: by(s => hasTag(s, 'Auto-attack') || hasClass(s, 'Marksman')),
    cc: by(s => hasTag(s, 'Crowd Control')),
    heal: by(s => hasTag(s, 'Self Healing') || BIG_HEAL.includes(s)),
    bigHeal: by(s => BIG_HEAL.includes(s)),
    shield: by(s => hasTag(s, 'Ally Protection')),
    dive: by(s => hasClass(s, 'Assassin') || hasClass(s, 'Diver') || hasTag(s, 'Dive')),
    burst: by(s => hasTag(s, 'Burst') && hasTag(s, 'Magic')),
    supp: by(s => SUPPRESS.includes(s)),
    slow: by(s => SLOWS.includes(s)),
  };
}
/* What kind of builder a champion is, for who takes which situational item. */
function builderOf(s) {
  if (hasClass(s, 'Marksman')) return 'adc';
  if (hasClass(s, 'Enchanter') || hasClass(s, 'Catcher') && !hasTag(s, 'Durable')) return 'enchanter';
  if (hasClass(s, 'Vanguard') || hasClass(s, 'Warden') || (hasTag(s, 'Durable') && !hasClass(s, 'Juggernaut') && !hasClass(s, 'Diver'))) return 'tank';
  if (hasTag(s, 'Magic') || hasClass(s, 'Burst mage') || hasClass(s, 'Battlemage') || hasClass(s, 'Artillery')) return 'ap';
  return 'ad';
}
const ANTIHEAL = { adc: [3123, 3033], ad: [3123, 6609], ap: [3916, 3165], tank: [3076, 3075] };
const champNames = list => list.map(s => C(s).n).join(', ');

/* Each of our picks: its usual build in that role from the stored lobbies,
   then the changes this enemy team calls for, each with its reason.
   Anti-heal goes to one player against two or more healers (two players
   against three, or any of the very big healers with another), chosen in
   the order an ADC, another physical carry, a mage, then a tank against
   auto-attacking healers, never a support. */
function draftBuilds(st, ER) {
  const ours = [0, 1, 2, 3, 4].filter(i => st.us[i].c);
  const foes = st.them.map(x => x.c).filter(Boolean);
  if (!ours.length) return '';
  const docs = ours.map(i => CHAMP_DOCS[st.us[i].c]);
  if (docs.some(d => !d)) {
    Promise.all(ours.map(i => loadChamp(st.us[i].c).catch(() => null))).then(() => { if (S.tab === 'draft' && !S.p) render(); });
    if (docs.every(d => !d)) return card('Builds', '', '<div class="empty">Loading builds…</div>');
  }
  const E = compOf(foes);
  const healNeed = E.heal.length >= 3 || (E.heal.length >= 2 && E.bigHeal.length) ? 2 : E.heal.length >= 2 || E.bigHeal.length >= 1 ? 1 : 0;
  const rank = { adc: 0, ad: 1, ap: 2, tank: 3, enchanter: 9 };
  const healers = ours.filter(i => builderOf(st.us[i].c) !== 'enchanter' && (builderOf(st.us[i].c) !== 'tank' || E.auto.some(s => E.heal.includes(s))))
    .sort((a, b) => rank[builderOf(st.us[a].c)] - rank[builderOf(st.us[b].c)]);
  const antiheal = new Set();
  const types = new Set();
  healers.forEach(i => { const t = builderOf(st.us[i].c); if (antiheal.size < healNeed && !(t !== 'tank' && types.has(t === 'ap' ? 'ap' : 'ad'))) { antiheal.add(i); types.add(t === 'ap' ? 'ap' : 'ad'); } });

  const rows = ours.map(i => {
    const x = st.us[i], s = x.c, doc = CHAMP_DOCS[s], kind = builderOf(s);
    const role = doc && doc.roles[x.r] ? x.r : doc ? Object.keys(doc.roles).sort((a, b) => doc.roles[b].all[0] - doc.roles[a].all[0])[0] : null;
    const B = role ? (doc.roles[role].builds || [])[0] : null;
    if (!B) return `<div class="bd-row">${champ(s, 26)}<span class="muted small">No build with enough games yet.</span></div>`;
    const why = [];
    let boots = B.boots, def = null;
    if (kind !== 'adc' && kind !== 'enchanter') {
      if (E.magicN >= 3 || E.cc.length >= 4) { if (boots !== 3111) { boots = 3111; why.push(['Mercury\'s Treads', `${E.magicN >= 3 ? 'AP-heavy (' + champNames([...E.magic, ...E.mixed]) + ')' : E.cc.length + ' crowd-control champions'}: magic resist and tenacity`]); } }
      else if (E.physN >= 3 && E.auto.length >= 2 && kind !== 'ap') { if (boots !== 3047) { boots = 3047; why.push(['Plated Steelcaps', `AD-heavy with ${E.auto.length} auto-attackers (${champNames(E.auto)})`]); } }
      else if (E.slow.length >= 2 && kind !== 'ap') { boots = 3009; why.push(['Boots of Swiftness', `${E.slow.length} champions that slow all game (${champNames(E.slow)})`]); }
    }
    if (kind === 'ap' && (E.dive.length >= 2)) { def = 3157; why.push(['Zhonya\'s Hourglass', `${E.dive.length} divers or assassins (${champNames(E.dive)})`]); }
    else if (kind === 'ap' && E.burst.length >= 2) { def = 3102; why.push(['Banshee\'s Veil', `burst mages (${champNames(E.burst)})`]); }
    else if (kind === 'adc' && E.supp.length) { def = 3139; why.push(['Mercurial Scimitar', `suppression (${champNames(E.supp)}): only a cleanse answers it`]); }
    else if ((kind === 'adc' || kind === 'ad') && E.shield.length >= 2) { def = 6695; why.push(['Serpent\'s Fang', `shields (${champNames(E.shield)})`]); }
    else if (kind === 'ad' && E.magicN >= 3) { def = 3156; why.push(['Maw of Malmortius', `AP-heavy (${champNames([...E.magic, ...E.mixed])})`]); }
    else if (kind === 'tank' && E.physN >= 3) { def = E.auto.length >= 2 ? 3143 : 3110; why.push([D.items[def] || 'Armor', `AD-heavy (${champNames([...E.phys, ...E.mixed])})`]); }
    else if (kind === 'tank' && E.magicN >= 3) { def = 4401; why.push(['Force of Nature', `AP-heavy (${champNames([...E.magic, ...E.mixed])})`]); }
    const ah = antiheal.has(i) ? ANTIHEAL[kind] || ANTIHEAL.ad : null;
    if (ah) why.unshift([D.items[ah[1]] || 'Anti-heal', `healing (${champNames(E.heal)}): rush ${D.items[ah[0]] || 'the component'} after your first item`]);
    /* The order: first item, anti-heal component, boots, second item, then
       the defensive pick or the third item, then whatever is left. */
    const core = B.items.filter(id => id !== def && !(ah && ah.includes(id)));
    const order = [core[0], ah ? ah[0] : null, boots, core[1], def || core[2], ah ? ah[1] : null, def ? core[2] : null]
      .filter((v, k, a) => v && a.indexOf(v) === k).slice(0, 7);
    const changed = why.length ? ` · <span class="bd-adj">adjusted for this enemy team</span>` : '';
    return `<div class="bd-row"><div class="bd-who">${champ(s, 26)}<span class="muted small">${x.p ? `<b style="color:${col(x.p)}">${esc(x.p)}</b> · ` : ''}${RN[x.r]}</span></div>` +
      `<div class="bd-items">${order.map((id, k) => `${k ? '<span class="bd-arrow">›</span>' : ''}${itemSlot(id, 30)}`).join('')}</div>` +
      `<div class="bd-wr"><b class="${B.wr >= 52 ? 'pos' : B.wr <= 48 ? 'neg' : ''}">${pc1(B.wr)}</b><span class="muted small">core build, ${B.games} games${changed}</span></div>` +
      (why.length ? `<div class="bd-why">${why.map(w => `<span class="dchip">${esc(w[0])}: ${esc(w[1])}</span>`).join('')}</div>` : '') + '</div>';
  }).join('');
  const prof = foes.length ? `<div class="bd-comp"><span class="dchip">AD ${E.physN} · AP ${E.magicN}</span>` +
    (E.heal.length ? `<span class="dchip">heals: ${esc(champNames(E.heal))}</span>` : '') + (E.cc.length ? `<span class="dchip">crowd control: ${E.cc.length}</span>` : '') +
    (E.dive.length ? `<span class="dchip">dive: ${esc(champNames(E.dive))}</span>` : '') + (E.shield.length ? `<span class="dchip">shields: ${esc(champNames(E.shield))}</span>` : '') + '</div>' : '';
  return card('Builds for this draft',
    `Each pick's most played finished items in that role in the stored lobbies, with that build's winrate, then changed for the enemy team: anti-heal for one player against healers (two against three or more), ` +
    `boots for the damage and crowd control they have, and one defensive item where it answers something specific. ${foes.length ? '' : 'Fill in enemy picks to adjust the builds.'}`,
    prof + `<div class="bd-list">${rows}</div>`);
}

/* ---- A predicted winrate for the draft ------------------------------------------
   Every pick on both sides gets the same expected winrate the suggestions
   use (its lobby winrate in the role, the player's own for ours, then its
   allies, its enemies and its lane), and the two sides' average picks are
   set against each other on the log-odds scale. Averages, not sums: five
   champions are not five independent coin flips, and adding them up would
   promise far too much. */
function pickExpect(st, team, i, ER) {
  const L = lobbyStats(), mine = team === 'us', x = st[team][i];
  const role = mine ? x.r : (ER[i] || {}).r;
  if (!x.c || !role) return null;
  const ri = ROLES.indexOf(role), ci = CIX[x.c];
  const b0 = L.base.get(ci + '|' + ri) || [0, 0], base = shrink(b0[1], b0[0], 0.5, 20);
  let own = base;
  if (mine && x.p) { const me = poolOf(x.p, x.r)[x.c] || [0, 0]; own = shrink(me[1], me[0], base, 15); }
  const d = (v, k = 50, cap = 0.04) => ({ d: v ? capv(shrink(v[1], v[0], base, k) - base, cap) : 0 });
  const allies = st[team].filter((y, j) => j !== i && y.c).map(y => y.c);
  const foes = (mine ? st.them : st.us).map(y => y.c).filter(Boolean);
  const laneFoe = mine ? laneFoeOf(st, role, ER) : (st.us.find(y => y.c && y.r === role) || {}).c;
  const e = pickTotal(own, allies.map(a => d(L.pair.get(ci + '+' + CIX[a]))), foes.map(f => d(L.vs.get(ci + '>' + CIX[f]))),
    laneFoe ? d(L.lane.get(ci + '>' + CIX[laneFoe] + '|' + ri), 30, 0.06) : null);
  return Math.max(0.05, Math.min(0.95, e));
}
function draftPrediction(st, ER) {
  const logit = p => Math.log(p / (1 - p));
  const us = [0, 1, 2, 3, 4].map(i => pickExpect(st, 'us', i, ER)).filter(v => v != null);
  const them = [0, 1, 2, 3, 4].map(i => pickExpect(st, 'them', i, ER)).filter(v => v != null);
  if (!us.length && !them.length) return '';
  const avg = a => a.length ? a.reduce((t, p) => t + logit(p), 0) / a.length : 0;
  const z = avg(us) - avg(them);
  const p = 1 / (1 + Math.exp(-z)), done = us.length + them.length;
  return `<div class="dr-pred"><span class="muted small">Predicted winrate${done < 10 ? ` (${done} of 10 picks in)` : ''}</span>` +
    `<b class="${p >= 0.52 ? 'pos' : p <= 0.48 ? 'neg' : ''}">${pc1(100 * p)}</b>` +
    `<div class="wrbar"><i style="width:${(100 * p).toFixed(1)}%;background:${p >= 0.5 ? '#2ecc71' : '#ff5f5f'}"></i><em></em></div>` +
    `<span class="muted small">From each pick's winrate in its role, your own games on yours, and how each has done with its team and against the other, set side against side. A rough guide, not a promise.</span></div>`;
}

/* ---- Multisearch -------------------------------------------------------------------
   Riot IDs pasted in and looked up live, one at a time, by api/lookup.js:
   their ranks, recent ranked games and top champion masteries, straight
   from Riot. What the group's own stored lobbies know about each of them
   (games played with or against the group) shows alongside, from files
   keyed by a hash of the name (see name_key in analysis_site.py), so those
   files never list anyone.

   The Riot key behind the lookup is the same one the hourly update uses,
   and it allows 100 requests every two minutes. A name costs about 14, so
   the page watches the counts Riot reports back and waits before a name
   that would run it out, saying how long. */
const MS_COST = 14, MS_HEADROOM = 10, MS_WINDOW = 120;
function nameKey(id) {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(String(id).replace(/\s+/g, '').toLowerCase())) h = Math.imul(h ^ b, 0x01000193) >>> 0;
  return h.toString(16).padStart(8, '0');
}
const MS_SHARDS = {};
const loadShard = s => MS_SHARDS[s] || (MS_SHARDS[s] = fetch('m/' + s + '.json').then(r => r.ok ? r.json() : {}).catch(() => ({})));
/* Riot IDs from whatever was pasted: one a line or comma separated, or the
   lobby's "Name#TAG joined the lobby" lines. */
function parseIds(text) {
  const out = [];
  String(text || '').split(/[\n,]+/).forEach(part => {
    const m = part.replace(/\s+(joined|left) the lobby.*$/i, '').trim().match(/^(.+?)\s*#\s*([\p{L}\p{N}]{2,5})$/u);
    if (m) { const id = `${m[1].trim()}#${m[2]}`; if (!out.some(o => o.toLowerCase() === id.toLowerCase())) out.push(id); }
  });
  return out.slice(0, 10);
}
/* Rows of [champion, role, won, k, d, a, tier, division, day] -> a summary. */
function msSummary(rows) {
  if (!rows || !rows.length) return null;
  const today = Math.floor(Date.now() / 86400000);
  const sum = k => rows.reduce((t, r) => t + r[k], 0);
  const roles = [0, 0, 0, 0, 0];
  rows.forEach(r => { if (r[1] >= 0) roles[r[1]]++; });
  const per = {};
  rows.forEach(r => { const p = per[r[0]] || (per[r[0]] = { ci: r[0], n: 0, w: 0, k: 0, d: 0, a: 0, wt: 0, roles: [0, 0, 0, 0, 0] });
    p.n++; p.w += r[2]; p.k += r[3]; p.d += r[4]; p.a += r[5]; p.wt += Math.pow(0.5, (today - r[8]) / 60); if (r[1] >= 0) p.roles[r[1]]++; });
  const last = rows.slice().sort((a, b) => b[8] - a[8]), ranked = last.find(r => r[6] >= 0);
  return { n: rows.length, w: sum(2), kda: (sum(3) + sum(5)) / Math.max(1, sum(4)), roles, per, last: last[0][8], rank: ranked ? [ranked[6], ranked[7]] : null };
}
const ciOf = name => CIX[name] != null ? CIX[name] : D.champIndex.findIndex(s => s.toLowerCase() === String(name).toLowerCase());
/* What api/lookup.js sends back, in the same shape, plus the live extras. */
function liveSummary(L) {
  const rows = (L.games || []).map(g => [ciOf(g[0]), ROLES.indexOf(g[1]), g[2], g[3], g[4], g[5], -1, 0, Math.floor(g[7] / 86400000)]).filter(r => r[0] >= 0);
  const s = msSummary(rows) || { n: 0, w: 0, kda: 0, roles: [0, 0, 0, 0, 0], per: {}, last: null, rank: null };
  /* Mastery points count toward the likely picks too: a champion with a
     lot of points is a comfort pick even if it was not in the last ten. */
  (L.mastery || []).forEach(([key, lvl, pts]) => {
    const ci = (D.champKeys || {})[String(key)];
    if (ci == null) return;
    const p = s.per[ci] || (s.per[ci] = { ci, n: 0, w: 0, k: 0, d: 0, a: 0, wt: 0, roles: [0, 0, 0, 0, 0] });
    p.wt += Math.log10(Math.max(10, pts)) / 3;
    p.mastery = [lvl, pts];
  });
  s.ranks = L.ranks || {};
  return s;
}
const topPicks = s => Object.values(s.per).sort((a, b) => b.wt - a.wt).slice(0, 3);
/* The busiest count Riot reported for a window of a minute or more, as
   [used, limit]. */
function rateOf(rate) {
  let best = null;
  Object.values(rate || {}).forEach(({ limits, counts }) => {
    const lim = {};
    limits.split(',').forEach(p => { const [n, w] = p.split(':').map(Number); lim[w] = n; });
    counts.split(',').forEach(p => { const [n, w] = p.split(':').map(Number); if (w >= 60 && lim[w] && (!best || n / lim[w] > best[0] / best[1])) best = [n, lim[w]]; });
  });
  return best;
}
/* What the key has left, as far as this page last heard: forgotten after
   two minutes, when Riot's window has certainly moved on. */
function msBudget() {
  const R = UI.msRate;
  return R && Date.now() - R.at <= MS_WINDOW * 1000 ? R : null;
}
const fmtSecs = s => s < 60 ? `${Math.max(1, Math.round(s))}s` : `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, '0')}s`;
function msPlan(n) {
  const B = msBudget(), per = UI.msPer || 3, cost = n * MS_COST, limit = B ? B.limit : 100;
  const room = (B ? B.limit - B.used : limit) - MS_HEADROOM;
  /* Names that do not fit now wait for the window to move on. */
  const waits = cost > room ? Math.ceil((cost - room) / (limit - MS_HEADROOM)) : 0;
  return { cost, secs: n * per + waits * MS_WINDOW / 2, wait: waits > 0, B };
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function msWait(secs, why) {
  const R = UI.msRes;
  for (let left = Math.ceil(secs); left > 0; left--) {
    if (UI.msRes !== R) return false;
    R.waitMsg = `${why} Waiting ${fmtSecs(left)}…`;
    drawMs();
    await sleep(1000);
  }
  R.waitMsg = '';
  return UI.msRes === R;
}
async function runMultisearch() {
  const st = draftState(), ids = parseIds(st.ms || '');
  if (!ids.length || (UI.msRes && UI.msRes.busy)) return;
  const R = UI.msRes = { ids, busy: true, local: {}, live: {}, done: 0, waitMsg: '' };
  drawMs();
  /* What the group's own lobbies know, which costs nothing. */
  const keys = ids.map(nameKey);
  const shards = Object.fromEntries(await Promise.all([...new Set(keys.map(k => k[0]))].map(s => loadShard(s).then(d => [s, d]))));
  ids.forEach((id, k) => { R.local[id] = msSummary((shards[keys[k][0]] || {})[keys[k]]); });
  drawMs();
  for (const id of ids) {
    if (UI.msRes !== R) return;
    const B = msBudget();
    if (B && B.limit - B.used - MS_HEADROOM < MS_COST) {
      if (!await msWait(MS_WINDOW / 2, `The Riot key is close to its limit (${B.used} of ${B.limit} in the last two minutes).`)) return;
      UI.msRate = null;
    }
    R.live[id] = { state: 'busy' };
    drawMs();
    const t0 = Date.now();
    let tries = 0;
    for (;;) {
      let body = null, status = 0;
      try {
        const res = await fetch('api/lookup?id=' + encodeURIComponent(id));
        status = res.status;
        body = await res.json().catch(() => null);
      } catch (e) { status = 0; }
      if (body && body.rate) { const r = rateOf(body.rate); if (r) UI.msRate = { used: r[0], limit: r[1], at: Date.now() }; }
      if (status === 429 && body && tries++ < 2) {
        if (!await msWait((body.after || 10) + 1, 'Riot asked the site to slow down.')) return;
        continue;
      }
      if (status === 200 && body) R.live[id] = { state: body.found ? 'ok' : 'none', data: body, s: body.found ? liveSummary(body) : null };
      else {
        const why = !status || status === 404 ? 'The live lookup is not reachable from here (it runs on the published site).'
          : body && body.error === 'nokey' ? 'The live lookup has no Riot key yet; it gets one on the next publish.'
            : body && body.error === 'badid' ? 'That is not a Riot ID (Name#TAG).' : 'Riot did not answer properly; try again in a minute.';
        R.live[id] = { state: 'err', why };
      }
      break;
    }
    /* Seconds a name, as measured, for the estimates. Cached answers are
       quick and pull it down, which is right: they cost nothing either. */
    const took = (Date.now() - t0) / 1000;
    UI.msPer = UI.msPer ? 0.6 * UI.msPer + 0.4 * took : took;
    R.done++;
    drawMs();
  }
  R.busy = false;
  drawMs();
}
/* Redraw just the multisearch card, so a running search does not jump the page. */
function drawMs() {
  const host = document.getElementById('mscard');
  if (host && S.tab === 'draft' && !S.p) host.outerHTML = multisearchCard(draftState());
}
const opggSlug = id => { const [n, t] = id.split('#'); return encodeURIComponent(n) + '-' + encodeURIComponent(t || ''); };
const TIER_IX = { IRON: 0, BRONZE: 1, SILVER: 2, GOLD: 3, PLATINUM: 4, EMERALD: 5, DIAMOND: 6, MASTER: 7, GRANDMASTER: 8, CHALLENGER: 9 };
function rankLine(r, label) {
  if (!r) return '';
  const t = TIER_IX[r[0]], wr = r[3] + r[4] ? 100 * r[3] / (r[3] + r[4]) : null;
  return `<span><span class="muted small">${label}</span> <b style="color:${t != null ? TCOL[t] : 'inherit'}">${t != null ? TIERS[t] : esc(r[0])}${t != null && t < 7 ? ' ' + esc(r[1]) : ''}</b> <span class="muted">${r[2]} LP</span>` +
    (wr != null ? ` · <b class="${wr >= 52 ? 'pos' : wr <= 48 ? 'neg' : ''}">${pc1(wr)}</b> <span class="muted">${r[3]}W ${r[4]}L</span>` : '') + '</span>';
}
function pickLine(p) {
  const slug = D.champIndex[p.ci], r = p.roles.indexOf(Math.max(...p.roles));
  const bits = [];
  if (p.n) bits.push(`${p.n}g · ${pc1(100 * p.w / p.n)} · ${((p.k + p.a) / Math.max(1, p.d)).toFixed(1)} KDA`);
  if (p.mastery) bits.push(`M${p.mastery[0]} ${p.mastery[1] >= 1e6 ? (p.mastery[1] / 1e6).toFixed(1) + 'm' : Math.round(p.mastery[1] / 1000) + 'k'} pts`);
  return `<span class="ms-pick">${cicon(slug, 30, true)}<span><b>${esc(C(slug).n)}</b><small class="muted">${p.n && p.roles[r] ? RN[ROLES[r]] + ' · ' : ''}${bits.join(' · ')}</small></span></span>`;
}
function rolesLine(roles) {
  const tot = roles.reduce((t, v) => t + v, 0);
  if (!tot) return '';
  return ROLES.map((r, k) => [r, roles[k]]).filter(x => x[1]).sort((a, b) => b[1] - a[1]).slice(0, 2)
    .map(([r, v]) => `${ricon(r, 14)} ${RN[r]} ${Math.round(100 * v / tot)}%`).join(' · ');
}
function msCard(id, R, region) {
  const live = R.live[id] || { state: 'wait' }, loc = R.local[id];
  const head = `<div class="ms-h"><b>${esc(live.data && live.data.found ? live.data.id : id)}</b>` +
    `<a class="linkbtn" target="_blank" rel="noopener" href="https://www.op.gg/summoners/${region}/${opggSlug(id)}">op.gg ↗</a>` +
    `<a class="linkbtn" target="_blank" rel="noopener" href="https://www.leagueofgraphs.com/summoner/${region}/${opggSlug(id)}">LoG ↗</a></div>`;
  let body;
  if (live.state === 'wait') body = '<div class="muted small">Waiting its turn…</div>';
  else if (live.state === 'busy') body = '<div class="muted small">Asking Riot…</div>';
  else if (live.state === 'none') body = '<div class="muted small">Riot has no account with that Riot ID.</div>';
  else if (live.state === 'err') body = `<div class="muted small">${esc(live.why)}</div>`;
  else {
    const s = live.s, ranks = s.ranks || {}, wr = s.n ? 100 * s.w / s.n : null;
    body = `<div class="ms-stats">${rankLine(ranks.solo, 'Solo') || '<span class="muted small">Unranked in solo</span>'}${rankLine(ranks.flex, 'Flex')}</div>` +
      (s.n ? `<div class="muted small">Last ${s.n} ranked: <b class="${wr >= 52 ? 'pos' : wr <= 48 ? 'neg' : ''}">${s.w}W ${s.n - s.w}L</b> · <b>${s.kda.toFixed(2)}</b> KDA · ${rolesLine(s.roles)}</div>`
        : '<div class="muted small">No recent ranked games.</div>') +
      `<div class="ms-picks"><span class="muted small">Expected picks</span>${topPicks(s).map(pickLine).join('')}</div>`;
  }
  const seen = loc ? `<div class="ms-seen muted small">With the group: ${loc.n} game${loc.n === 1 ? '' : 's'} in the stored lobbies (${loc.w}W ${loc.n - loc.w}L for their team)` +
    `${loc.rank ? `, ${TIERS[loc.rank[0]]}${loc.rank[0] < 7 && loc.rank[1] ? ' ' + DIV[loc.rank[1]] : ''} then` : ''}, mostly ${topPicks(loc).map(p => esc(C(D.champIndex[p.ci]).n)).join(', ')}.</div>` : '';
  return `<div class="ms-card${live.state === 'busy' ? ' busy' : ''}">${head}${body}${seen}</div>`;
}
const msEstText = n => { if (!n) return ''; const P = msPlan(n); return `${n} name${n === 1 ? '' : 's'} · about ${P.cost} requests · about ${fmtSecs(P.secs)}${P.wait ? ' (with a wait)' : ''}`; };
function multisearchCard(st) {
  const R = UI.msRes, region = REGION[D.meta.platform] || 'euw', ids = parseIds(st.ms || '');
  const plan = msPlan(ids.length), B = plan.B;
  const usage = B ? `The key has used <b>${B.used} of ${B.limit}</b> requests in the last two minutes.` : '';
  const warn = ids.length && plan.wait && !(R && R.busy) ? `<div class="ms-warn">⚠ ${ids.length} name${ids.length === 1 ? '' : 's'} need about ${plan.cost} requests` +
    `${B ? `, and the key has about ${Math.max(0, B.limit - B.used - MS_HEADROOM)} to spare right now` : ''}. The search will pause when it gets close and carry on by itself: about ${fmtSecs(plan.secs)} in all.</div>` : '';
  const est = `<span class="muted small ms-est">${msEstText(ids.length)}</span>`;
  const multi = ids.length ? `<span class="ms-links"><span class="muted small">All ${ids.length} on</span>` +
    `<a class="pill sm" target="_blank" rel="noopener" href="https://www.op.gg/multisearch/${region}?summoners=${encodeURIComponent(ids.join(','))}">op.gg ↗</a>` +
    `<a class="pill sm" target="_blank" rel="noopener" href="https://u.gg/multisearch?summoners=${encodeURIComponent(ids.join(','))}&region=${encodeURIComponent(D.meta.platform)}">u.gg ↗</a></span>` : '';
  let prog = '';
  if (R && R.ids.length) {
    const left = R.ids.length - R.done;
    prog = `<div class="ms-prog"><span>${R.busy ? `Looked up <b>${R.done} of ${R.ids.length}</b>${left ? ` · about ${fmtSecs(left * (UI.msPer || 3))} left` : ''}` : `Looked up all ${R.ids.length}.`}</span>` +
      `${usage ? `<span class="muted small">${usage}</span>` : ''}<div class="wrbar"><i style="width:${(100 * R.done / R.ids.length).toFixed(0)}%;background:var(--violet)"></i></div>` +
      (R.waitMsg ? `<div class="ms-warn">⏳ ${esc(R.waitMsg)}</div>` : '') + '</div>' +
      `<div class="ms-grid">${R.ids.map(id => msCard(id, R, region)).join('')}</div>`;
  }
  return `<div id="mscard">` + card('Multisearch',
    'Paste the enemy\'s Riot IDs (Name#TAG, one a line, or their "joined the lobby" lines) and press Search. Each is looked up live with Riot: ranks, the last ten ranked games, ' +
    'top champion masteries and the three champions they are most likely to pick, plus anything the group\'s own games know about them. ' +
    `Each name costs about ${MS_COST} of the 100 requests the site's Riot key allows every two minutes, and the hourly update uses the same key, so the search shows how much is left and waits if it gets close.`,
    `<div class="ms-in"><textarea class="search" rows="3" data-ms placeholder="Name#TAG&#10;Name#TAG">${esc(st.ms || '')}</textarea>` +
    `<div class="ms-act"><button type="button" class="pill sm on" data-mss${R && R.busy ? ' disabled' : ''}>${R && R.busy ? 'Searching…' : 'Search'}</button>${est}${multi}</div>${warn}</div>${prog}`) + '</div>';
}
