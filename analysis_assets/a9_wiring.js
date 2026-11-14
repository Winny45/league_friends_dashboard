/* ---- wiring ----------------------------------------------------------------------
   Last of the scripts on purpose: everything above only defines things, and
   this is where the page is first drawn. */
const VIEWS = { game: tabGame, players: tabPlayers, champions: tabChampions, roles: tabRoles, time: tabTime, duos: tabDuos, flow: tabFlow, records: tabRecords };
function render() {
  const tab = VIEWS[S.tab] ? S.tab : 'game';
  document.getElementById('tabs').innerHTML = TABS.map(t =>
    `<button type="button" role="tab" aria-selected="${t[0] === tab}" class="tab-btn${t[0] === tab ? ' on' : ''}" ${set({ tab: t[0] })}>${t[1]}</button>`).join('');
  let html;
  try { html = VIEWS[tab](); } catch (e) { console.error(e); html = empty('This view could not be drawn: ' + esc(e.message)); }
  document.getElementById('view').innerHTML = html;
  /* Eight tabs do not fit across a phone, so the strip scrolls. Without this
     the page could open on a tab whose own button was off the edge of it. */
  const on = document.querySelector('.tab-btn.on'), strip = document.getElementById('tabs');
  if (on && strip.scrollWidth > strip.clientWidth) strip.scrollLeft = on.offsetLeft - (strip.clientWidth - on.offsetWidth) / 2;
  if (tab === 'game') fillGame();
}
document.addEventListener('click', e => {
  if (e.target.closest('[data-play]')) return togglePlay();
  const step = e.target.closest('[data-step]');
  if (step && NOW) {
    stopPlay();
    UI.mapT = Math.max(0, Math.min(NOW.G.dur, UI.mapT + Number(step.dataset.step)));
    document.getElementById('map-t').value = UI.mapT;
    redrawMap();
    return;
  }
  const sess = e.target.closest('[data-session]');
  if (sess) return sessionModal(sess.dataset.session);
  const a = e.target.closest('[data-set]');
  if (a) {
    stopPlay();
    closeModal();
    const patch = JSON.parse(a.dataset.set);
    if (a.closest('.sg-pop')) UI.q = '';
    setState(patch);
    if ('tab' in patch) window.scrollTo({ top: 0 });
    return;
  }
  const u = e.target.closest('[data-ui]');
  if (u) {
    const playing = !!PLAY.timer, patch = JSON.parse(u.dataset.ui);
    Object.assign(UI, patch);
    if ('ml' in patch && S.tab === 'game' && document.getElementById('gmap')) {
      /* Switching a map layer redraws the map alone, so playback carries on
         and the page does not jump. */
      document.getElementById('map-layers').innerHTML = layerPills('ml', UI.ml);
      return redrawMap();
    }
    if (playing) stopPlay();
    if (S.tab === 'game' && NOW && document.getElementById('game-body')) document.getElementById('game-body').innerHTML = gameBody(NOW.G, NOW.entry);
    else render();
  }
});
document.addEventListener('keydown', e => {
  /* Bars and blocks that act as buttons answer to the keyboard as well. */
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[data-session]')) { e.preventDefault(); return sessionModal(e.target.dataset.session); }
  if (!e.target.matches('[data-champ-search]')) return;
  const host = e.target.parentNode.querySelector('.sg-host'), rows = [...host.querySelectorAll('.sg-row')];
  const i = rows.findIndex(r => r.classList.contains('on'));
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (!rows.length) return;
    const j = (i + (e.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length;
    rows.forEach((r, k) => r.classList.toggle('on', k === j));
  } else if (e.key === 'Enter') {
    if (rows[i < 0 ? 0 : i]) rows[i < 0 ? 0 : i].click();
  } else if (e.key === 'Escape') {
    UI.q = ''; e.target.value = ''; host.innerHTML = '';
  }
});
document.addEventListener('input', e => {
  if (e.target.id === 'map-t') { stopPlay(); UI.mapT = Number(e.target.value); redrawMap(); return; }
  if (e.target.matches('[data-champ-search]')) {
    /* Only the list under the box is redrawn: redrawing the page would take
       the cursor out of the box on every letter. */
    UI.q = e.target.value;
    e.target.parentNode.querySelector('.sg-host').innerHTML = champSuggest(UI.q);
  }
});
/* The suggestions close when the box is left, a moment late so a click on one still lands. */
document.addEventListener('focusout', e => {
  if (!e.target.matches || !e.target.matches('[data-champ-search]')) return;
  const host = e.target.parentNode.querySelector('.sg-host');
  setTimeout(() => { if (document.activeElement !== e.target && host) host.innerHTML = ''; }, 180);
});
document.addEventListener('focusin', e => {
  if (e.target.matches && e.target.matches('[data-champ-search]') && UI.q) e.target.parentNode.querySelector('.sg-host').innerHTML = champSuggest(UI.q);
});
/* A new face was chosen: everything that shows it is redrawn. */
document.addEventListener('avatars:changed', () => render());
(function stamp() {
  const el = document.querySelector('[data-generated-ms]');
  if (!el) return;
  const ms = Number(el.dataset.generatedMs), mins = Math.max(0, Math.round((Date.now() - ms) / 60000));
  const ago = mins < 60 ? mins + 'm ago' : mins < 2880 ? Math.round(mins / 60) + 'h ago' : Math.round(mins / 1440) + 'd ago';
  el.innerHTML = `updated <b>${new Date(ms).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })}</b> · ${ago}`;
})();
render();
