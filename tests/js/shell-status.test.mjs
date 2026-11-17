// L5/t2 — logique pure de la scrutation de l'état du gabarit (static/shell-status.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const SRC = readFileSync(`${ROOT}jobmail/web/static/shell-status.js`, 'utf8');

function load() {
  const ctx = vm.createContext({});
  vm.runInContext(SRC, ctx);
  return ctx.JobmailShell;
}

test('scrute toutes les 8 s pendant un traitement, 30 s au repos, jamais onglet caché', () => {
  const s = load();
  assert.equal(s.nextDelay({ running: true }, false), 8000);
  assert.equal(s.nextDelay({ running: false }, false), 30000);
  assert.equal(s.nextDelay(null, false), 30000);
  assert.equal(s.nextDelay({ running: true }, true), null);
});

test('signale la fin d’un traitement, une seule transition', () => {
  const s = load();
  assert.equal(s.justFinished({ running: true }, { running: false }), true);
  assert.equal(s.justFinished({ running: false }, { running: false }), false);
  assert.equal(s.justFinished({ running: false }, { running: true }), false);
  assert.equal(s.justFinished(null, { running: false }), false);
});

test('classe de connexion : état connu ou neutre', () => {
  const s = load();
  assert.equal(s.connClass('ok'), 'conn-ok');
  assert.equal(s.connClass('warn'), 'conn-warn');
  assert.equal(s.connClass('bizarre'), 'conn-off');
});

test('barre d’avancement : bornée, masquée sans avancement ou au repos', () => {
  const s = load();
  assert.equal(s.progressWidth({ running: true, progress: 42.4 }), 42);
  assert.equal(s.progressWidth({ running: true, progress: 140 }), 100);
  assert.equal(s.progressWidth({ running: true, progress: null }), null);
  assert.equal(s.progressWidth({ running: false, progress: 50 }), null);
});

// Correction de revue L5 : le lien « recharger la page » ne doit ni renvoyer un POST (405)
// ni se réduire à un saut d'ancre quand l'adresse porte un #fragment.
test('recharger : GET de l’adresse sans fragment pour une page venue d’un GET', () => {
  const s = load();
  assert.equal(s.reloadHref('http://h/nouveautes#ma-note', 'GET', '/nouveautes'), 'http://h/nouveautes');
  assert.equal(s.reloadHref('http://h/?status=new#x', 'GET', '/'), 'http://h/?status=new');
  assert.equal(s.reloadHref('http://h/plan-de-travail', 'GET', '/plan-de-travail'), 'http://h/plan-de-travail');
  assert.equal(s.reloadHref('http://h/a#', 'GET', '/a'), 'http://h/a');
});

test('recharger : une page venue d’un POST repart sur la page GET donnée par le serveur', () => {
  const s = load();
  assert.equal(s.reloadHref('http://h/cleaner/scan', 'POST', '/cleaner'), '/cleaner');
  assert.equal(s.reloadHref('http://h/cleaner/backups/cleanup#r', 'POST', '/cleaner'), '/cleaner');
  assert.equal(s.reloadHref('http://h/cleaner/scan', 'POST', ''), '/');
});
