// L4/t5 — « Corbeille scan JobMail » de l'extension Thunderbird : seule la sélection confirmée
// dans /cleaner part à la corbeille. background.js est chargé tel quel dans un contexte isolé,
// avec une fausse API Thunderbird et un faux serveur JobMail : aucun mail réel, aucun réseau.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../../thunderbird-extension/background.js", import.meta.url), "utf8");

function loadExtension({ latestRequest }) {
  const calls = { deleted: [], events: [], notifications: [], fetched: [] };
  let onMessage = null;
  const noop = { addListener() {} };
  const messenger = {
    runtime: { onMessage: { addListener: (fn) => { onMessage = fn; } }, onStartup: noop, onInstalled: noop },
    alarms: { onAlarm: noop, clear: async () => {}, create() {} },
    menus: { create() {}, onClicked: noop },
    storage: { local: { get: async (defaults) => ({ ...defaults }), set: async () => {} } },
    notifications: { create: async (options) => { calls.notifications.push(options.message); } },
    accounts: { list: async () => [] },
    messages: {
      // Chaque Message-Id connu de la fausse boîte donne un identifiant Thunderbird.
      query: async ({ headerMessageId }) => {
        const id = { "<two@example.test>": 12, "<one@example.test>": 11 }[headerMessageId];
        return { messages: id ? [{ id, folder: { type: "inbox", path: "/Inbox", name: "Inbox" } }] : [] };
      },
      continueList: async () => ({ messages: [] }),
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
    throw new Error(`appel inattendu : ${url}`);
  };
  vm.runInNewContext(SOURCE, { messenger, fetch, console: { warn() {} }, Date, Number, Set, Array, JSON, String, Math });
  return { calls, send: (type) => onMessage({ type }) };
}

const candidate = (messageId) => ({ uid: `mbox:a:${messageId}`, message_id: messageId, subject: "Promotion", sender: "n@example.test" });

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
  // Le serveur apprend quelle demande a été exécutée : il la consomme, pas de rejeu.
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
