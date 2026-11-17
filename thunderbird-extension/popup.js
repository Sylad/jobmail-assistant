const DEFAULT_ENDPOINT = "http://127.0.0.1:8765";
const api = typeof messenger !== "undefined" ? messenger : browser;

// L4/t6 : la fenêtre n'affiche qu'un extrait des candidats ; aucun mail ne part d'ici sans avoir
// été coché et confirmé dans l'écran /cleaner de JobMail.
const PREVIEW_ONLY = "Aperçu seulement : pour déplacer, coche et confirme les mails dans /cleaner de JobMail.";

const statusEl = document.querySelector("#status");
const cleanerStatusEl = document.querySelector("#cleaner-status");
const cleanerCandidatesEl = document.querySelector("#cleaner-candidates");
const jobMailCleanerStatusEl = document.querySelector("#jobmail-cleaner-status");
const jobMailCleanerMissingEl = document.querySelector("#jobmail-cleaner-missing");
const endpointEl = document.querySelector("#endpoint");
const sinceDaysEl = document.querySelector("#since-days");
const maxMessagesEl = document.querySelector("#max-messages");
const autoImportEl = document.querySelector("#auto-import");
const autoMinutesEl = document.querySelector("#auto-minutes");
const cleanerAgeDaysEl = document.querySelector("#cleaner-age-days");
const cleanerMaxMessagesEl = document.querySelector("#cleaner-max-messages");
const importButton = document.querySelector("#import");
const importUnreadButton = document.querySelector("#import-unread");
const scanCleanerButton = document.querySelector("#scan-cleaner");
const trashJobMailCleanerButton = document.querySelector("#trash-jobmail-cleaner");
const saveButton = document.querySelector("#save");

init();

async function init() {
  const stored = await api.runtime.sendMessage({ type: "get-options" });
  endpointEl.value = stored.endpoint || DEFAULT_ENDPOINT;
  sinceDaysEl.value = stored.sinceDays || 14;
  maxMessagesEl.value = stored.maxMessages || 50;
  autoImportEl.checked = Boolean(stored.autoImport);
  autoMinutesEl.value = stored.autoMinutes || 15;
  await refreshStatus();
  await refreshCleanerState();
}

importButton.addEventListener("click", async () => {
  importButton.disabled = true;
  statusEl.textContent = "Import en cours...";
  try {
    const result = await api.runtime.sendMessage({ type: "import-selected" });
    statusEl.textContent = `${result.new_count || 0} nouveau(x), ${result.job_related_count || 0} offre(s).`;
  } catch (error) {
    statusEl.textContent = error.message || "Import impossible.";
  } finally {
    importButton.disabled = false;
  }
});

importUnreadButton.addEventListener("click", async () => {
  importUnreadButton.disabled = true;
  statusEl.textContent = "Import des non lus...";
  try {
    const result = await api.runtime.sendMessage({ type: "import-unread" });
    statusEl.textContent = `${result.new_count || 0} nouveau(x), ${result.job_related_count || 0} offre(s).`;
  } catch (error) {
    statusEl.textContent = error.message || "Import impossible.";
  } finally {
    importUnreadButton.disabled = false;
  }
});

scanCleanerButton.addEventListener("click", async () => {
  scanCleanerButton.disabled = true;
  cleanerStatusEl.textContent = "Aperçu du nettoyage...";
  try {
    const result = await api.runtime.sendMessage({ type: "scan-cleaner" });
    // L4/t6 : ce scan ne déplace rien et ne prépare aucun déplacement.
    cleanerStatusEl.textContent = `${result.candidate_count || 0} candidat(s) sur ${result.scanned_count || 0} mail(s). ${PREVIEW_ONLY}`;
    renderCleanerCandidates(result.candidates || []);
  } catch (error) {
    cleanerStatusEl.textContent = error.message || "Scan impossible.";
    renderCleanerCandidates([]);
  } finally {
    scanCleanerButton.disabled = false;
  }
});

trashJobMailCleanerButton.addEventListener("click", async () => {
  const ok = window.confirm("Envoyer à la corbeille les mails sélectionnés et confirmés dans l'écran /cleaner de JobMail ?");
  if (!ok) {
    return;
  }
  trashJobMailCleanerButton.disabled = true;
  cleanerStatusEl.textContent = "Deplacement du scan JobMail...";
  try {
    const result = await api.runtime.sendMessage({ type: "trash-jobmail-cleaner-request" });
    cleanerStatusEl.textContent = `${result.moved_count || 0}/${result.requested_count || 0} mail(s) retrouves et envoyes a la corbeille.`;
    jobMailCleanerStatusEl.textContent = `Demandes ${result.requested_count || 0} · retrouves ${result.resolved_count || 0} · deplaces ${result.moved_count || 0} · introuvables ${result.missing_count || 0}`;
    renderMissingJobMailCandidates(result.missing || []);
    renderCleanerCandidates([]);
  } catch (error) {
    cleanerStatusEl.textContent = error.message || "Deplacement JobMail impossible.";
    jobMailCleanerStatusEl.textContent = "";
    renderMissingJobMailCandidates([]);
  } finally {
    trashJobMailCleanerButton.disabled = false;
  }
});

saveButton.addEventListener("click", async () => {
  await api.runtime.sendMessage({
    type: "save-options",
    options: {
      endpoint: endpointEl.value,
      sinceDays: sinceDaysEl.value,
      maxMessages: maxMessagesEl.value,
      autoImport: autoImportEl.checked,
      autoMinutes: autoMinutesEl.value,
    },
  });
  await refreshStatus();
  await refreshCleanerState();
});

async function refreshStatus() {
  try {
    const endpoint = endpointEl.value.replace(/\/$/, "") || DEFAULT_ENDPOINT;
    const response = await fetch(`${endpoint}/api/status`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const status = await response.json();
    statusEl.textContent = `${status.offers || 0} offre(s), ${status.emails || 0} mail(s) analyses.`;
  } catch (_error) {
    statusEl.textContent = "Lance JobMail local avant l'import.";
  }
}

function renderCleanerCandidates(candidates) {
  cleanerCandidatesEl.replaceChildren();
  for (const candidate of candidates.slice(0, 8)) {
    const item = document.createElement("li");
    const subject = document.createElement("strong");
    const sender = document.createElement("span");
    subject.textContent = candidate.subject || "(sans sujet)";
    sender.textContent = `${candidate.sender || "(expediteur inconnu)"} · ${candidate.reason || ""}`;
    item.append(subject, sender);
    cleanerCandidatesEl.append(item);
  }
  if (candidates.length > 8) {
    const item = document.createElement("li");
    const more = document.createElement("span");
    more.textContent = `+ ${candidates.length - 8} autre(s) candidat(s)`;
    item.append(more);
    cleanerCandidatesEl.append(item);
  }
}

function renderMissingJobMailCandidates(candidates) {
  jobMailCleanerMissingEl.replaceChildren();
  for (const candidate of candidates.slice(0, 5)) {
    const item = document.createElement("li");
    const subject = document.createElement("strong");
    const sender = document.createElement("span");
    subject.textContent = candidate.subject || "(sans sujet)";
    sender.textContent = candidate.sender || "(expediteur inconnu)";
    item.append(subject, sender);
    jobMailCleanerMissingEl.append(item);
  }
  if (candidates.length > 5) {
    const item = document.createElement("li");
    const more = document.createElement("span");
    more.textContent = `+ ${candidates.length - 5} autre(s) introuvable(s)`;
    item.append(more);
    jobMailCleanerMissingEl.append(item);
  }
}

async function refreshCleanerState() {
  try {
    const endpoint = endpointEl.value.replace(/\/$/, "") || DEFAULT_ENDPOINT;
    const response = await fetch(`${endpoint}/cleaner/state?source=thunderbird`, {
      headers: { "Accept": "application/json" },
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const state = await response.json();
    cleanerAgeDaysEl.value = state.min_age_days || "";
    cleanerMaxMessagesEl.value = state.max_mails || "";
    cleanerStatusEl.textContent = "Nettoyage manuel : seule la sélection confirmée dans /cleaner peut partir.";
  } catch (_error) {
    cleanerAgeDaysEl.value = "";
    cleanerMaxMessagesEl.value = "";
    cleanerStatusEl.textContent = "Configuration cleaner JobMail indisponible.";
  }
}
