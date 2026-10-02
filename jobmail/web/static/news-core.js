/*
 * L6 — logique pure des Nouveautés : mémoire « vu / pas vu » (localStorage), pastille du
 * menu, ligne d'état, séparateur « Déjà vu … », lien permanent, dates en français.
 * Repris du modèle des apps sœurs (evatosorus news-badge / news-anchor / format-date),
 * en JavaScript simple servi tel quel : pas de build, pas de framework. Script classique
 * qui expose `window.JobmailNews` ; testé par `node --test tests/js/`.
 *
 * Mémoire : { date, slugs, at, all: true, baseline? }. `slugs` porte TOUS les slugs vus,
 * donc une entrée antidatée reste nouvelle. `baseline: true` = mémoire posée à la toute
 * première page vue (n'importe laquelle), pas lors d'une visite des Nouveautés.
 */
(function (root) {
  'use strict';

  var NEWS_SEEN_KEY = 'jobmail.news.seen-v1';
  var NBSP = ' ';
  var DATE_OR_INSTANT = /^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z)?$/;

  function instant(d) {
    return typeof d === 'string' && DATE_OR_INSTANT.test(d) ? Date.parse(d) : NaN;
  }

  // ── Dates (mêmes cas que jobmail/web/dates.py) ──────────────────────────────────

  function formatLongDate(date, timeZone) {
    var opts = { day: 'numeric', month: 'long', year: 'numeric' };
    if (timeZone) opts.timeZone = timeZone;
    var parts = new Intl.DateTimeFormat('fr-FR', opts).formatToParts(date);
    var day = '', month = '', year = '';
    parts.forEach(function (p) {
      if (p.type === 'day') day = p.value === '1' ? '1er' : p.value;
      else if (p.type === 'month') month = p.value;
      else if (p.type === 'year') year = p.value;
    });
    return [day, month, year].join(NBSP);
  }

  /** Jour calendaire « AAAA-MM-JJ » (midi UTC : jamais la veille). */
  function formatDay(day) {
    return formatLongDate(new Date(day + 'T12:00:00Z'), 'UTC');
  }

  /** « 20 h 42 », « 9 h 05 » (fuseau du navigateur par défaut). */
  function formatTime(date, timeZone) {
    var opts = { hour: 'numeric', minute: '2-digit', hourCycle: 'h23' };
    if (timeZone) opts.timeZone = timeZone;
    var h = '', m = '';
    new Intl.DateTimeFormat('fr-FR', opts).formatToParts(date).forEach(function (p) {
      if (p.type === 'hour') h = String(Number(p.value));
      else if (p.type === 'minute') m = p.value;
    });
    return h + NBSP + 'h' + NBSP + m;
  }

  // ── Mémoire ─────────────────────────────────────────────────────────────────────

  function readSeen(storage) {
    if (!storage) return null;
    try {
      var raw = storage.getItem(NEWS_SEEN_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
      if (isNaN(instant(parsed.date)) || !Array.isArray(parsed.slugs)) return null;
      var seen = {
        date: parsed.date,
        slugs: parsed.slugs.filter(function (s) { return typeof s === 'string'; }),
      };
      if (typeof parsed.at === 'string' && !isNaN(Date.parse(parsed.at))) seen.at = parsed.at;
      if (parsed.all === true) seen.all = true;
      if (parsed.baseline === true) seen.baseline = true;
      return seen;
    } catch (e) {
      return null;
    }
  }

  function write(storage, seen) {
    if (!storage) return false;
    try {
      storage.setItem(NEWS_SEEN_KEY, JSON.stringify(seen));
      return true;
    } catch (e) {
      return false; // stockage plein ou refusé : la pastille restera, la page fonctionne
    }
  }

  function snapshot(entries, now, baseline) {
    var date = '1970-01-01';
    entries.forEach(function (e) { if (instant(e.date) > instant(date)) date = e.date; });
    var seen = {
      date: date,
      slugs: entries.map(function (e) { return e.slug; }).sort(),
      at: now.toISOString(),
      all: true,
    };
    if (baseline) seen.baseline = true;
    return seen;
  }

  /** Visite des Nouveautés : toutes les entrées sont vues. Retourne la mémoire écrite. */
  function markAllSeen(storage, entries, now) {
    var seen = snapshot(entries, now || new Date(), false);
    write(storage, seen);
    return seen;
  }

  /**
   * Toute première page vue (n'importe laquelle) : ce qui est déjà publié compte comme vu,
   * sans pastille. Une mémoire existante n'est jamais écrasée. Vrai si une mémoire a été écrite.
   */
  function ensureBaseline(storage, entries, now) {
    if (!storage || readSeen(storage)) return false;
    return write(storage, snapshot(entries, now || new Date(), true));
  }

  function isUnseen(entry, seen) {
    if (!seen) return false;
    if (seen.slugs.indexOf(entry.slug) !== -1) return false;
    return seen.all === true || instant(entry.date) >= instant(seen.date);
  }

  function countUnseen(entries, seen) {
    return entries.filter(function (e) { return isUnseen(e, seen); }).length;
  }

  // ── Autres onglets ──────────────────────────────────────────────────────────────

  /** Événement `storage` venu d'un autre onglet qui touche la mémoire (ou l'efface). */
  function isSeenStorageEvent(event) {
    return !!event && (event.key === NEWS_SEEN_KEY || event.key === null);
  }

  /** Nombre à afficher après un changement de la mémoire ailleurs (sans poser de base). */
  function badgeAfterStorageChange(storage, entries) {
    return countUnseen(entries, readSeen(storage));
  }

  // ── Libellés ────────────────────────────────────────────────────────────────────

  function badgeLabel(count) {
    if (count <= 0) return '';
    return count > 9 ? '9+' : String(count);
  }

  /** Complément du nom accessible du lien : « Nouveautés (2 nouveautés non vues) ». */
  function badgeSrLabel(count) {
    if (count <= 0) return '';
    return count === 1 ? ' (1 nouveauté non vue)' : ' (' + count + ' nouveautés non vues)';
  }

  function sinceLabel(count) {
    if (count <= 0) return '';
    return count === 1
      ? '1 nouveauté depuis ta dernière visite'
      : count + ' nouveautés depuis ta dernière visite';
  }

  /**
   * Où poser le séparateur (liste du plus récent au plus ancien) : avant la première entrée
   * vue, seulement si toutes les nouvelles sont au-dessus ; sinon -1 (entrée antidatée plus
   * bas : les marques « Nouveau » suffisent, pas de séparateur trompeur).
   */
  function seenSeparatorIndex(fresh) {
    var first = fresh.indexOf(false);
    if (first <= 0) return -1;
    return fresh.slice(first).indexOf(true) !== -1 ? -1 : first;
  }

  function seenSeparatorLabel(seen, timeZone) {
    if (!seen || !seen.at || isNaN(Date.parse(seen.at))) return 'Déjà vu lors d’une visite précédente';
    var d = new Date(seen.at);
    var when = formatLongDate(d, timeZone) + ' à ' + formatTime(d, timeZone);
    return seen.baseline
      ? 'Déjà publié lors de ta première visite, le ' + when
      : 'Déjà vu lors de ta visite du ' + when;
  }

  // ── Lien permanent ──────────────────────────────────────────────────────────────

  function permalink(origin, slug) {
    return origin + '/nouveautes#' + encodeURIComponent(slug);
  }

  function entryForFragment(fragment, slugs) {
    var raw = String(fragment || '').replace(/^#/, '');
    if (!raw) return null;
    var slug;
    try {
      slug = decodeURIComponent(raw);
    } catch (e) {
      return null;
    }
    return slugs.indexOf(slug) !== -1 ? slug : null;
  }

  // ── Entrées ─────────────────────────────────────────────────────────────────────

  /** Index { slug, date } publié dans chaque page ; illisible = liste vide. */
  function parseIndex(text) {
    try {
      var list = JSON.parse(text);
      if (!Array.isArray(list)) return [];
      return list
        .filter(function (e) {
          return e && typeof e.slug === 'string' && !isNaN(instant(e.date));
        })
        .map(function (e) { return { slug: e.slug, date: e.date }; });
    } catch (e) {
      return [];
    }
  }

  function browserStorage() {
    try {
      var s = root.localStorage;
      return s || null;
    } catch (e) {
      return null;
    }
  }

  root.JobmailNews = {
    NEWS_SEEN_KEY: NEWS_SEEN_KEY,
    formatLongDate: formatLongDate,
    formatDay: formatDay,
    formatTime: formatTime,
    readSeen: readSeen,
    markAllSeen: markAllSeen,
    ensureBaseline: ensureBaseline,
    isUnseen: isUnseen,
    countUnseen: countUnseen,
    isSeenStorageEvent: isSeenStorageEvent,
    badgeAfterStorageChange: badgeAfterStorageChange,
    badgeLabel: badgeLabel,
    badgeSrLabel: badgeSrLabel,
    sinceLabel: sinceLabel,
    seenSeparatorIndex: seenSeparatorIndex,
    seenSeparatorLabel: seenSeparatorLabel,
    permalink: permalink,
    entryForFragment: entryForFragment,
    parseIndex: parseIndex,
    browserStorage: browserStorage,
  };
})(typeof window !== 'undefined' ? window : globalThis);
