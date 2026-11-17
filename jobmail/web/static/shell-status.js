/*
 * L5/t2 — état du gabarit (barre latérale et ligne d'état du téléphone) tenu à jour SANS
 * recharger la page : l'ancien <meta http-equiv="refresh" content="8"> faisait perdre le
 * défilement, le focus et les filtres (WCAG 2.2.1). La page scrute /api/shell-status : toutes
 * les 8 s pendant un traitement, toutes les 30 s au repos (un traitement lancé ailleurs finit
 * par se voir), jamais quand l'onglet est caché.
 *
 * Les textes viennent du serveur (`_shell_status`, jobmail/web/app.py) : ce script ne fait
 * que les recopier. Script classique, sans build, qui expose `window.JobmailShell` ;
 * logique pure testée par `node --test tests/js/shell-status.test.mjs`.
 */
(function (root) {
  'use strict';

  var RUNNING_DELAY = 8000;
  var IDLE_DELAY = 30000;
  var CONN_STATES = ['ok', 'warn', 'off'];

  /** Délai avant la prochaine scrutation, ou null pour ne pas scruter (onglet caché). */
  function nextDelay(status, hidden) {
    if (hidden) return null;
    return status && status.running ? RUNNING_DELAY : IDLE_DELAY;
  }

  /** Vrai quand un traitement vient de finir : les données affichées par la page sont périmées. */
  function justFinished(previous, current) {
    return Boolean(previous && previous.running && current && !current.running);
  }

  /** Classe de couleur d'une connexion ; un état inconnu reste neutre. */
  function connClass(state) {
    return 'conn-' + (CONN_STATES.indexOf(state) >= 0 ? state : 'off');
  }

  /** Largeur de la barre d'avancement, ou null pour la masquer. */
  function progressWidth(status) {
    if (!status || !status.running || typeof status.progress !== 'number') return null;
    return Math.max(0, Math.min(100, Math.round(status.progress)));
  }

  /**
   * Adresse du lien « Traitement terminé · recharger la page » (correction de revue L5).
   * Page venue d'un GET : son adresse SANS #fragment (un lien vers la même adresse avec
   * fragment ne fait que défiler, sans recharger). Page rendue par un POST : la page GET
   * donnée par le serveur (`_shell_reload_target`), jamais le renvoi du formulaire (405).
   */
  function reloadHref(locationHref, method, fallback) {
    if (method === 'GET') {
      var hash = String(locationHref).indexOf('#');
      return hash >= 0 ? String(locationHref).slice(0, hash) : String(locationHref);
    }
    return fallback || '/';
  }

  var api = {
    reloadHref: reloadHref,
    nextDelay: nextDelay,
    justFinished: justFinished,
    connClass: connClass,
    progressWidth: progressWidth,
    RUNNING_DELAY: RUNNING_DELAY,
    IDLE_DELAY: IDLE_DELAY,
  };
  root.JobmailShell = api;

  if (typeof document === 'undefined' || typeof fetch === 'undefined') return;

  function setText(selector, text) {
    document.querySelectorAll(selector).forEach(function (el) {
      if (el.textContent !== text) el.textContent = text;
    });
  }

  function apply(status, finished) {
    document.querySelectorAll('[data-shell-status]').forEach(function (box) {
      box.classList.toggle('is-running', Boolean(status.running));
      var dot = box.querySelector('.live-dot');
      if (dot) dot.classList.toggle('live-dot-idle', !status.running);
    });
    setText('[data-shell-label]', status.label);
    setText('[data-shell-detail]', status.summary);
    document.querySelectorAll('[data-shell-meta]').forEach(function (el) {
      if (el.textContent !== status.meta) el.textContent = status.meta;
      el.hidden = !status.meta;
    });
    setText('[data-shell-ollama-label]', status.ollama.label);
    setText('[data-shell-ollama-detail]', status.ollama.model);
    document.querySelectorAll('[data-shell-ollama]').forEach(function (el) {
      CONN_STATES.forEach(function (s) { el.classList.remove('conn-' + s); });
      el.classList.add(connClass(status.ollama.state));
    });
    document.querySelectorAll('[data-shell-progress]').forEach(function (bar) {
      var width = progressWidth(status);
      bar.hidden = width === null;
      if (width === null) {
        bar.removeAttribute('aria-valuenow');
        return;
      }
      bar.setAttribute('aria-valuenow', String(width));
      var fill = bar.firstElementChild;
      if (fill) fill.style.width = width + '%';
    });
    if (finished) {
      document.querySelectorAll('[data-shell-done]').forEach(function (link) {
        link.href = reloadHref(window.location.href, reload.method, reload.href);
        link.hidden = false;
      });
    }
  }

  var current = null;
  try {
    current = JSON.parse(document.getElementById('jm-shell-status').textContent);
  } catch (_e) {
    current = null;
  }
  var reload = { method: 'GET', href: '/' };
  var reloadEl = document.getElementById('jm-shell-reload');
  if (reloadEl) {
    reload = { method: reloadEl.getAttribute('data-method') || 'GET', href: reloadEl.getAttribute('data-href') || '/' };
  }
  var timer = null;

  function schedule() {
    if (timer) window.clearTimeout(timer);
    timer = null;
    var delay = nextDelay(current, document.hidden);
    if (delay !== null) timer = window.setTimeout(poll, delay);
  }

  function poll() {
    fetch('/api/shell-status', { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (next) {
        if (next) {
          apply(next, justFinished(current, next));
          current = next;
        }
      })
      .catch(function () { /* réseau coupé : on garde l'état affiché et on réessaie */ })
      .then(schedule);
  }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      schedule();
    } else {
      poll();
    }
  });
  schedule();
})(typeof window !== 'undefined' ? window : globalThis);
