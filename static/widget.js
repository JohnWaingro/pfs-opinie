/**
 * Print Flow Solutions — widget opinii
 * Uzycie:
 *   <div id="pfs-testimonials"></div>
 *   <script src="https://twoja-domena.onrender.com/static/widget.js"></script>
 *
 * Opcjonalne atrybuty na divie:
 *   data-columns="3"   — liczba kolumn (domyslnie 3)
 *   data-max="12"      — max liczba opinii (domyslnie wszystkie)
 */
(function () {
  'use strict';

  var SCRIPT_SRC = (function () {
    var scripts = document.getElementsByTagName('script');
    return scripts[scripts.length - 1].src;
  })();

  // Wyprowadz base URL z lokalizacji skryptu (dziala na kazdym hoscie)
  var BASE_URL = SCRIPT_SRC.replace(/\/static\/widget\.js.*$/, '');

  function esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function initials(name) {
    var parts = name.trim().split(/\s+/);
    var ini = parts[0][0] || '';
    if (parts.length > 1) ini += parts[parts.length - 1][0];
    return ini.toUpperCase();
  }

  function stars(n) {
    var out = '';
    for (var i = 1; i <= 5; i++) out += i <= n ? '\u2605' : '\u2606';
    return out;
  }

  function injectStyles() {
    if (document.getElementById('pfs-widget-styles')) return;
    var css = [
      '.pfs-wall{display:grid;gap:20px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));}',
      '.pfs-card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:22px;display:flex;flex-direction:column;gap:12px;box-shadow:0 1px 4px rgba(0,0,0,.06);}',
      '.pfs-stars{color:#f59e0b;font-size:15px;letter-spacing:1px;}',
      '.pfs-text{font-size:14px;color:#374151;line-height:1.65;flex:1;}',
      '.pfs-text::before{content:open-quote;}',
      '.pfs-text::after{content:close-quote;}',
      '.pfs-author{display:flex;align-items:center;gap:12px;margin-top:4px;}',
      '.pfs-avatar,.pfs-avatar-ini{width:44px;height:44px;border-radius:50%;object-fit:cover;flex-shrink:0;}',
      '.pfs-avatar-ini{background:#2563eb;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;}',
      '.pfs-author-info strong{display:block;font-size:14px;color:#111827;}',
      '.pfs-author-info small{font-size:12px;color:#6b7280;}',
    ].join('');
    var el = document.createElement('style');
    el.id = 'pfs-widget-styles';
    el.textContent = css;
    document.head.appendChild(el);
  }

  function render(container, testimonials) {
    var max = parseInt(container.getAttribute('data-max'), 10) || testimonials.length;
    var items = testimonials.slice(0, max);

    if (!items.length) { container.innerHTML = ''; return; }

    var cards = items.map(function (t) {
      var avatar = t.photo_url
        ? '<img class="pfs-avatar" src="' + esc(t.photo_url) + '" alt="' + esc(t.name) + '">'
        : '<div class="pfs-avatar-ini">' + esc(initials(t.name)) + '</div>';

      var meta = '<strong>' + esc(t.name) + '</strong>';
      var sub = [t.job_title, t.company].filter(Boolean).map(esc).join(' · ');
      if (sub) meta += '<small>' + sub + '</small>';

      return [
        '<div class="pfs-card">',
        '<div class="pfs-stars">' + stars(t.rating) + '</div>',
        '<p class="pfs-text">' + esc(t.text) + '</p>',
        '<div class="pfs-author">' + avatar + '<div class="pfs-author-info">' + meta + '</div></div>',
        '</div>',
      ].join('');
    });

    container.innerHTML = '<div class="pfs-wall">' + cards.join('') + '</div>';
    injectStyles();
  }

  function init() {
    var container = document.getElementById('pfs-testimonials');
    if (!container) return;

    fetch(BASE_URL + '/api/testimonials')
      .then(function (r) { return r.json(); })
      .then(function (data) { render(container, data); })
      .catch(function (e) { console.warn('[pfs-widget] blad:', e); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
