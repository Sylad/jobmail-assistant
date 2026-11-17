// L4/t5 — « Corbeille scan JobMail » de l'extension Thunderbird : seule la sélection confirmée
// dans /cleaner part à la corbeille. background.js est chargé tel quel dans un contexte isolé,
// avec une fausse API Thunderbird et un faux serveur JobMail : aucun mail réel, aucun réseau.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../../thunderbird-extension/background.js", import.meta.url), "utf8");

// Fausse boîte par défaut : deux mails de l'Inbox, connus par leur Message-Id (Thunderbird
// range `headerMessageId` sans chevrons).
const INBOX = { type: "inbox", path: "/Inbox", name: "Inbox" };
const TRASH = { type: "trash", path: "/Trash", name: "Trash" };
const DEFAULT_BOX = [
  { id: 11, headerMessageId: "one@example.test", folder: INBOX },
  { id: 12, headerMessageId: "two@example.test", folder: INBOX },
];

// `box` : les mails de la fausse boîte. `queryByMessageId` remplace la recherche par Message-Id
// (pour simuler une requête qui échoue ou qui répond à côté). Toute autre recherche (sujet,
// expéditeur, dates : l'ancien repli) rend les mails de l'Inbox, comme le ferait Thunderbird.
// `stored` : ce que le stockage local de l'extension contient déjà ; `scanResult` : la réponse du
// faux serveur à un scan lancé depuis l'extension (t6).
function loadExtension({ latestRequest = { status: 400, body: {} }, box = DEFAULT_BOX, queryByMessageId = null, stored = {}, scanResult = null }) {
  const calls = { deleted: [], events: [], notifications: [], fetched: [], queries: [], stored: [], removed: [] };
  let onMessage = null;
  const noop = { addListener() {} };
  const strip = (value) => String(value || "").replace(/^<|>$/g, "");
  const messenger = {
    runtime: { onMessage: { addListener: (fn) => { onMessage = fn; } }, onStartup: noop, onInstalled: noop },
    alarms: { onAlarm: noop, clear: async () => {}, create() {} },
    menus: { create() {}, onClicked: noop },
    storage: {
      local: {
        get: async (defaults) => ({ ...defaults, ...stored }),
        set: async (values) => { calls.stored.push(values); },
        remove: async (keys) => { calls.removed.push(...[].concat(keys)); },
      },
    },
    notifications: { create: async (options) => { calls.notifications.push(options.message); } },
    accounts: { list: async () => [{ folders: [INBOX, TRASH] }] },
    messages: {
      query: async (queryInfo) => {
        calls.queries.push(queryInfo);
        if (queryInfo.headerMessageId !== undefined) {
          if (queryByMessageId) {
            return queryByMessageId(queryInfo.headerMessageId);
          }
          return { messages: box.filter((header) => header.headerMessageId === strip(queryInfo.headerMessageId)) };
        }
        return { messages: box.filter((header) => header.folder === INBOX) };
      },
      continueList: async () => ({ messages: [] }),
      getFull: async () => ({ headers: {}, parts: [] }),
      listAttachments: async () => [],
      delete: async (ids, options) => { calls.deleted.push({ ids: [...ids], options }); },
    },
  };
  const fetch = async (url, options = {}) => {
    calls.fetched.push(url);
    if (url.endsWith("/api/thunderbird/cleaner/latest-request")) {
      return { ok: latestRequest.status === 200, status: latestRequest.status, json: async () => latestRequest.body };
    }
    if (url.endsWith("/api/thunderbird/bridge/event")) {
      calls.events.push(JSON.parse(options.body));
      return { ok: true, status: 200, json: async () => ({}) };
    }
    if (url.includes("/cleaner/state")) {
      return { ok: true, status: 200, json: async () => ({ min_age_days: 7, max_mails: 500 }) };
    }
    if (url.endsWith("/api/thunderbird/cleaner/scan") && scanResult) {
      return { ok: true, status: 200, json: async () => scanResult };
    }
    throw new Error(`appel inattendu : ${url}`);
  };
  vm.runInNewContext(SOURCE, { messenger, fetch, console: { warn() {} }, Date, Number, Set, Array, JSON, String, Math });
  return { calls, send: (type) => onMessage({ type }) };
}

const candidate = (messageId) => ({
  uid: `mbox:a:${messageId}`,
  message_id: messageId,
  subject: "Promotion",
  sender: "n@example.test",
  received_at: "2026-05-01T08:30:00",
});
const confirmed = (...candidates) => ({
  status: 200,
  body: { request_id: "req", source: "confirmed_selection", candidate_count: candidates.length, candidates },
});

test("sans sélection confirmée (400 du serveur), rien ne part à la corbeille", async () => {
  const { calls, send } = loadExtension({
    latestRequest: { status: 400, body: { detail: "Aucun mail sélectionné : rien n'a été déplacé." } },
  });

  await assert.rejects(send("trash-jobmail-cleaner-request"), /Aucune sélection confirmée/);

  assert.deepEqual(calls.deleted, []);
  assert.deepEqual(calls.events, []);
});

test("une réponse qui n'est pas une sélection confirmée est refusée, même avec des candidats", async () => {
  // Ce que servait le serveur avant t5 : tous les candidats des scans en mémoire.
  const { calls, send } = loadExtension({
    latestRequest: {
      status: 200,
      body: { request_id: "old", source: "latest_cleaner_scan", candidate_count: 2, candidates: [candidate("<one@example.test>"), candidate("<two@example.test>")] },
    },
  });

  await assert.rejects(send("trash-jobmail-cleaner-request"), /Aucune sélection confirmée/);

  assert.deepEqual(calls.deleted, []);
});

test("seuls les mails de la sélection confirmée partent, en corbeille et non en suppression définitive", async () => {
  const { calls, send } = loadExtension({
    latestRequest: {
      status: 200,
      body: { request_id: "req-1", source: "confirmed_selection", candidate_count: 1, candidates: [candidate("<two@example.test>")] },
    },
  });

  const result = await send("trash-jobmail-cleaner-request");

  assert.equal(calls.deleted.length, 1);
  assert.deepEqual(calls.deleted[0].ids, [12]);
  assert.equal(calls.deleted[0].options.deletePermanently, false);
  assert.equal(result.moved_count, 1);
  // Le compte rendu nomme la demande exécutée (le serveur l'a déjà consommée en la servant).
  assert.equal(calls.events[0].event, "cleaner_move");
  assert.equal(calls.events[0].payload.request_id, "req-1");
});

test("une sélection confirmée introuvable dans Thunderbird ne déplace rien", async () => {
  const { calls, send } = loadExtension({
    latestRequest: {
      status: 200,
      body: { request_id: "req-2", source: "confirmed_selection", candidate_count: 1, candidates: [candidate("<absent@example.test>")] },
    },
  });

  const result = await send("trash-jobmail-cleaner-request");

  assert.deepEqual(calls.deleted, []);
  assert.equal(result.moved_count, 0);
  assert.equal(result.missing_count, 1);
});

// ── Revue L4/t5, M1 : un mail se résout par son Message-Id, et par rien d'autre ──
// Avant : quand le Message-Id ne donnait rien, un repli prenait dans l'Inbox le premier mail de
// même sujet et de même expéditeur à ±2 jours, c'est-à-dire un mail que personne n'a sélectionné.

// Le numéro voisin d'une newsletter : même sujet, même expéditeur, le lendemain, autre Message-Id.
const NEIGHBOUR = {
  id: 99,
  headerMessageId: "voisin@example.test",
  subject: "Promotion",
  author: "Newsletter <n@example.test>",
  date: new Date("2026-05-02T08:30:00"),
  folder: INBOX,
};

test("un mail sélectionné déjà en corbeille n'est pas remplacé par son voisin de même sujet", async () => {
  const { calls, send } = loadExtension({
    latestRequest: confirmed(candidate("<two@example.test>")),
    box: [{ id: 12, headerMessageId: "two@example.test", subject: "Promotion", folder: TRASH }, NEIGHBOUR],
  });

  const result = await send("trash-jobmail-cleaner-request");

  assert.deepEqual(calls.deleted, []);
  assert.equal(result.moved_count, 0);
  assert.equal(result.missing_count, 1);
  assert.equal(result.missing[0].subject, "Promotion");
});

test("un candidat sans Message-Id est compté non trouvé, sans recherche par sujet ni expéditeur", async () => {
  const { calls, send } = loadExtension({
    latestRequest: confirmed({ ...candidate(""), uid: "mbox:a:sans-id" }),
    box: [NEIGHBOUR],
  });

  const result = await send("trash-jobmail-cleaner-request");

  assert.deepEqual(calls.deleted, []);
  assert.equal(result.missing_count, 1);
  // Aucune requête autre que par Message-Id n'est même posée à Thunderbird.
  assert.deepEqual(calls.queries.filter((query) => query.headerMessageId === undefined), []);
});

test("une recherche par Message-Id qui échoue ne déplace rien", async () => {
  const { calls, send } = loadExtension({
    latestRequest: confirmed(candidate("<two@example.test>")),
    box: [NEIGHBOUR],
    queryByMessageId: async () => { throw new Error("requête refusée"); },
  });

  const result = await send("trash-jobmail-cleaner-request");

  assert.deepEqual(calls.deleted, []);
  assert.equal(result.missing_count, 1);
});

test("un mail rendu par la recherche avec un autre Message-Id n'est pas déplacé", async () => {
  // Une recherche qui répondrait à côté (filtre ignoré) ne doit pas désigner un autre mail.
  const { calls, send } = loadExtension({
    latestRequest: confirmed(candidate("<two@example.test>")),
    queryByMessageId: async () => ({ messages: [NEIGHBOUR] }),
  });

  const result = await send("trash-jobmail-cleaner-request");

  assert.deepEqual(calls.deleted, []);
  assert.equal(result.missing_count, 1);
});

test("les mails retrouvés partent, le non retrouvé est compté et rien ne le remplace", async () => {
  const { calls, send } = loadExtension({
    latestRequest: confirmed(candidate("<one@example.test>"), candidate("<absent@example.test>")),
    box: [...DEFAULT_BOX, NEIGHBOUR],
  });

  const result = await send("trash-jobmail-cleaner-request");

  assert.deepEqual(calls.deleted.map((call) => call.ids), [[11]]);
  assert.equal(result.requested_count, 2);
  assert.equal(result.moved_count, 1);
  assert.equal(result.missing_count, 1);
});

// ── L4/t6 : l'action « Corbeille candidats » est retirée ──
// Avant : elle envoyait à la corbeille TOUS les candidats du dernier scan lancé depuis l'extension
// (jusqu'à 500, dont 8 seulement affichés dans la fenêtre), sans sélection mail par mail. Le seul
// chemin de déplacement de l'extension est désormais la sélection confirmée dans /cleaner.

const read = (name) => readFileSync(new URL(`../../thunderbird-extension/${name}`, import.meta.url), "utf8");
const SCAN_CANDIDATES = [{ id: "11", subject: "Promotion" }, { id: "12", subject: "Promotion" }];

test("t6 : l'ancien message « trash-cleaner-candidates » ne déplace plus rien, même avec des candidats en mémoire", async () => {
  const { calls, send } = loadExtension({ stored: { cleanerCandidates: SCAN_CANDIDATES } });

  await send("trash-cleaner-candidates");

  assert.deepEqual(calls.deleted, []);
  assert.deepEqual(calls.events, []);
});

test("t6 : le scan lancé depuis l'extension est un aperçu, il ne garde aucune liste à déplacer", async () => {
  const { calls, send } = loadExtension({
    scanResult: { scanned_count: 2, candidate_count: 2, candidates: SCAN_CANDIDATES },
  });

  const result = await send("scan-cleaner");

  assert.equal(result.candidate_count, 2);
  assert.deepEqual(calls.deleted, []);
  assert.deepEqual(calls.stored.filter((values) => "cleanerCandidates" in values), []);
  // Une liste laissée par une version précédente de l'extension est effacée.
  assert.ok(calls.removed.includes("cleanerCandidates"));
});

test("t6 : l'extension n'a qu'un seul appel de mise à la corbeille, celui de la sélection confirmée", () => {
  const source = read("background.js");
  assert.equal(source.split("api.messages.delete(").length - 1, 1);
  assert.doesNotMatch(source, /trashCleanerCandidates|trash-cleaner-candidates/);
  const start = source.indexOf("async function trashJobMailCleanerRequest");
  const end = source.indexOf("async function getLatestCleanerRequest");
  assert.ok(start > 0 && end > start);
  assert.ok(source.slice(start, end).includes("api.messages.delete("));
});

test("t6 : la fenêtre de l'extension n'a plus le bouton « Corbeille candidats » et dit où se fait le déplacement", () => {
  const html = read("popup.html");
  const script = read("popup.js");
  assert.doesNotMatch(html, /Corbeille candidats|id="trash-cleaner"/);
  assert.doesNotMatch(script, /trash-cleaner-candidates|#trash-cleaner"/);
  // Le seul bouton de corbeille restant est celui de la sélection confirmée.
  assert.deepEqual(html.match(/<button[^>]*class="danger"[^>]*>[^<]*/g).map((b) => b.replace(/<[^>]*>/, "")), ["Corbeille scan JobMail"]);
  // Le scan de l'extension s'annonce comme un aperçu et renvoie vers /cleaner.
  assert.match(html, /Aperçu nettoyage/);
  assert.match(script, /Aperçu seulement/);
  assert.match(script, /\/cleaner/);
});

test("t6 : le README de l'extension ne propose plus « Corbeille candidats »", () => {
  const readme = read("README.md");
  assert.doesNotMatch(readme, /`Corbeille candidats` (demande|agit)/);
  assert.match(readme, /`Aperçu nettoyage`/);
  assert.match(readme, /retir/);
});
