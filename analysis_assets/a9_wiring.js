/* ---- wiring ----------------------------------------------------------------------
   Last of the scripts on purpose: everything above only defines things, and
   this is where the page is first drawn. */
const VIEWS = { home: tabHome, champions: tabChampionsSite, draft: tabDraft, roles: tabRoles, time: () => tabTime(), duos: tabDuos, flow: tabFlow, records: tabRecords, game: tabGame };
let LAST_P = null;
function render() {
  const inProfile = !!S.p;
  const tab = inProfile ? null : VIEWS[S.tab] ? S.tab : 'home';
  /* A different player's profile starts at the top of their list. */
  if (S.p !== LAST_P) { UI.pn = 20; UI.pexp = null; UI.prt = null; LAST_P = S.p; }
  document.getElementById('tabs').innerHTML = TABS.map(t =>
    `<button type="button" role="tab" aria-selected="${t[0] === tab}" class="tab-btn${t[0] === tab ? ' on' : ''}" ${set({ tab: t[0], p: '', pt: '', champ: '', crole: '', game: '' })}>${t[1]}</button>`).join('') +
    (inProfile ? `<button type="button" class="tab-btn on pchip" ${set({ p: '' })} title="Close this profile">${esc(S.p)} ✕</button>` : '');
  let html;
  try { html = inProfile ? viewProfile() : VIEWS[tab](); } catch (e) { console.error(e); html = empty('This view could not be drawn: ' + esc(e.message)); }
  document.getElementById('view').innerHTML = html;
  /* Eight tabs do not fit across a phone, so the strip scrolls. Without this
     the page could open on a tab whose own button was off the edge of it. */
  const on = document.querySelector('.tab-btn.on'), strip = document.getElementById('tabs');
  if (on && strip.scrollWidth > strip.clientWidth) strip.scrollLeft = on.offsetLeft - (strip.clientWidth - on.offsetWidth) / 2;
  if (tab === 'game') fillGame();
}

/* ---- the search box in the header: a friend or a champion ---------------------- */
function searchHits(q) {
  q = q.trim().toLowerCase();
  if (!q) return [];
  const people = FR.filter(l => l.toLowerCase().includes(q) || String(ACC(l).riot || '').toLowerCase().includes(q))
    .map(l => ({ kind: 'p', key: l, html: `${av(l, 26)}<span><b style="color:${col(l)}">${esc(l)}</b><small>${esc(ACC(l).riot || '')}</small></span><span class="r small muted">profile</span>` }));
  const games = {};
  D.cube.forEach(c => { games[c[0]] = (games[c[0]] || 0) + c[4]; });
  const champs = D.champIndex.map((slug, i) => [slug, i]).filter(([s]) => C(s).n.toLowerCase().includes(q))
    .sort((a, b) => (C(b[0]).n.toLowerCase().startsWith(q) - C(a[0]).n.toLowerCase().startsWith(q)) || (games[b[1]] || 0) - (games[a[1]] || 0)).slice(0, 7)
    .map(([s, i]) => ({ kind: 'c', key: s, html: `${cicon(s, 26)}<span><b>${esc(C(s).n)}</b><small>${esc((C(s).cs || []).join(' · '))}</small></span><span class="r small muted">${games[i] || 0} group games</span>` }));
  return people.concat(champs);
}
function drawSearch(input) {
  const host = input.parentNode.querySelector('.gs-pop'), hits = searchHits(input.value);
  if (!input.value.trim()) { host.innerHTML = ''; return; }
  host.innerHTML = `<div class="sg-pop">${hits.length ? hits.map((h, k) => `<button type="button" class="sg-row${k === 0 ? ' on' : ''}" ` +
    `${h.kind === 'p' ? set({ p: h.key, pt: 'overview', tab: 'home', champ: '', game: '', pq: '', pc: '', pr: '' }) : set({ tab: 'champions', champ: h.key, crole: '', p: '', game: '' })}>${h.html}</button>`).join('')
    : '<div class="sg-foot">Nobody and no champion matches that.</div>'}` + (hits.length ? '<div class="sg-foot">↑↓ to move · Enter to open</div>' : '') + '</div>';
}

/* ---- patch notes ----------------------------------------------------------------- */
const NOTES = CFG.notes || [];
const NOTE_KEY = 'league-dashboard/notes-seen';
function notesSeen() { try { return localStorage.getItem(NOTE_KEY) || ''; } catch (e) { return ''; } }
function markNotes() {
  const btn = document.querySelector('[data-notes]');
  if (btn) btn.classList.toggle('unread', !!NOTES.length && NOTES[0].date > notesSeen());
}
function openNotes() {
  const KIND = { added: 'New', fixed: 'Fixed', improved: 'Improved', changed: 'Changed', removed: 'Removed' };
  const D2 = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  openModal(`<div class="modal-head"><div><h2>What's new</h2><p class="hint">Changes to the site, newest first.</p></div><button type="button" class="pill sm" data-close>✕ Close</button></div>` +
    NOTES.map(n => `<div class="note"><div class="note-h"><b>${esc(n.title)}</b><span class="muted small">${D2.format(new Date(n.date + 'T12:00:00Z'))}</span></div><ul>` +
      n.items.map(it => `<li><span class="tag nk ${esc(it.type)}">${KIND[it.type] || 'New'}</span>${esc(it.text)}</li>`).join('') + '</ul></div>').join(''));
  try { if (NOTES[0]) localStorage.setItem(NOTE_KEY, NOTES[0].date); } catch (e) { /* private window: the dot just stays */ }
  markNotes();
}

document.addEventListener('click', e => {
  if (e.target.closest('[data-play]')) return togglePlay();
  if (e.target.closest('[data-notes]')) return openNotes();
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
  if (e.target.closest('[data-mss]')) return runMultisearch();
  if (e.target.closest('[data-shot-apply]')) return applyShot();
  if (e.target.closest('[data-shot-clear]')) { UI.shot = null; return drawShot(); }
  const da = e.target.closest('[data-dra]');
  if (da) return draftAction(JSON.parse(da.dataset.dra));
  const wk = e.target.closest('[data-working]');
  if (wk) return showWorking(S.p, wk.dataset.working);
  const a = e.target.closest('[data-set]');
  if (a) {
    stopPlay();
    closeModal();
    const patch = JSON.parse(a.dataset.set);
    if (a.closest('.sg-pop')) { const i = document.querySelector('[data-gsearch]'); if (i) { i.value = ''; i.blur(); } document.querySelectorAll('.gs-pop').forEach(h => { h.innerHTML = ''; }); }
    const pageChange = PAGE_KEYS.some(k => k in patch && (patch[k] || '') !== (S[k] || ''));
    setState(patch);
    if (pageChange) window.scrollTo({ top: 0 });
    return;
  }
  const u = e.target.closest('[data-ui]');
  if (u) {
    const playing = !!PLAY.timer, patch = JSON.parse(u.dataset.ui);
    Object.assign(UI, patch);
    if ('ml' in patch && S.tab === 'game' && !S.p && document.getElementById('gmap')) {
      /* Switching a map layer redraws the map alone, so playback carries on
         and the page does not jump. */
      document.getElementById('map-layers').innerHTML = layerPills('ml', UI.ml);
      return redrawMap();
    }
    if (playing) stopPlay();
    /* Opening a game on a profile redraws only the list, so the page stays put. */
    if (('pexp' in patch || 'pxt' in patch || 'pn' in patch) && document.getElementById('pgames')) {
      document.getElementById('pgames').innerHTML = profileGameList(S.p);
      return;
    }
    if (S.tab === 'game' && !S.p && NOW && document.getElementById('game-body')) document.getElementById('game-body').innerHTML = gameBody(NOW.G, NOW.entry);
    else render();
  }
});
document.addEventListener('change', e => {
  const pf = e.target.closest('[data-pf]');
  if (pf) return setState({ [pf.dataset.pf]: pf.value });
  if (e.target.matches('[data-cpt]')) return setState({ cpt: e.target.value });
  const dr = e.target.closest('[data-dr]');
  if (dr) return draftChange(dr.dataset.dr, dr.value);
  if (e.target.matches('[data-shot-file]') && e.target.files[0]) return readScreenshot(e.target.files[0]);
});
document.addEventListener('keydown', e => {
  /* Bars and blocks that act as buttons answer to the keyboard as well. */
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[data-session]')) { e.preventDefault(); return sessionModal(e.target.dataset.session); }
  if (e.target.matches('[data-ms]') && e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); return runMultisearch(); }
  if (e.target.matches('[data-grip]') && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) return gripKey(e);
  if (!e.target.matches('[data-gsearch]')) return;
  const host = e.target.parentNode.querySelector('.gs-pop'), rows = [...host.querySelectorAll('.sg-row')];
  const i = rows.findIndex(r => r.classList.contains('on'));
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (!rows.length) return;
    const j = (i + (e.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length;
    rows.forEach((r, k) => r.classList.toggle('on', k === j));
  } else if (e.key === 'Enter') {
    if (rows[i < 0 ? 0 : i]) rows[i < 0 ? 0 : i].click();
  } else if (e.key === 'Escape') {
    e.target.value = ''; host.innerHTML = '';
  }
});
document.addEventListener('input', e => {
  if (e.target.id === 'map-t') { stopPlay(); UI.mapT = Number(e.target.value); redrawMap(); return; }
  if (e.target.matches('[data-gsearch]')) return drawSearch(e.target);
  /* The multisearch box keeps what was typed without a redraw, so the cursor stays put. */
  if (e.target.matches('[data-ms]')) {
    draftState().ms = e.target.value; saveDraft();
    const est = document.querySelector('#mscard .ms-est');
    if (est) est.textContent = msEstText(parseIds(e.target.value).length);
    return;
  }
  if (e.target.matches('[data-cq]')) {
    /* Only the lists are redrawn, so the cursor stays in the box. */
    UI.cq = e.target.value;
    const host = document.getElementById('ccols');
    if (host) host.outerHTML = champIndexCols();
  }
});
/* The suggestions close when the box is left, a moment late so a click on one still lands. */
document.addEventListener('focusout', e => {
  if (!e.target.matches || !e.target.matches('[data-gsearch]')) return;
  const host = e.target.parentNode.querySelector('.gs-pop');
  setTimeout(() => { if (document.activeElement !== e.target && host) host.innerHTML = ''; }, 180);
});
document.addEventListener('focusin', e => {
  if (e.target.matches && e.target.matches('[data-gsearch]') && e.target.value) drawSearch(e.target);
});
/* Dragging a draft row by its handle. */
document.addEventListener('pointerdown', e => {
  const g = e.target.closest && e.target.closest('[data-grip]');
  if (!g || g.disabled || e.button > 0) return;
  e.preventDefault();
  dragStart(e, g);
});
document.addEventListener('pointermove', dragMove);
document.addEventListener('pointerup', dragEnd);
document.addEventListener('pointercancel', dragEnd);
/* A screenshot of champion select: pasted anywhere on the Draft tab, or
   dropped on its box. */
document.addEventListener('paste', e => {
  if (S.tab !== 'draft' || S.p || !SHOT_READY) return;
  const item = [...(e.clipboardData || {}).items || []].find(i => i.type && i.type.startsWith('image/'));
  if (!item) return;
  e.preventDefault();
  readScreenshot(item.getAsFile());
});
document.addEventListener('dragover', e => {
  const z = e.target.closest && e.target.closest('[data-shot-drop]');
  if (z) { e.preventDefault(); z.classList.add('over'); }
});
document.addEventListener('dragleave', e => { const z = e.target.closest && e.target.closest('[data-shot-drop]'); if (z) z.classList.remove('over'); });
document.addEventListener('drop', e => {
  const z = e.target.closest && e.target.closest('[data-shot-drop]');
  if (!z) return;
  e.preventDefault();
  z.classList.remove('over');
  const f = [...(e.dataTransfer || {}).files || []].find(f => f.type.startsWith('image/'));
  if (f) readScreenshot(f);
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
markNotes();
render();
