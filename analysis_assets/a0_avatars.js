/* Player icons, shared by both pages.

   Each player's face is a champion portrait. It starts as their most mastered
   champion and anybody can change it, for themselves: the choice is kept in
   this browser's localStorage, because the site is static files and has
   nowhere to keep it for everyone. To change a default for all viewers, set
   "icon" on that friend in config.json.

   The same file is inlined into the main dashboard and the analysis page, and
   both read the same storage key, so a face chosen on one is the face on the
   other. It brings its own styles for that reason. */
(function () {
  'use strict';
  var el = document.getElementById('avatar-config');
  var cfg = { version: '', defaults: {}, champs: [], played: {} };
  try { if (el) cfg = JSON.parse(el.textContent); } catch (e) { /* keep the empty config */ }
  var KEY = 'league-dashboard/avatars';
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { saved = {}; }
  var names = {};
  cfg.champs.forEach(function (c) { names[c[1]] = c[0]; });

  function idOf(label) {
    var mine = saved[label];
    return (mine && names[mine]) ? mine : (cfg.defaults[label] || null);
  }
  function urlOf(id) {
    return 'https://ddragon.leagueoflegends.com/cdn/' + cfg.version + '/img/champion/' + encodeURIComponent(id) + '.png';
  }
  function url(label) { var id = idOf(label); return id && cfg.version ? urlOf(id) : null; }

  /* Repaint every portrait the server drew, for pages that are not re-rendered. */
  function apply(root) {
    (root || document).querySelectorAll('img[data-av]').forEach(function (img) {
      var id = idOf(img.getAttribute('data-av'));
      if (!id) return;
      var want = urlOf(id);
      if (img.getAttribute('src') !== want) { img.classList.remove('broken'); img.src = want; }
      img.title = names[id] || '';
    });
  }
  function set(label, id) {
    if (id) saved[label] = id; else delete saved[label];
    try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) { /* private mode: lasts for this page only */ }
    apply();
    document.dispatchEvent(new CustomEvent('avatars:changed', { detail: { label: label } }));
  }

  /* ---- the picker ------------------------------------------------------------ */
  var modal = null, current = null;
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function build() {
    var css = document.createElement('style');
    css.textContent =
      '.avp-back{position:fixed;inset:0;z-index:200;background:rgba(5,7,12,.72);display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(4px)}' +
      '.avp-back[hidden]{display:none}' +
      '.avp{width:min(680px,100%);max-height:min(640px,92vh);display:flex;flex-direction:column;background:#161a24;border:1px solid rgba(255,255,255,.14);border-radius:16px;box-shadow:0 18px 44px rgba(0,0,0,.55);color:#f2f4f8;font-family:Inter,system-ui,sans-serif}' +
      '.avp-head{padding:18px 20px 12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}' +
      '.avp-head h3{margin:0;font-size:17px;font-weight:700;flex:1 1 200px;font-family:Outfit,Inter,sans-serif}' +
      '.avp-head input{flex:1 1 180px;height:38px;border-radius:999px;border:1px solid rgba(255,255,255,.14);background:#1f2430;color:inherit;padding:0 14px;font:inherit}' +
      '.avp-grid{padding:4px 20px 12px;overflow-y:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(54px,1fr));gap:8px}' +
      '.avp-grid h4{grid-column:1/-1;margin:8px 0 0;font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:#788296;font-weight:600}' +
      '.avp-c{border:2px solid transparent;border-radius:12px;padding:0;background:#1f2430;cursor:pointer;overflow:hidden;aspect-ratio:1;display:block}' +
      '.avp-c img{width:100%;height:100%;display:block;transform:scale(1.14)}' +
      '.avp-c:hover{border-color:#8b6cf6}.avp-c.on{border-color:#4c8dff;box-shadow:0 0 0 2px rgba(76,141,255,.35)}' +
      '.avp-foot{padding:12px 20px 16px;display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;border-top:1px solid rgba(255,255,255,.08)}' +
      '.avp-foot span{color:#788296;font-size:12px;flex:1 1 220px}' +
      '.avp-foot button{height:36px;border-radius:10px;padding:0 14px;border:1px solid rgba(255,255,255,.14);background:#1f2430;color:#f2f4f8;font:inherit;font-weight:600;font-size:13px;cursor:pointer}' +
      '.avp-foot button.primary{background:#4c8dff;border-color:transparent}' +
      '[data-av-edit]{cursor:pointer;position:relative}' +
      '[data-av-edit]:focus-visible{outline:2px solid #4c8dff;outline-offset:3px;border-radius:50%}';
    document.head.appendChild(css);
    modal = document.createElement('div');
    modal.className = 'avp-back';
    modal.hidden = true;
    modal.innerHTML = '<div class="avp" role="dialog" aria-modal="true" aria-labelledby="avp-title">' +
      '<div class="avp-head"><h3 id="avp-title"></h3><input type="search" placeholder="Search champion…" aria-label="Search champion"></div>' +
      '<div class="avp-grid"></div>' +
      '<div class="avp-foot"><span>Saved in this browser only. Everyone else keeps seeing the default.</span>' +
      '<button type="button" data-avp="reset">Use most mastered</button><button type="button" class="primary" data-avp="close">Done</button></div></div>';
    document.body.appendChild(modal);
    modal.addEventListener('click', function (e) {
      if (e.target === modal || e.target.closest('[data-avp="close"]')) return close();
      if (e.target.closest('[data-avp="reset"]')) { set(current, null); return draw(); }
      var c = e.target.closest('.avp-c');
      if (c) { set(current, c.getAttribute('data-id')); draw(); }
    });
    modal.querySelector('input').addEventListener('input', draw);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && modal && !modal.hidden) close(); });
  }
  function tile(c, chosen) {
    return '<button type="button" class="avp-c' + (c[1] === chosen ? ' on' : '') + '" data-id="' + esc(c[1]) + '" title="' + esc(c[0]) + '" aria-label="' + esc(c[0]) + '">' +
      '<img loading="lazy" alt="" src="' + urlOf(c[1]) + '"></button>';
  }
  function draw() {
    var q = modal.querySelector('input').value.trim().toLowerCase(), chosen = idOf(current);
    var all = cfg.champs.filter(function (c) { return !q || c[0].toLowerCase().indexOf(q) >= 0; });
    var mine = (cfg.played[current] || []).filter(function (id) { return names[id] && (!q || names[id].toLowerCase().indexOf(q) >= 0); });
    var html = '';
    if (mine.length) html += '<h4>Most played</h4>' + mine.map(function (id) { return tile([names[id], id], chosen); }).join('') + '<h4>Everyone</h4>';
    html += all.map(function (c) { return tile(c, chosen); }).join('') || '<h4>No champion by that name</h4>';
    modal.querySelector('.avp-grid').innerHTML = html;
  }
  function open(label) {
    if (!cfg.champs.length) return;
    if (!modal) build();
    current = label;
    modal.querySelector('#avp-title').textContent = 'Choose an icon for ' + label;
    modal.querySelector('input').value = '';
    draw();
    modal.hidden = false;
    modal.querySelector('input').focus();
  }
  function close() { modal.hidden = true; }

  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-av-edit]');
    if (t) { e.preventDefault(); e.stopPropagation(); open(t.getAttribute('data-av-edit')); }
  }, true);
  document.addEventListener('keydown', function (e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('[data-av-edit]')) { e.preventDefault(); open(e.target.getAttribute('data-av-edit')); }
  });

  window.Avatars = { idOf: idOf, url: url, name: function (label) { return names[idOf(label)] || ''; }, apply: apply, open: open, set: set };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { apply(); });
  else apply();
})();
