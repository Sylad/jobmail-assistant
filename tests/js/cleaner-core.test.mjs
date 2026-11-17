// L4 — logique pure du nettoyeur (frontend/src/cleaner/cleaner-core.ts), utilisée par
// CleanerApp.vue : ce qui part au déplacement, retrait du panneau de scan, message vide.
// Node ≥ 22.18 lit le TypeScript sans compilation (types effacés). Données fictives seulement.
import test from 'node:test';
import assert from 'node:assert/strict';

const core = await import('../../frontend/src/cleaner/cleaner-core.ts');
const ORDER = ['thunderbird', 'regex', 'parsed_jobs', 'duplicates'];

function candidate(uid, sender, canMove = true) {
  return { uid, sender, can_move: canMove };
}
function result(source, candidates, scanned = candidates.length) {
  return { source, report: { scanned_count: scanned, candidate_count: candidates.length, candidates } };
}
function regexScan() {
  // 48 candidats regex fictifs, dont 8 d'un même expéditeur (le cas mesuré sur la vraie boîte).
  const list = [];
  for (let i = 0; i < 40; i += 1) list.push(candidate(`r${i}`, `liste${i % 5}@club.example`));
  for (let i = 0; i < 8; i += 1) list.push(candidate(`x${i}`, 'promo@boutique.example'));
  return result('regex', list);
}

test('exclure un expéditeur de la phase Règles regex le retire du déplacement (t1)', () => {
  const regex = regexScan();
  const results = { thunderbird: null, regex, parsed_jobs: null, duplicates: null };
  const all = core.initialPhaseSelection(regex);
  assert.equal(all.length, 48);
  // Ce que fait « exclure » sur l'expéditeur : sa sélection de phase perd ses 8 UID.
  const selections = {
    thunderbird: [], parsed_jobs: [], duplicates: [],
    regex: all.filter((uid) => !uid.startsWith('x')),
  };
  const moves = core.planPhaseMoves(ORDER, results, selections);
  assert.deepEqual(moves.map((m) => m.source), ['regex']);
  assert.equal(moves[0].uids.length, 40);
  assert.ok(moves[0].uids.every((uid) => !uid.startsWith('x')));
  assert.equal(core.countPlannedMoves(ORDER, results, selections), 40);
});

test('une phase regex entièrement exclue ne part pas (une liste vide déplacerait tout le scan côté serveur)', () => {
  const regex = regexScan();
  const results = { thunderbird: null, regex, parsed_jobs: null, duplicates: null };
  const selections = { thunderbird: [], regex: [], parsed_jobs: [], duplicates: [] };
  assert.deepEqual(core.planPhaseMoves(ORDER, results, selections), []);
  assert.equal(core.countPlannedMoves(ORDER, results, selections), 0);
});

test('les UID sont dédupliqués entre phases, dans l’ordre des phases, sans phase non scannée', () => {
  const results = {
    thunderbird: result('thunderbird', [candidate('a', 's1'), candidate('b', 's2')]),
    regex: result('regex', [candidate('b', 's2'), candidate('c', 's3')]),
    parsed_jobs: null,
    duplicates: result('duplicates', [candidate('a', 's1')]),
  };
  const selections = { thunderbird: ['a', 'b'], regex: ['b', 'c'], parsed_jobs: ['zz'], duplicates: ['a'] };
  const moves = core.planPhaseMoves(ORDER, results, selections);
  assert.deepEqual(moves, [
    { source: 'thunderbird', uids: ['a', 'b'] },
    { source: 'regex', uids: ['c'] },
  ]);
  assert.equal(core.countPlannedMoves(ORDER, results, selections), 3);
});

test('la sélection initiale ne garde que les candidats déplaçables', () => {
  const r = result('regex', [candidate('a', 's'), candidate('b', 's', false)]);
  assert.deepEqual(core.initialPhaseSelection(r), ['a']);
});

test('le panneau de scan se retire seulement quand les quatre phases sont terminées', () => {
  const done = { thunderbird: 'done', regex: 'done', parsed_jobs: 'done', duplicates: 'done' };
  assert.equal(core.scanPanelVisibleAfterFullScan(ORDER, done, true), false);
  for (const source of ORDER) {
    for (const status of ['idle', 'running', 'cancelled', 'error']) {
      const partial = { ...done, [source]: status };
      assert.equal(core.scanPanelVisibleAfterFullScan(ORDER, partial, true), true, `${source}=${status}`);
    }
  }
  // Un panneau déjà masqué ne réapparaît pas.
  assert.equal(core.scanPanelVisibleAfterFullScan(ORDER, { ...done, regex: 'error' }, false), false);
});

test('message vide : explication propre à « Offres déjà traitées » quand la base n’a aucune offre', () => {
  const special = "Aucun mail d'offre déjà extraite dans la base : cette phase n'a rien à proposer.";
  const generic = 'Aucun candidat trouvé avec ces critères.';
  assert.equal(core.emptyCandidatesMessage(result('parsed_jobs', [], 0)), special);
  // Mails scannés mais aucun candidat : critère, pas base vide.
  assert.equal(core.emptyCandidatesMessage(result('parsed_jobs', [], 12)), generic);
  for (const source of ['thunderbird', 'regex', 'duplicates']) {
    assert.equal(core.emptyCandidatesMessage(result(source, [], 0)), generic, source);
  }
  assert.equal(core.emptyCandidatesMessage(null), generic);
});
