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
   Riot IDs pasted in, looked up in every lobby the group has played: their
   champions, roles, record and the rank they were at. Anyone the group has
   never played with or against is not in there, so each name also links
   out to the usual sites. The lookup files are keyed by a hash of the name
   (see name_key in analysis_site.py), so they never list anyone. */
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
function msSummary(rows) {
  if (!rows || !rows.length) return null;
  const today = Math.floor(Date.now() / 86400000);
  const sum = (k) => rows.reduce((t, r) => t + r[k], 0);
  const roles = [0, 0, 0, 0, 0];
  rows.forEach(r => { if (r[1] >= 0) roles[r[1]]++; });
  /* Champions by how often, recent games counting more (half as much after
     two months), so a new main shows over an old one. */
  const per = {};
  rows.forEach(r => { const p = per[r[0]] || (per[r[0]] = { ci: r[0], n: 0, w: 0, k: 0, d: 0, a: 0, wt: 0, roles: [0, 0, 0, 0, 0] });
    p.n++; p.w += r[2]; p.k += r[3]; p.d += r[4]; p.a += r[5]; p.wt += Math.pow(0.5, (today - r[8]) / 60); if (r[1] >= 0) p.roles[r[1]]++; });
  const top = Object.values(per).sort((a, b) => b.wt - a.wt).slice(0, 3);
  const last = rows.slice().sort((a, b) => b[8] - a[8]), ranked = last.find(r => r[6] >= 0);
  return { n: rows.length, w: sum(2), kda: (sum(3) + sum(5)) / Math.max(1, sum(4)), roles, top, last: last[0][8], rank: ranked ? [ranked[6], ranked[7]] : null };
}
async function runMultisearch() {
  const st = draftState(), ids = parseIds(st.ms || '');
  UI.msRes = { ids, busy: true, found: {} };
  render();
  const keys = ids.map(nameKey);
  const shards = await Promise.all([...new Set(keys.map(k => k[0]))].map(s => loadShard(s).then(d => [s, d])));
  const by = Object.fromEntries(shards);
  ids.forEach((id, k) => { UI.msRes.found[id] = msSummary((by[keys[k][0]] || {})[keys[k]]); });
  UI.msRes.busy = false;
  if (S.tab === 'draft' && !S.p) render();
}
const opggSlug = id => { const [n, t] = id.split('#'); return encodeURIComponent(n) + '-' + encodeURIComponent(t || ''); };
function multisearchCard(st) {
  const R = UI.msRes, region = REGION[D.meta.platform] || 'euw', ids = parseIds(st.ms || '');
  const multi = ids.length ? `<span class="ms-links"><span class="muted small">All ${ids.length} on</span>` +
    `<a class="pill sm" target="_blank" rel="noopener" href="https://www.op.gg/multisearch/${region}?summoners=${encodeURIComponent(ids.join(','))}">op.gg ↗</a>` +
    `<a class="pill sm" target="_blank" rel="noopener" href="https://u.gg/multisearch?summoners=${encodeURIComponent(ids.join(','))}&region=${encodeURIComponent(D.meta.platform)}">u.gg ↗</a></span>` : '';
  let body = '';
  if (R && R.busy) body = '<div class="empty">Searching…</div>';
  else if (R && R.ids.length) {
    body = `<div class="ms-grid">${R.ids.map(id => {
      const f = R.found[id], link = `https://www.leagueofgraphs.com/summoner/${region}/${opggSlug(id)}`;
      const head = `<div class="ms-h"><b>${esc(id)}</b><a class="linkbtn" target="_blank" rel="noopener" href="https://www.op.gg/summoners/${region}/${opggSlug(id)}">op.gg ↗</a><a class="linkbtn" target="_blank" rel="noopener" href="${link}">LoG ↗</a></div>`;
      if (!f) return `<div class="ms-card">${head}<div class="muted small">Not in any of the group's stored games. Use the links for their history.</div></div>`;
      const roleTot = f.roles.reduce((t, v) => t + v, 0) || 1;
      const roles = ROLES.map((r, k) => [r, f.roles[k]]).filter(x => x[1]).sort((a, b) => b[1] - a[1]).slice(0, 2)
        .map(([r, v]) => `${ricon(r, 14)} ${RN[r]} ${Math.round(100 * v / roleTot)}%`).join(' · ');
      const ago = Math.floor(Date.now() / 86400000) - f.last;
      return `<div class="ms-card">${head}` +
        `<div class="ms-stats"><span>${f.rank ? `<b style="color:${TCOL[f.rank[0]]}">${TIERS[f.rank[0]]}${f.rank[0] < 7 && f.rank[1] ? ' ' + DIV[f.rank[1]] : ''}</b>` : '<span class="muted">rank not read</span>'}</span>` +
        `<span><b class="${100 * f.w / f.n >= 52 ? 'pos' : 100 * f.w / f.n <= 48 ? 'neg' : ''}">${pc1(100 * f.w / f.n)}</b> <span class="muted">${f.w}W ${f.n - f.w}L</span></span>` +
        `<span><b>${f.kda.toFixed(2)}</b> <span class="muted">KDA</span></span></div>` +
        `<div class="muted small">${roles} · seen ${f.n} game${f.n === 1 ? '' : 's'}, last ${ago <= 0 ? 'today' : ago + 'd ago'}</div>` +
        `<div class="ms-picks"><span class="muted small">Expected picks</span>${f.top.map(p => { const slug = D.champIndex[p.ci], r = p.roles.indexOf(Math.max(...p.roles));
          return `<span class="ms-pick" title="${esc(C(slug).n)}: ${p.n} games, ${pc1(100 * p.w / p.n)}, KDA ${((p.k + p.a) / Math.max(1, p.d)).toFixed(2)}">${cicon(slug, 30, true)}` +
            `<span><b>${esc(C(slug).n)}</b><small class="muted">${r >= 0 && p.roles[r] ? RN[ROLES[r]] + ' · ' : ''}${p.n}g · ${pc1(100 * p.w / p.n)} · ${((p.k + p.a) / Math.max(1, p.d)).toFixed(1)} KDA</small></span></span>`; }).join('')}</div></div>`;
    }).join('')}</div>`;
  }
  return card('Multisearch',
    'Paste the enemy\'s Riot IDs (Name#TAG, one a line, or their "joined the lobby" lines). Each is looked up in every stored lobby the group has played: their rank when last seen, record, KDA, roles, and the three champions they are most likely to pick. ' +
    'Anyone you have never played with or against will not be there; the links open their full history elsewhere.',
    `<div class="ms-in"><textarea class="search" rows="3" data-ms placeholder="Name#TAG&#10;Name#TAG">${esc(st.ms || '')}</textarea>` +
    `<div class="ms-act"><button type="button" class="pill sm on" data-mss>Search</button>${multi}</div></div>${body}`);
}
