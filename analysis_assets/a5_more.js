/* ---- Records -------------------------------------------------------------------- */
function tabRecords() {
  const R = D.records;
  /* The season highlights are the main dashboard's own cards, built by the
     same code that builds them there, so the two pages cannot disagree. */
  const season = R.season.length ? `<section class="card" style="margin-bottom:20px"><h2>Season highlights</h2><p class="hint">The same awards as the Basic page, worked out the same way.</p>` +
    `<div class="awards">${R.season.map(c => `<div class="award" style="--stripe:${col(c.who)}"><div class="award-icon">${c.icon}</div><div class="award-body">` +
      `<div class="award-title">${esc(c.title)}</div><div class="award-text">${c.text}</div>${c.why || ''}</div></div>`).join('')}</div></section>` : '';
  const how = rows => !rows || !rows.length ? '' : `<details class="award-why"><summary>How this was worked out</summary><table class="why-table"><thead><tr><th class="num">#</th><th>Player</th>` +
    `<th class="num">Value</th><th class="num">Games</th></tr></thead><tbody>${rows.map((r, i) => `<tr><td class="num muted">${i + 1}</td><td>${fn(r[0])}</td><td class="num"><b>${esc(r[1])}</b></td><td class="num muted">${r[2]}</td></tr>`).join('')}</tbody></table></details>`;
  const game = R.game.length ? `<section class="card"><h2>Game records</h2><p class="hint">From the minute-by-minute data. Comebacks and throws count from 5k gold, judged on a win chance that knows how each team's champions scale. ` +
    `Anything that names a best needs thirty games behind it.</p><div class="awards">${R.game.map(c => `<div class="award" style="--stripe:${c.who ? col(c.who) : 'var(--violet)'}"><div class="award-icon">${c.icon}</div><div class="award-body">` +
      `<div class="award-title">${esc(c.title)}</div><div class="award-text">${c.text}</div>` +
      (c.game ? `<button type="button" class="linkbtn" ${set({ tab: 'game', game: c.game[0], team: c.game[1] })}>Open this game →</button>` : '') + how(c.how) + '</div></div>').join('')}</div></section>`
    : empty('No game records yet.');
  return season + game;
}

/* ---- Check -----------------------------------------------------------------------
   Scoring one game is done twice: in scoring.py for every stored game, and in
   a1_core.js when a game is opened. analysis.py ships a dozen recent games
   with the plan and score it reached; this fetches those games and scores
   them here. Run Check.run() in the console, or the pre-deploy script does:
   {ok: true} means the two copies of the arithmetic agree. */
window.Check = {
  async run() {
    const bad = [];
    let plans = 0, scores = 0;
    for (const c of SC.check) {
      const mine = JSON.stringify(planFor(c.champ, c.role).map(p => [p[0], p[1], p[2], p[3]]));
      if (mine !== JSON.stringify(c.plan)) bad.push({ game: c.game, what: 'plan', here: mine, there: JSON.stringify(c.plan) });
      else plans++;
      const entry = GAMES.find(g => g[0] === c.game);
      if (!entry) continue;
      try {
        const doc = await loadDay(dayOf(entry[1])), G = doc[c.game];
        if (!G) continue;
        const got = gameScore(c.champ, c.role, c.tier, G.p[c.pid - 1].m || {}).score;
        if (got == null || Math.abs(got - c.score) > 0.05) bad.push({ game: c.game, what: 'score', here: got, there: c.score });
        else scores++;
      } catch (e) { bad.push({ game: c.game, what: 'fetch', here: String(e) }); }
    }
    return { ok: !bad.length && plans > 0, plans, scores, of: SC.check.length, bad };
  },
};
