// L6 — logique pure de la pastille et de la page Nouveautés (static/news-core.js).
// Lancé par `node --test tests/js/` (Node ≥ 20, sans dépendance) ; tests/test_js.py le
// lance aussi depuis pytest quand Node est installé.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const SRC = readFileSync(`${ROOT}jobmail/web/static/news-core.js`, 'utf8');
const CASES = JSON.parse(readFileSync(`${ROOT}tests/fixtures/date-format-cases.json`, 'utf8'));

// Script classique (pas de module), exécuté comme le navigateur le ferait : il pose
// globalThis.JobmailNews (sans window ni DOM).
vm.runInThisContext(SRC, { filename: 'news-core.js' });
const N = globalThis.JobmailNews;

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
    dump: () => Object.fromEntries(data),
  };
}
const throwingStorage = {
  getItem() { throw new Error('denied'); },
  setItem() { throw new Error('quota'); },
  removeItem() { throw new Error('denied'); },
};

const E = (slug, date) => ({ slug, date });
const NOW = new Date('2026-10-02T18:42:00Z');

test('clé de stockage propre à l’application', () => {
  assert.equal(N.NEWS_SEEN_KEY, 'jobmail.news.seen-v1');
});

test('dates : mêmes cas que le formateur Python (1er, espaces insécables)', () => {
  for (const [day, expected] of CASES.days) assert.equal(N.formatDay(day), expected);
  for (const [iso, expected] of CASES.times) assert.equal(N.formatTime(new Date(iso), 'UTC'), expected);
});

test('première visite de n’importe quelle page : mémoire de base, aucune pastille', () => {
  const s = memoryStorage();
  const entries = [E('b', '2026-10-02'), E('a', '2026-10-01')];
  assert.equal(N.ensureBaseline(s, entries, NOW), true);
  const seen = N.readSeen(s);
  assert.equal(seen.baseline, true);
  assert.deepEqual(seen.slugs, ['a', 'b']);
  assert.equal(N.countUnseen(entries, seen), 0);
  // Une mémoire existante n'est jamais écrasée.
  assert.equal(N.ensureBaseline(s, [...entries, E('c', '2026-10-03')], NOW), false);
});

test('première visite sans aucune entrée : la première publiée lèvera la pastille', () => {
  const s = memoryStorage();
  N.ensureBaseline(s, [], NOW);
  assert.equal(N.countUnseen([E('a', '2026-10-01')], N.readSeen(s)), 1);
});

test('entrée publiée plus tard : pastille sans ouvrir Nouveautés ; entrée antidatée comptée aussi', () => {
  const s = memoryStorage();
  N.ensureBaseline(s, [E('a', '2026-10-01')], NOW);
  const later = [E('c', '2026-10-03'), E('a', '2026-10-01'), E('old', '2026-09-01')];
  const seen = N.readSeen(s);
  assert.equal(N.countUnseen(later, seen), 2);
  assert.equal(N.isUnseen(E('old', '2026-09-01'), seen), true);
});

test('visite de Nouveautés : tout est vu, la mémoire n’est plus la mémoire de base', () => {
  const s = memoryStorage();
  N.ensureBaseline(s, [], NOW);
  const entries = [E('b', '2026-10-02'), E('a', '2026-10-01')];
  N.markAllSeen(s, entries, NOW);
  const seen = N.readSeen(s);
  assert.equal(seen.baseline, undefined);
  assert.equal(seen.at, NOW.toISOString());
  assert.equal(N.countUnseen(entries, seen), 0);
});

test('mémoire absente (premier visiteur) : rien n’est nouveau', () => {
  assert.equal(N.isUnseen(E('a', '2026-10-01'), null), false);
});

test('stockage corrompu ou indisponible : jamais d’exception', () => {
  for (const raw of ['{', 'null', '42', '"x"', '{"date":"hier","slugs":[]}', '{"date":"2026-10-01"}']) {
    const s = memoryStorage({ 'jobmail.news.seen-v1': raw });
    assert.equal(N.readSeen(s), null, raw);
    assert.equal(N.ensureBaseline(s, [E('a', '2026-10-01')], NOW), true, raw);
  }
  assert.equal(N.readSeen(throwingStorage), null);
  assert.equal(N.ensureBaseline(throwingStorage, [E('a', '2026-10-01')], NOW), false);
  assert.doesNotThrow(() => N.markAllSeen(throwingStorage, [E('a', '2026-10-01')], NOW));
  assert.equal(N.readSeen(null), null);
  const s = memoryStorage({ 'jobmail.news.seen-v1': '{"date":"2026-10-01","slugs":[1,"a",null],"all":true}' });
  assert.deepEqual(N.readSeen(s).slugs, ['a']);
});

test('pastille : nombre, « 9+ » au-delà de neuf, nom accessible', () => {
  assert.equal(N.badgeLabel(0), '');
  assert.equal(N.badgeLabel(1), '1');
  assert.equal(N.badgeLabel(9), '9');
  assert.equal(N.badgeLabel(10), '9+');
  assert.equal(N.badgeSrLabel(0), '');
  assert.equal(N.badgeSrLabel(1), ' (1 nouveauté non vue)');
  assert.equal(N.badgeSrLabel(2), ' (2 nouveautés non vues)');
});

test('ligne d’état de la page', () => {
  assert.equal(N.sinceLabel(0), '');
  assert.equal(N.sinceLabel(1), '1 nouveauté depuis ta dernière visite');
  assert.equal(N.sinceLabel(3), '3 nouveautés depuis ta dernière visite');
});

test('séparateur : seulement si toutes les nouvelles sont au-dessus', () => {
  assert.equal(N.seenSeparatorIndex([true, true, false, false]), 2);
  assert.equal(N.seenSeparatorIndex([false, false]), -1);
  assert.equal(N.seenSeparatorIndex([true, true]), -1);
  assert.equal(N.seenSeparatorIndex([true, false, true]), -1);
});

test('séparateur : libellé de visite, libellé honnête pour la mémoire de base', () => {
  const at = '2026-10-02T18:42:00Z';
  assert.equal(
    N.seenSeparatorLabel({ date: '2026-10-01', slugs: [], at, all: true }, 'UTC'),
    'Déjà vu lors de ta visite du 2 octobre 2026 à 18 h 42',
  );
  assert.equal(
    N.seenSeparatorLabel({ date: '2026-10-01', slugs: [], at: '2026-10-01T07:05:00Z', all: true, baseline: true }, 'UTC'),
    'Déjà publié lors de ta première visite, le 1er octobre 2026 à 7 h 05',
  );
  assert.equal(N.seenSeparatorLabel({ date: '2026-10-01', slugs: [] }), 'Déjà vu lors d’une visite précédente');
});

test('lien permanent et ancre', () => {
  assert.equal(N.permalink('http://127.0.0.1:8765', '2026-10-02-une-page'), 'http://127.0.0.1:8765/nouveautes#2026-10-02-une-page');
  const slugs = ['2026-10-02-une-page', 'é-accent'];
  assert.equal(N.entryForFragment('#2026-10-02-une-page', slugs), '2026-10-02-une-page');
  assert.equal(N.entryForFragment('#%C3%A9-accent', slugs), 'é-accent');
  assert.equal(N.entryForFragment('#inconnu', slugs), null);
  assert.equal(N.entryForFragment('#%E0%A4%A', slugs), null);
  assert.equal(N.entryForFragment('', slugs), null);
});

test('index des Nouveautés lu dans la page : illisible = liste vide', () => {
  assert.deepEqual(N.parseIndex('[{"slug":"a","date":"2026-10-01"},{"slug":2},"x"]'), [E('a', '2026-10-01')]);
  assert.deepEqual(N.parseIndex('{'), []);
  assert.deepEqual(N.parseIndex(null), []);
});

test('autre onglet : seul un changement de la mémoire des Nouveautés recalcule la pastille', () => {
  assert.equal(N.isSeenStorageEvent({ key: 'jobmail.news.seen-v1' }), true);
  assert.equal(N.isSeenStorageEvent({ key: null }), true); // localStorage.clear() ailleurs
  assert.equal(N.isSeenStorageEvent({ key: 'autre.cle' }), false);
  assert.equal(N.isSeenStorageEvent(null), false);
});

test('autre onglet : la visite de Nouveautés ailleurs éteint la pastille ici', () => {
  const s = memoryStorage();
  const entries = [E('b', '2026-10-02'), E('a', '2026-10-01')];
  N.ensureBaseline(s, [E('a', '2026-10-01')], NOW);
  assert.equal(N.badgeAfterStorageChange(s, entries), 1);
  N.markAllSeen(s, entries, NOW); // l'autre onglet ouvre Nouveautés
  assert.equal(N.badgeAfterStorageChange(s, entries), 0);
  assert.equal(N.badgeAfterStorageChange(throwingStorage, entries), 0);
});

test('ligne d’état : « première visite » quand la mémoire n’est que la mémoire de base', () => {
  const baseline = { date: '2026-10-01', slugs: [], at: '2026-10-01T07:05:00Z', all: true, baseline: true };
  const visit = { date: '2026-10-01', slugs: [], at: '2026-10-01T07:05:00Z', all: true };
  assert.equal(N.sinceLabel(1, baseline), '1 nouveauté depuis ta première visite');
  assert.equal(N.sinceLabel(2, baseline), '2 nouveautés depuis ta première visite');
  assert.equal(N.sinceLabel(2, visit), '2 nouveautés depuis ta dernière visite');
  assert.equal(N.sinceLabel(0, baseline), '');
});
