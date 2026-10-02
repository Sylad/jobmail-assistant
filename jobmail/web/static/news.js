/*
 * L6 — branchement dans la page de la logique de news-core.js (chargé juste avant).
 *
 * Sur chaque page : mémoire de base à la toute première visite, puis pastille du lien
 * « Nouveautés » (nombre d'entrées non vues, dans le nom accessible du lien).
 * Sur /nouveautes : ligne « N nouveautés depuis ta dernière visite », marque « Nouveau »,
 * séparateur « Déjà vu … », puis tout est marqué vu ; bouton « Copier le lien » ; capture
 * agrandie au clavier ; arrivée sur /nouveautes#<slug>.
 *
 * Rien ici ne doit casser une page : stockage absent ou corrompu, presse-papiers refusé,
 * <dialog> non pris en charge — chaque partie se replie sur le comportement natif.
 */
(function () {
  'use strict';
  var N = window.JobmailNews;
  if (!N) return;

  function attempt(fn) {
    try { fn(); } catch (e) { /* une partie en échec ne bloque pas les autres */ }
  }

  var indexEl = document.getElementById('jm-news-index');
  var entries = N.parseIndex(indexEl ? indexEl.textContent : '[]');
  var storage = N.browserStorage();
  var newsPage = document.querySelector('.news-page');

  function renderBadge(count) {
    var label = N.badgeLabel(count);
    document.querySelectorAll('[data-news-badge]').forEach(function (b) {
      b.textContent = label;
      b.classList.toggle('is-on', label !== '');
    });
    document.querySelectorAll('[data-news-badge-sr]').forEach(function (s) {
      s.textContent = N.badgeSrLabel(count);
    });
  }

  // ── Autre onglet : Nouveautés visitée ailleurs (ou mémoire effacée) → pastille à jour ──
  window.addEventListener('storage', function (event) {
    if (!N.isSeenStorageEvent(event)) return;
    attempt(function () { renderBadge(N.badgeAfterStorageChange(storage, entries)); });
  });

  // ── Pastille (toutes les pages sauf /nouveautes, qui marque tout comme vu) ─────────
  if (!newsPage) {
    attempt(function () {
      N.ensureBaseline(storage, entries);
      renderBadge(N.countUnseen(entries, N.readSeen(storage)));
    });
    return;
  }

  var articles = Array.prototype.slice.call(newsPage.querySelectorAll('article.news-entry'));

  // ── Dernière visite ───────────────────────────────────────────────────────────────
  attempt(function () {
    var seen = N.readSeen(storage);
    var listed = articles.map(function (a) {
      var t = a.querySelector('time');
      return { slug: a.id, date: t ? t.getAttribute('datetime') : '' };
    });
    var fresh = listed.map(function (e) { return N.isUnseen(e, seen); });
    var count = fresh.filter(Boolean).length;

    articles.forEach(function (a, i) {
      var slot = a.querySelector('.news-new-slot');
      if (!slot || !fresh[i]) return;
      var mark = document.createElement('span');
      mark.className = 'news-new';
      mark.textContent = 'Nouveau';
      slot.appendChild(mark);
    });
    var since = newsPage.querySelector('.news-since');
    if (since) since.textContent = N.sinceLabel(count, seen);

    var at = seen ? N.seenSeparatorIndex(fresh) : -1;
    if (at > 0) {
      var sep = document.createElement('p');
      sep.className = 'news-seen-sep';
      var text = document.createElement('span');
      text.textContent = N.seenSeparatorLabel(seen);
      sep.appendChild(text);
      articles[at].parentNode.insertBefore(sep, articles[at]);
    }
    N.markAllSeen(storage, entries.length ? entries : listed);
  });
  attempt(function () { renderBadge(0); });

  // ── Copier le lien ────────────────────────────────────────────────────────────────
  // Copie seulement : ni défilement ni changement d'adresse. Le retour remplace le libellé
  // dans une case de largeur réservée ; annonce pour lecteur d'écran. Copie refusée :
  // l'adresse s'affiche sous le titre, sélectionnable.
  var copyStatus = document.getElementById('news-copy-status');
  var timers = new WeakMap();

  function setState(btn, state) {
    btn.dataset.state = state;
    btn.querySelectorAll('.news-copy-label').forEach(function (l) {
      l.classList.toggle('is-hidden', l.dataset.for !== state);
    });
  }

  function showAddress(article, url) {
    var box = article && article.querySelector('.news-permalink');
    if (!box) return;
    box.querySelector('.news-permalink-url').textContent = url;
    box.hidden = false;
  }

  function copied(btn, ok, url) {
    setState(btn, ok ? 'ok' : 'ko');
    if (!ok) showAddress(btn.closest('article'), url);
    if (copyStatus) {
      copyStatus.textContent = ok
        ? 'Lien copié dans le presse-papiers'
        : 'Copie impossible : l’adresse est affichée sous le titre';
    }
    clearTimeout(timers.get(btn));
    timers.set(btn, setTimeout(function () {
      setState(btn, 'idle');
      if (copyStatus) copyStatus.textContent = '';
    }, 4000));
  }

  document.addEventListener('click', function (event) {
    var btn = event.target && event.target.closest && event.target.closest('button.news-copy');
    if (!btn) return;
    var url = N.permalink(location.origin, btn.dataset.slug || '');
    var clip = navigator.clipboard;
    if (!clip || typeof clip.writeText !== 'function') {
      copied(btn, false, url);
      return;
    }
    clip.writeText(url).then(
      function () { copied(btn, true, url); },
      function () { copied(btn, false, url); }
    );
  });

  // ── Capture agrandie ──────────────────────────────────────────────────────────────
  // Entrée sur le lien (ou clic) ouvre, Échap ou « Fermer » referme, le focus revient au
  // lien. Sans <dialog>, le lien ouvre simplement l'image.
  attempt(function () {
    var dialog = document.querySelector('dialog.news-lightbox');
    if (!dialog || typeof dialog.showModal !== 'function') return;
    var img = dialog.querySelector('.news-lightbox-img');
    var caption = dialog.querySelector('.news-lightbox-caption');
    var opener = null;

    document.addEventListener('click', function (event) {
      var link = event.target && event.target.closest && event.target.closest('a[data-lightbox]');
      if (!link) return;
      var thumb = link.querySelector('img');
      if (!thumb) return;
      event.preventDefault();
      opener = link;
      img.src = link.getAttribute('href');
      img.alt = thumb.alt;
      caption.textContent = thumb.alt;
      dialog.showModal();
      dialog.querySelector('.news-lightbox-close').focus();
    });
    dialog.querySelector('.news-lightbox-close').addEventListener('click', function () {
      dialog.close();
    });
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener('close', function () {
      img.removeAttribute('src');
      if (opener) opener.focus();
      opener = null;
    });
  });

  // ── Arrivée sur /nouveautes#<slug> ────────────────────────────────────────────────
  // L'entrée est signalée, défilée sous le haut de l'écran (scroll-margin-top) et reçoit
  // le focus ; défilement refait ici car la ligne d'état a pu décaler la page.
  function revealTarget() {
    var slugs = articles.map(function (a) { return a.id; });
    var slug = N.entryForFragment(location.hash, slugs);
    articles.forEach(function (a) { a.classList.toggle('is-target', a.id === slug); });
    if (!slug) return;
    var target = document.getElementById(slug);
    target.scrollIntoView({ block: 'start' });
    target.focus({ preventScroll: true });
  }
  attempt(revealTarget);
  window.addEventListener('hashchange', function () { attempt(revealTarget); });
})();
