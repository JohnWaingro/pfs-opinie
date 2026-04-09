/**
 * Print Flow Solutions — widget opinii
 *
 * Uzycie na stronie:
 *   <div id="pfs-testimonials"></div>
 *   <script src="https://pfs-opinie.onrender.com/static/widget.js"></script>
 *
 * Opcjonalne atrybuty na divie:
 *   data-max="6"   — max liczba opinii (domyslnie wszystkie)
 */
(function () {
  'use strict';

  var SCRIPT_SRC = (function () {
    var scripts = document.getElementsByTagName('script');
    return scripts[scripts.length - 1].src;
  })();
  var BASE_URL = SCRIPT_SRC.replace(/\/static\/widget\.js.*$/, '');

  function esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function initials(name) {
    var parts = (name || '').trim().split(/\s+/);
    return ((parts[0] || '')[0] + ((parts[1] || '')[0] || '')).toUpperCase();
  }

  function stars(n) {
    var s = '';
    for (var i = 1; i <= 5; i++) s += i <= n ? '\u2605' : '\u2606';
    return s;
  }

  function injectStyles() {
    if (document.getElementById('pfs-widget-styles')) return;
    var css = `
      .pfs-wall {
        display: grid;
        gap: 20px;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      }
      .pfs-card {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        box-shadow: 0 1px 4px rgba(0,0,0,.06);
        transition: box-shadow .2s, transform .2s;
      }
      .pfs-card:hover {
        box-shadow: 0 6px 20px rgba(0,0,0,.1);
        transform: translateY(-2px);
      }
      .pfs-stars { color: #f59e0b; font-size: 14px; letter-spacing: 1px; }
      .pfs-text {
        font-size: 14px;
        color: #374151;
        line-height: 1.7;
        flex: 1;
        font-style: italic;
      }
      .pfs-text::before { content: '\u201e'; }
      .pfs-text::after  { content: '\u201d'; }
      .pfs-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
      .pfs-author { display: flex; align-items: center; gap: 10px; }
      .pfs-avatar, .pfs-avatar-ini {
        width: 40px; height: 40px;
        border-radius: 50%;
        object-fit: cover;
        flex-shrink: 0;
      }
      .pfs-avatar-ini {
        background: linear-gradient(135deg, #0353a4, #00b4d8);
        color: #fff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 14px;
      }
      .pfs-author-info strong { display: block; font-size: 13.5px; color: #111; }
      .pfs-author-info small  { font-size: 12px; color: #6b7280; }
      .pfs-logo {
        height: 32px;
        max-width: 80px;
        object-fit: contain;
        opacity: .85;
        flex-shrink: 0;
      }
    `;
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
        ? '<img class="pfs-avatar" src="' + esc(t.photo_url) + '" alt="' + esc(t.name) + '" loading="lazy">'
        : '<div class="pfs-avatar-ini" aria-hidden="true">' + esc(initials(t.name)) + '</div>';

      var authorInfo = '<strong>' + esc(t.name) + '</strong>';
      var sub = [t.job_title, t.company].filter(Boolean).map(esc).join(' &middot; ');
      if (sub) authorInfo += '<small>' + sub + '</small>';

      var logo = t.logo_url
        ? '<img class="pfs-logo" src="' + esc(t.logo_url) + '" alt="' + esc(t.company || '') + '" loading="lazy">'
        : '';

      return [
        '<article class="pfs-card">',
        '<div class="pfs-stars">' + stars(t.rating) + '</div>',
        '<p class="pfs-text">' + esc(t.text) + '</p>',
        '<div class="pfs-footer">',
        '<div class="pfs-author">' + avatar + '<div class="pfs-author-info">' + authorInfo + '</div></div>',
        logo,
        '</div>',
        '</article>',
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
      .catch(function (e) { console.warn('[pfs-widget]', e); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
