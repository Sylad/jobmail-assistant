const api = typeof messenger !== "undefined" ? messenger : browser;
const DEFAULT_ENDPOINT = "http://127.0.0.1:8765";
const DEFAULT_SINCE_DAYS = 14;
const DEFAULT_MAX_MESSAGES = 50;
const AUTO_ALARM = "jobmail-auto-import-unread";

api.runtime.onMessage.addListener((message) => {
  if (message?.type === "import-selected") {
    return importSelectedMessages();
  }
  if (message?.type === "import-unread") {
    return importUnreadMessages();
  }
  if (message?.type === "get-status") {
    return getJobMailStatus();
  }
  if (message?.type === "scan-cleaner") {
    return scanCleanerCandidates();
  }
  if (message?.type === "trash-cleaner-candidates") {
    return trashCleanerCandidates();
  }
  if (message?.type === "trash-jobmail-cleaner-request") {
    return trashJobMailCleanerRequest();
  }
  if (message?.type === "get-options") {
    return getOptions();
  }
  if (message?.type === "save-options") {
    return saveOptions(message.options || {});
  }
  return undefined;
});

api.runtime.onStartup?.addListener(() => {
  restoreAutoImportAlarm();
});

api.runtime.onInstalled?.addListener(() => {
  restoreAutoImportAlarm();
});

api.alarms?.onAlarm.addListener((alarm) => {
  if (alarm.name === AUTO_ALARM) {
    importUnreadMessages({ silent: true }).catch((error) => {
      console.warn("JobMail auto import failed:", error);
    });
  }
});

try {
  api.menus.create({
    id: "jobmail-import-selected",
    title: "Envoyer vers JobMail",
    contexts: ["message_list"],
  });

  api.menus.onClicked.addListener((info) => {
    if (info.menuItemId === "jobmail-import-selected") {
      importSelectedMessages();
    }
  });
} catch (error) {
  console.warn("JobMail menu disabled:", error);
}

async function getEndpoint() {
  const stored = await api.storage.local.get({ endpoint: DEFAULT_ENDPOINT });
  return String(stored.endpoint || DEFAULT_ENDPOINT).replace(/\/$/, "");
}

async function getOptions() {
  return api.storage.local.get({
    endpoint: DEFAULT_ENDPOINT,
    sinceDays: DEFAULT_SINCE_DAYS,
    maxMessages: DEFAULT_MAX_MESSAGES,
    autoImport: false,
    autoMinutes: 15,
  });
}

async function saveOptions(options) {
  const next = {
    endpoint: String(options.endpoint || DEFAULT_ENDPOINT).replace(/\/$/, ""),
    sinceDays: clampNumber(options.sinceDays, 1, 90, DEFAULT_SINCE_DAYS),
    maxMessages: clampNumber(options.maxMessages, 1, 200, DEFAULT_MAX_MESSAGES),
    autoImport: Boolean(options.autoImport),
    autoMinutes: clampNumber(options.autoMinutes, 5, 240, 15),
  };
  await api.storage.local.set(next);
  await configureAutoImportAlarm(next);
  return next;
}

async function restoreAutoImportAlarm() {
  const options = await getOptions();
  await configureAutoImportAlarm(options);
}

async function configureAutoImportAlarm(options) {
  if (!api.alarms) {
    return;
  }
  await api.alarms.clear(AUTO_ALARM);
  if (options.autoImport) {
    api.alarms.create(AUTO_ALARM, {
      delayInMinutes: options.autoMinutes,
      periodInMinutes: options.autoMinutes,
    });
  }
}

async function getSelectedMessages() {
  const [activeTab] = await api.tabs.query({ active: true, currentWindow: true });
  if (!activeTab?.id || !api.mailTabs) {
    return [];
  }

  let page = await api.mailTabs.getSelectedMessages(activeTab.id);
  const selected = [...(page.messages || [])];
  while (page.id) {
    page = await api.messages.continueList(page.id);
    selected.push(...(page.messages || []));
  }
  return selected;
}

async function importSelectedMessages() {
  const selected = await getSelectedMessages();
  if (!selected.length) {
    await notify("JobMail", "Aucun message selectionne.");
    return { imported: 0 };
  }

  const messages = await buildPayloadMessages(selected);
  return sendMessagesToJobMail(messages, { notifyUser: true });
}

async function importUnreadMessages(options = {}) {
  const stored = await getOptions();
  const fromDate = new Date(Date.now() - stored.sinceDays * 24 * 60 * 60 * 1000);
  let page = await api.messages.query({
    unread: true,
    fromDate,
    messagesPerPage: Math.min(stored.maxMessages, 100),
  });
  const headers = [];
  while (page && headers.length < stored.maxMessages) {
    headers.push(...(page.messages || []));
    if (!page.id || headers.length >= stored.maxMessages) {
      break;
    }
    page = await api.messages.continueList(page.id);
  }

  const limitedHeaders = headers.slice(0, stored.maxMessages);
  if (!limitedHeaders.length) {
    if (!options.silent) {
      await notify("JobMail", "Aucun mail non lu recent a importer.");
    }
    return emptyImportResult();
  }

  const messages = await buildPayloadMessages(limitedHeaders);
  return sendMessagesToJobMail(messages, { notifyUser: !options.silent });
}

async function buildPayloadMessages(headers) {
  const messages = [];
  for (const header of headers) {
    try {
      messages.push(await buildPayloadMessage(header));
    } catch (error) {
      console.warn("JobMail skipped unread message:", error);
    }
  }
  return messages;
}

async function sendMessagesToJobMail(messages, { notifyUser }) {
  const endpoint = await getEndpoint();
  const response = await fetch(`${endpoint}/api/thunderbird/import`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-JobMail-Client": "thunderbird-extension",
    },
    body: JSON.stringify({ messages }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`JobMail a refuse l'import (${response.status}): ${detail}`);
  }

  const result = await response.json();
  if (notifyUser) {
    await notify(
      "JobMail",
      `${result.new_count || 0} nouveau(x), ${result.job_related_count || 0} offre(s) detectee(s).`
    );
  }
  return result;
}

async function scanCleanerCandidates() {
  const cleanerState = await getCleanerState();
  const minAgeDays = cleanerState.min_age_days;
  const maxMessages = cleanerState.max_mails;
  const toDate = new Date(Date.now() - minAgeDays * 24 * 60 * 60 * 1000);
  const headers = await queryCleanerHeaders({ toDate, maxMessages });

  const messages = await buildPayloadMessages(headers.slice(0, maxMessages));
  const endpoint = await getEndpoint();
  const response = await fetch(`${endpoint}/api/thunderbird/cleaner/scan`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-JobMail-Client": "thunderbird-extension",
    },
    body: JSON.stringify({
      minAgeDays,
      messages,
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`JobMail a refuse le scan (${response.status}): ${detail}`);
  }
  const result = await response.json();
  await api.storage.local.set({ cleanerCandidates: result.candidates || [] });
  await notify("JobMail cleaner", `${result.candidate_count || 0} candidat(s) trouve(s).`);
  return result;
}

async function queryCleanerHeaders({ toDate, maxMessages }) {
  const folders = await getInboxFolders();
  if (!folders.length) {
    return queryMessagesPage({ unread: false, toDate, maxMessages });
  }

  const headers = [];
  for (const folder of folders) {
    const folderHeaders = await queryMessagesPage({
      folder,
      unread: false,
      toDate,
      maxMessages: maxMessages - headers.length,
    });
    headers.push(...folderHeaders);
    if (headers.length >= maxMessages) {
      break;
    }
  }
  return headers.slice(0, maxMessages);
}

async function queryMessagesPage(query) {
  const { maxMessages, ...queryInfo } = query;
  let page = await api.messages.query({
    ...queryInfo,
    messagesPerPage: Math.min(maxMessages, 100),
  });
  const headers = [];
  while (page && headers.length < maxMessages) {
    headers.push(...(page.messages || []).filter((header) => !isExcludedCleanerFolder(header.folder)));
    if (!page.id || headers.length >= maxMessages) {
      break;
    }
    page = await api.messages.continueList(page.id);
  }
  return headers.slice(0, maxMessages);
}

async function getInboxFolders() {
  if (!api.accounts?.list) {
    return [];
  }
  const accounts = await api.accounts.list();
  const folders = [];
  for (const account of accounts || []) {
    collectInboxFolders(account.folders || [], folders);
  }
  return folders;
}

function collectInboxFolders(folders, out) {
  for (const folder of folders || []) {
    if (isInboxFolder(folder)) {
      out.push(folder);
    }
    collectInboxFolders(folder.subFolders || folder.folders || [], out);
  }
}

function isInboxFolder(folder) {
  const type = String(folder.type || "").toLowerCase();
  const path = String(folder.path || "").toLowerCase();
  const name = String(folder.name || "").toLowerCase();
  return type === "inbox" || path === "/inbox" || name === "courrier entrant" || name === "inbox";
}

function isExcludedCleanerFolder(folder) {
  const value = `${folder?.type || ""} ${folder?.path || ""} ${folder?.name || ""}`.toLowerCase();
  return /trash|corbeille|junk|spam|indesirable|indésirable|archive|sent|envoy/.test(value);
}

async function getCleanerState() {
  const endpoint = await getEndpoint();
  const response = await fetch(`${endpoint}/cleaner/state?source=thunderbird`, {
    headers: { "Accept": "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Configuration cleaner indisponible (${response.status})`);
  }
  const state = await response.json();
  return {
    min_age_days: clampNumber(state.min_age_days, 1, 365, 7),
    max_mails: clampNumber(state.max_mails, 1, 500, 250),
  };
}

async function trashCleanerCandidates() {
  const stored = await api.storage.local.get({ cleanerCandidates: [] });
  const ids = (stored.cleanerCandidates || [])
    .map((candidate) => Number.parseInt(candidate.id, 10))
    .filter((id) => Number.isFinite(id));
  if (!ids.length) {
    await notify("JobMail cleaner", "Aucun candidat a deplacer.");
    return { moved_count: 0 };
  }

  await api.messages.delete(ids, {
    deletePermanently: false,
    isUserAction: true,
  });
  await api.storage.local.set({ cleanerCandidates: [] });
  await reportBridgeEvent("cleaner_move", { moved_count: ids.length });
  await notify("JobMail cleaner", `${ids.length} mail(s) envoyes a la corbeille.`);
  return { moved_count: ids.length };
}

async function trashJobMailCleanerRequest() {
  const request = await getLatestCleanerRequest();
  const resolution = await resolveCleanerRequestMessageIds(request.candidates || []);
  const ids = resolution.ids;
  if (!ids.length) {
    await notify("JobMail cleaner", "Aucun candidat JobMail retrouve dans Thunderbird.");
    return {
      requested_count: request.candidate_count || 0,
      resolved_count: 0,
      moved_count: 0,
      missing_count: resolution.missing.length,
      missing: resolution.missing,
    };
  }

  await api.messages.delete(ids, {
    deletePermanently: false,
    isUserAction: true,
  });
  await reportBridgeEvent("cleaner_move", {
    requested_count: request.candidate_count || 0,
    resolved_count: ids.length,
    moved_count: ids.length,
  });
  await notify("JobMail cleaner", `${ids.length}/${request.candidate_count || ids.length} mail(s) du scan JobMail envoyes a la corbeille.`);
  return {
    requested_count: request.candidate_count || 0,
    resolved_count: ids.length,
    moved_count: ids.length,
    missing_count: resolution.missing.length,
    missing: resolution.missing,
  };
}

async function getLatestCleanerRequest() {
  const endpoint = await getEndpoint();
  const response = await fetch(`${endpoint}/api/thunderbird/cleaner/latest-request`, {
    headers: { "Accept": "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Demande cleaner JobMail indisponible (${response.status})`);
  }
  return response.json();
}

async function resolveCleanerRequestMessageIds(candidates) {
  const ids = new Set();
  const missing = [];
  for (const candidate of candidates) {
    const id = await findMessageIdForCandidate(candidate);
    if (id) {
      ids.add(id);
    } else {
      missing.push({
        subject: candidate.subject || "",
        sender: candidate.sender || "",
        reason: candidate.reason || "",
      });
    }
  }
  return {
    ids: Array.from(ids),
    missing,
  };
}

async function findMessageIdForCandidate(candidate) {
  const byMessageId = await findByHeaderMessageId(candidate.message_id || "");
  if (byMessageId) {
    return byMessageId;
  }
  return findByCandidateFallback(candidate);
}

async function findByHeaderMessageId(messageId) {
  const clean = String(messageId || "").trim();
  if (!clean || !api.messages?.query) {
    return 0;
  }
  for (const value of [clean, clean.replace(/^<|>$/g, "")]) {
    try {
      const page = await api.messages.query({ headerMessageId: value, messagesPerPage: 10 });
      const match = (page.messages || []).find((header) => !isExcludedCleanerFolder(header.folder));
      if (match?.id) {
        return match.id;
      }
    } catch (_error) {
      return 0;
    }
  }
  return 0;
}

async function findByCandidateFallback(candidate) {
  const folders = await getInboxFolders();
  const received = candidate.received_at ? new Date(candidate.received_at) : null;
  const fromDate = received ? new Date(received.getTime() - 2 * 24 * 60 * 60 * 1000) : undefined;
  const toDate = received ? new Date(received.getTime() + 2 * 24 * 60 * 60 * 1000) : undefined;
  const queryBase = {
    subject: candidate.subject || undefined,
    author: candidate.sender || undefined,
    fromDate,
    toDate,
    maxMessages: 20,
  };

  for (const folder of folders) {
    const headers = await queryMessagesPage({ ...queryBase, folder });
    const match = headers.find((header) => candidateMatchesHeader(candidate, header));
    if (match?.id) {
      return match.id;
    }
  }
  return 0;
}

function candidateMatchesHeader(candidate, header) {
  const subject = String(candidate.subject || "").trim();
  const sender = String(candidate.sender || "").toLowerCase();
  const headerSubject = String(header.subject || "").trim();
  const headerAuthor = String(header.author || "").toLowerCase();
  if (subject && headerSubject && subject !== headerSubject) {
    return false;
  }
  if (sender && headerAuthor && !headerAuthor.includes(extractEmail(sender))) {
    return false;
  }
  return true;
}

function extractEmail(value) {
  const match = String(value || "").match(/[\w.+-]+@[\w-]+\.[\w.-]+/);
  return match ? match[0].toLowerCase() : String(value || "").toLowerCase();
}

async function reportBridgeEvent(event, payload) {
  const endpoint = await getEndpoint();
  try {
    await fetch(`${endpoint}/api/thunderbird/bridge/event`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobMail-Client": "thunderbird-extension",
      },
      body: JSON.stringify({ event, payload }),
    });
  } catch (error) {
    console.warn("JobMail bridge event failed:", error);
  }
}

function emptyImportResult() {
  return {
    fetched_count: 0,
    new_count: 0,
    job_related_count: 0,
    extracted_count: 0,
    sent_to_llm_count: 0,
    skipped_non_job_count: 0,
  };
}

async function getJobMailStatus() {
  const endpoint = await getEndpoint();
  const response = await fetch(`${endpoint}/api/status`);
  if (!response.ok) {
    throw new Error(`JobMail indisponible (${response.status})`);
  }
  return response.json();
}

async function buildPayloadMessage(header) {
  const full = await api.messages.getFull(header.id);
  const body = collectBodies(full);
  const headers = full.headers || {};
  let hasAttachment = false;
  try {
    const attachments = await api.messages.listAttachments(header.id);
    hasAttachment = attachments.length > 0;
  } catch (_error) {
    hasAttachment = Boolean(header.hasAttachments);
  }

  return {
    id: header.id,
    messageId: firstHeader(headers["message-id"]) || header.messageId || "",
    subject: header.subject || firstHeader(headers.subject) || "",
    author: header.author || firstHeader(headers.from) || "",
    date: header.date ? new Date(header.date).toISOString() : firstHeader(headers.date) || "",
    folderAccount: header.folder?.accountId || "",
    folderPath: header.folder?.path || "",
    folderName: header.folder?.name || "",
    bodyPlain: body.text,
    bodyHtml: body.html,
    hasAttachment,
  };
}

function collectBodies(part, bucket = { text: [], html: [] }) {
  const contentType = String(part.contentType || "").toLowerCase();
  if (typeof part.body === "string") {
    if (contentType.startsWith("text/html")) {
      bucket.html.push(part.body);
    } else if (contentType.startsWith("text/plain") || !contentType) {
      bucket.text.push(part.body);
    }
  }
  for (const child of part.parts || []) {
    collectBodies(child, bucket);
  }
  return {
    text: bucket.text.join("\n\n").trim(),
    html: bucket.html.join("\n\n").trim(),
  };
}

function firstHeader(value) {
  if (Array.isArray(value)) {
    return value[0] || "";
  }
  return value || "";
}

function clampNumber(value, min, max, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

async function notify(title, message) {
  try {
    await api.notifications.create({
      type: "basic",
      title,
      message,
    });
  } catch (_error) {
    // Notifications are comfort only; importing should not depend on them.
  }
}
