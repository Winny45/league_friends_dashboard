// Live player lookup for the draft tab's multisearch.
//
//   GET /api/lookup?id=Name%23TAG
//
// One Riot ID a call, so the page can show progress and stop before the key's
// rate limit. About 14 requests to Riot a player: the account, their ranks,
// their top champion masteries, their recent ranked match ids and ten of those
// matches (14 in all). The key comes from the deployment's environment (the publish
// workflow passes the RIOT_API_KEY secret) and never reaches the page.
//
// Every answer carries Riot's own rate-limit counts for the key, so the page
// can say how close it is to the limit and how long to wait. Answers are
// cached at Vercel's edge for fifteen minutes, so looking the same player up
// again costs nothing.

const PLATFORM = process.env.RIOT_PLATFORM || 'euw1';
const REGION = process.env.RIOT_REGION || 'europe';
const MATCHES = 10;
const ID_RE = /^(.{3,16})#([\p{L}\p{N}]{2,5})$/u;

// The busiest count Riot has reported on each host during this call, as
// {limits: "20:1,100:120", counts: "3:1,57:120"}.
function track(seen, host, res) {
  const limits = res.headers.get('x-app-rate-limit'), counts = res.headers.get('x-app-rate-limit-count');
  if (!limits || !counts) return;
  const used = s => Math.max(...s.split(',').map(p => +p.split(':')[0]));
  if (!seen[host] || used(counts) >= used(seen[host].counts)) seen[host] = { limits, counts };
}

class RateLimited extends Error {
  constructor(after) { super('rate limited'); this.after = after; }
}

async function riot(seen, host, path) {
  const res = await fetch(`https://${host}.api.riotgames.com${path}`, { headers: { 'X-Riot-Token': process.env.RIOT_API_KEY } });
  track(seen, host, res);
  if (res.status === 429) throw new RateLimited(+(res.headers.get('retry-after') || 10));
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Riot answered ${res.status}`);
  return res.json();
}

module.exports = async (req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  const send = (code, body, cache) => {
    res.setHeader('Cache-Control', cache ? 'public, s-maxage=900, stale-while-revalidate=60' : 'no-store');
    res.statusCode = code;
    res.end(JSON.stringify(body));
  };
  if (!process.env.RIOT_API_KEY) return send(503, { error: 'nokey' });
  const id = String((req.query && req.query.id) || '').trim();
  const m = id.match(ID_RE);
  if (!m) return send(400, { error: 'badid' });
  const seen = {};
  let calls = 0;
  const call = (host, path) => { calls++; return riot(seen, host, path); };
  try {
    const acct = await call(REGION, `/riot/account/v1/accounts/by-riot-id/${encodeURIComponent(m[1].trim())}/${encodeURIComponent(m[2])}`);
    if (!acct) return send(200, { id, found: false, calls, rate: seen }, true);
    const pu = encodeURIComponent(acct.puuid);
    const [league, mastery, ids] = await Promise.all([
      call(PLATFORM, `/lol/league/v4/entries/by-puuid/${pu}`),
      call(PLATFORM, `/lol/champion-mastery/v4/champion-masteries/by-puuid/${pu}/top?count=5`),
      call(REGION, `/lol/match/v5/matches/by-puuid/${pu}/ids?type=ranked&start=0&count=${MATCHES}`),
    ]);
    const matches = await Promise.all((ids || []).map(mid => call(REGION, `/lol/match/v5/matches/${mid}`).catch(e => { if (e instanceof RateLimited) throw e; return null; })));
    const games = [];
    for (const g of matches) {
      const info = g && g.info;
      const p = info && (info.participants || []).find(x => x.puuid === acct.puuid);
      if (!p || p.gameEndedInEarlySurrender) continue;
      games.push([p.championName, p.teamPosition || '', p.win ? 1 : 0, p.kills, p.deaths, p.assists, info.queueId, info.gameStartTimestamp || info.gameCreation]);
    }
    const ranks = {};
    for (const e of league || []) {
      const q = { RANKED_SOLO_5x5: 'solo', RANKED_FLEX_SR: 'flex' }[e.queueType] || e.queueType;
      ranks[q] = [e.tier, e.rank, e.leaguePoints, e.wins, e.losses];
    }
    // The account's name as Riot spells it; no puuid, no other ids.
    return send(200, {
      id: `${acct.gameName}#${acct.tagLine}`, found: true, ranks,
      mastery: (mastery || []).map(x => [x.championId, x.championLevel, x.championPoints]),
      games, calls, rate: seen,
    }, true);
  } catch (e) {
    if (e instanceof RateLimited) return send(429, { error: 'rate', after: e.after, calls, rate: seen });
    return send(502, { error: 'riot', message: String(e.message || e), calls, rate: seen });
  }
};
