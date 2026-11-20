<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ChevronDown, ChevronUp, Download, ExternalLink, Plus, Search, Send, Trash2 } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import ProgressPanel from "./ProgressPanel.vue";
import {
  candidatesListOpen,
  countPlannedMoves,
  emptyCandidatesMessage as emptyMessageFor,
  initialPhaseSelection,
  missingConfirmationHint,
  planPhaseMoves,
  plannedMoveUids,
  scanPanelVisibleAfterFullScan,
} from "./cleaner-core";
import type {
  CleanerInitialState,
  CleanerMoveJobPayload,
  CleanerReportPayload,
  CleanerScanJobPayload,
  CleanerScanResultPayload,
  CleanerSource,
  ProgressPanelState,
  RegexRule,
} from "./types";

const props = defineProps<{ initial: CleanerInitialState }>();

type CleanerPhaseSource = Exclude<CleanerSource, "imap">;
type PhaseStatus = "idle" | "running" | "done" | "cancelled" | "error";

const scanPhases: Array<{ source: CleanerPhaseSource; label: string; description: string }> = [
  {
    source: "thunderbird",
    label: "Pubs anciennes",
    description: "Heuristique newsletters et publicités anciennes.",
  },
  {
    source: "regex",
    label: "Règles regex",
    description: "Filtres expéditeur et objet que tu pilotes.",
  },
  {
    source: "parsed_jobs",
    label: "Offres déjà traitées",
    description: "Mails d'offres déjà extraites et peu utiles.",
  },
  {
    source: "duplicates",
    label: "Doublons",
    description: "Copies Orange déjà présentes côté Gmail.",
  },
];

const form = reactive({
  source: props.initial.source ?? "thunderbird",
  minAgeDays: props.initial.min_age_days ?? 7,
  maxMails: props.initial.max_mails ?? 250,
  scanOffset: props.initial.scan_offset ?? 0,
});

const regexRules = ref<RegexRule[]>(normalizeRules(props.initial.regex_rules ?? []));
const reportResult = ref<CleanerScanResultPayload | null>(null);
const phaseResults = reactive<Record<CleanerPhaseSource, CleanerScanResultPayload | null>>({
  thunderbird: null,
  regex: null,
  parsed_jobs: null,
  duplicates: null,
});
const phaseStatuses = reactive<Record<CleanerPhaseSource, PhaseStatus>>({
  thunderbird: "idle",
  regex: "idle",
  parsed_jobs: "idle",
  duplicates: "idle",
});
const phaseErrors = reactive<Record<CleanerPhaseSource, string>>({
  thunderbird: "",
  regex: "",
  parsed_jobs: "",
  duplicates: "",
});
const phaseSelections = reactive<Record<CleanerPhaseSource, string[]>>({
  thunderbird: [],
  regex: [],
  parsed_jobs: [],
  duplicates: [],
});
const activePhase = ref<CleanerPhaseSource>("thunderbird");
const fullScanRunning = ref(false);
const moveAllRunning = ref(false);
const extensionRequestRunning = ref(false);
const moveAllBaseMoved = ref(0);
const moveAllBaseProcessed = ref(0);
const moveAllSkipped = ref(0);
const moveAllTotalPlanned = ref(0);
const moveAllCurrentPhaseIndex = ref(0);
const moveAllPhaseCount = ref(0);
const moveAllCurrentPhase = ref<CleanerPhaseSource | null>(null);
const selectedUids = ref<Set<string>>(new Set());
const confirmMove = ref(false);
const confirmThunderbirdClosed = ref(false);
const actionMessage = ref("");
const actionError = ref("");
// L4/t4 : la confirmation manquante se dit à côté du bouton cliqué, qui la porte en aria-describedby.
const confirmHint = ref<{ action: "move" | "extension"; text: string } | null>(null);
// L4/t3 : liste des candidats repliable par phase. `null` = pas encore de choix à la main : repliée
// par défaut en écran étroit au-delà du seuil. Affichage seulement, la sélection ne change pas.
const candidatesOpenChoice = reactive<Record<CleanerPhaseSource, boolean | null>>({
  thunderbird: null,
  regex: null,
  parsed_jobs: null,
  duplicates: null,
});
const narrowQuery = typeof window.matchMedia === "function" ? window.matchMedia("(max-width: 900px)") : null;
const narrowScreen = ref(narrowQuery?.matches ?? false);
narrowQuery?.addEventListener("change", (event) => {
  narrowScreen.value = event.matches;
});
const regexSaveState = ref<"saved" | "dirty" | "saving" | "error">("saved");
let regexSaveTimer: number | undefined;
let regexHydrating = false;
let currentScanJobId = "";
let currentMoveJobId = "";

const scanPanel = reactive<ProgressPanelState>({
  visible: false,
  title: "Scan en cours",
  elapsedSeconds: 0,
  active: false,
  cancelling: false,
  progressValue: null,
  stats: defaultScanStats(),
});

const movePanel = reactive<ProgressPanelState>({
  visible: false,
  title: "Déplacement en cours",
  elapsedSeconds: 0,
  active: false,
  cancelling: false,
  progressValue: null,
  stats: [
    { label: "Messages prévus", value: 0 },
    { label: "Messages déplacés", value: 0 },
  ],
});

const currentReport = computed<CleanerReportPayload | null>(() => reportResult.value?.report ?? null);
const movableCandidates = computed(() => currentReport.value?.candidates.filter((candidate) => candidate.can_move) ?? []);
const selectedCount = computed(() => selectedUids.value.size);
const totalPhaseCandidates = computed(() => scanPhases.reduce((sum, phase) => sum + (phaseResults[phase.source]?.report.candidate_count ?? 0), 0));
const phaseOrder = scanPhases.map((phase) => phase.source);
// L4/t1 : le total annoncé et ce qui part au déplacement viennent du même calcul
// (cleaner-core.ts), sélection par phase comprise pour « Règles regex ».
const totalSelectedCandidates = computed(() => countPlannedMoves(phaseOrder, phaseResults, phaseSelections));
const emptyCandidatesMessage = computed(() => emptyMessageFor(reportResult.value));
const candidatesOpen = computed(() => candidatesListOpen(
  currentReport.value?.candidates.length ?? 0,
  narrowScreen.value,
  candidatesOpenChoice[activePhase.value],
));

function toggleCandidates(): void {
  candidatesOpenChoice[activePhase.value] = !candidatesOpen.value;
}

function collapseCandidatesFromBottom(): void {
  candidatesOpenChoice[activePhase.value] = false;
  // Le bouton du bas disparaît avec la liste : le focus et la vue reviennent sur l'en-tête.
  const toggle = document.getElementById("cleaner-candidates-toggle");
  toggle?.focus();
  toggle?.scrollIntoView({ block: "center" });
}

watch([confirmMove, confirmThunderbirdClosed], () => {
  const hint = confirmHint.value;
  if (hint && missingConfirmationHint(hint.action, confirmMove.value, confirmThunderbirdClosed.value) === null) {
    confirmHint.value = null;
  }
});
const regexSaveLabel = computed(() => {
  if (regexSaveState.value === "saving") return "Sauvegarde...";
  if (regexSaveState.value === "dirty") return "Modifications non sauvegardées";
  if (regexSaveState.value === "error") return "Sauvegarde en erreur";
  return "Règles sauvegardées";
});

watch(
  regexRules,
  () => {
    if (regexHydrating) {
      regexHydrating = false;
      return;
    }
    scheduleRegexRulesSave();
  },
  { deep: true },
);

function normalizeRules(rules: RegexRule[]): RegexRule[] {
  const clean = rules.filter((rule) => rule.sender_regex || rule.subject_regex);
  while (clean.length < 5) clean.push({ sender_regex: "", subject_regex: "" });
  return clean;
}

function defaultScanStats() {
  return [
    { label: "Mails scannés", value: 0 },
    { label: "Candidats", value: 0 },
    { label: "Factures avec PJ", value: 0 },
    { label: form.source === "regex" ? "Hors regex" : "Hors filtre", value: 0 },
    { label: "Trop récents", value: 0 },
  ];
}

function sourceDescription(source: CleanerSource): string {
  if (source === "parsed_jobs") {
    return "Source SQLite : mails d'offres déjà extraites. Seuls les mails liés à une offre ignorée ou notée 3 ou moins sont proposés.";
  }
  if (source === "duplicates") {
    return "Source Thunderbird : propose uniquement les copies Orange dont le même Message-Id existe dans une boîte Gmail.";
  }
  if (source === "regex") {
    return "Les lignes regex sont combinées en OU global. Dans une ligne, les champs remplis doivent tous correspondre.";
  }
  if (source === "imap") {
    return props.initial.imap_enabled ? `Source IMAP configurée, déplacement vers ${props.initial.delete_folder}.` : "IMAP n'est pas configuré.";
  }
  return `MBOX scannés : ${props.initial.mbox_patterns.join(", ")}`;
}

function addRegexRule(): void {
  regexRules.value.push({ sender_regex: "", subject_regex: "" });
}

function scheduleRegexRulesSave(): void {
  regexSaveState.value = "dirty";
  window.clearTimeout(regexSaveTimer);
  regexSaveTimer = window.setTimeout(() => {
    saveRegexRules().catch(() => {
      regexSaveState.value = "error";
    });
  }, 700);
}

function cleanRegexRules(): RegexRule[] {
  return regexRules.value
    .map((rule) => ({
      sender_regex: rule.sender_regex.trim(),
      subject_regex: rule.subject_regex.trim(),
    }))
    .filter((rule) => rule.sender_regex || rule.subject_regex);
}

async function saveRegexRules(): Promise<void> {
  window.clearTimeout(regexSaveTimer);
  regexSaveState.value = "saving";
  const response = await fetch("/cleaner/regex-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rules: cleanRegexRules() }),
  });
  if (!response.ok) {
    regexSaveState.value = "error";
    return;
  }
  regexSaveState.value = "saved";
}

function scanFormData(extra?: Record<string, string>, source: CleanerSource = form.source, offset = form.scanOffset): FormData {
  const data = new FormData();
  data.set("source", source);
  data.set("min_age_days", String(form.minAgeDays));
  data.set("max_mails", String(form.maxMails));
  data.set("scan_offset", String(offset));
  if (source === "regex") {
    cleanRegexRules().forEach((rule) => {
      data.append("sender_regex_rule", rule.sender_regex);
      data.append("subject_regex_rule", rule.subject_regex);
    });
  }
  Object.entries(extra ?? {}).forEach(([key, value]) => data.set(key, value));
  return data;
}

async function startFullScan(): Promise<void> {
  actionMessage.value = "";
  actionError.value = "";
  confirmHint.value = null;
  reportResult.value = null;
  selectedUids.value = new Set();
  confirmMove.value = false;
  confirmThunderbirdClosed.value = false;
  fullScanRunning.value = true;
  scanPhases.forEach((phase) => {
    phaseResults[phase.source] = null;
    phaseStatuses[phase.source] = "idle";
    phaseErrors[phase.source] = "";
    phaseSelections[phase.source] = [];
    candidatesOpenChoice[phase.source] = null;
  });

  try {
    await saveRegexRules();
    let firstCandidatePhase: CleanerPhaseSource | null = null;
    let firstResultPhase: CleanerPhaseSource | null = null;
    for (const phase of scanPhases) {
      if (scanPanel.cancelling) break;
      activePhase.value = phase.source;
      phaseStatuses[phase.source] = "running";
      const result = await startPhaseScan(phase.source);
      if (!result) {
        if (phaseStatuses[phase.source] === "running") phaseStatuses[phase.source] = "cancelled";
        break;
      }
      phaseResults[phase.source] = result;
      phaseStatuses[phase.source] = "done";
      if (!firstResultPhase) firstResultPhase = phase.source;
      if (!firstCandidatePhase && result.report.candidate_count > 0) {
        firstCandidatePhase = phase.source;
      }
    }
    const selectedPhase = firstCandidatePhase ?? firstResultPhase;
    if (selectedPhase) selectPhase(selectedPhase);
    // L4 : une fois toutes les phases finies, le panneau (figé sur la dernière phase) contredirait
    // les statistiques de la phase affichée ; les cartes de phase portent déjà les comptes.
    scanPanel.visible = scanPanelVisibleAfterFullScan(phaseOrder, phaseStatuses, scanPanel.visible);
  } catch (error) {
    scanPanel.title = error instanceof Error ? error.message : "Scan en erreur";
    scanPanel.active = false;
    scanPanel.progressValue = 0;
  } finally {
    fullScanRunning.value = false;
  }
}

async function startPhaseScan(source: CleanerPhaseSource): Promise<CleanerScanResultPayload | null> {
  const offset = source === "thunderbird" ? Math.max(0, form.scanOffset) : 0;
  form.source = source;
  form.scanOffset = offset;
  showScanPanel(`Scan : ${phaseLabel(source)}`);
  try {
    const response = await fetch("/cleaner/scan/start", {
      method: "POST",
      body: scanFormData(undefined, source, offset),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "Impossible de lancer le scan.");
    }
    const payload = await response.json() as CleanerScanJobPayload;
    currentScanJobId = payload.id;
    setScanProgress(payload, source);
    return await pollScan(payload.id, source);
  } catch (error) {
    phaseStatuses[source] = "error";
    phaseErrors[source] = error instanceof Error ? error.message : "Scan en erreur";
    throw error;
  }
}

async function pollScan(jobId: string, source: CleanerSource): Promise<CleanerScanResultPayload | null> {
  const response = await fetch(`/cleaner/scan/status/${jobId}`);
  if (!response.ok) throw new Error("Impossible de lire le statut du scan.");
  const payload = await response.json() as CleanerScanJobPayload;
  setScanProgress(payload, source);

  if (payload.status === "done") {
    scanPanel.title = fullScanRunning.value ? `Phase terminée : ${phaseLabel(source)}` : "Scan terminé";
    scanPanel.active = false;
    return await loadScanResult(payload.result_json_url, false);
  }
  if (payload.status === "cancelled") {
    scanPanel.title = "Scan annulé";
    scanPanel.active = false;
    scanPanel.progressValue = 0;
    scanPanel.cancelling = false;
    return null;
  }
  if (payload.status === "error") {
    scanPanel.title = payload.error || "Scan en erreur";
    scanPanel.active = false;
    scanPanel.progressValue = 0;
    scanPanel.cancelling = false;
    throw new Error(scanPanel.title);
  }
  await sleep(700);
  return pollScan(jobId, source);
}

async function loadScanResult(url: string, activate = true): Promise<CleanerScanResultPayload> {
  const response = await fetch(url);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Impossible de charger le rapport.");
  }
  const payload = await response.json() as CleanerScanResultPayload;
  form.source = payload.source;
  form.minAgeDays = payload.min_age_days;
  form.maxMails = payload.max_mails;
  form.scanOffset = payload.scan_offset;
  if (isPhaseSource(payload.source)) {
    phaseResults[payload.source] = payload;
    initializePhaseSelection(payload.source, payload);
  }
  if (payload.source === "regex") {
    regexHydrating = true;
    regexRules.value = normalizeRules(payload.regex_rules);
    window.queueMicrotask(() => {
      regexHydrating = false;
    });
    regexSaveState.value = "saved";
  }
  if (activate && isPhaseSource(payload.source)) {
    selectPhase(payload.source);
  }
  return payload;
}

async function cancelScan(): Promise<void> {
  if (!currentScanJobId) return;
  scanPanel.cancelling = true;
  scanPanel.title = "Arrêt demandé";
  await fetch(`/cleaner/scan/cancel/${currentScanJobId}`, { method: "POST" }).catch(() => {});
}

function showScanPanel(title: string): void {
  scanPanel.visible = true;
  scanPanel.title = title;
  scanPanel.elapsedSeconds = 0;
  scanPanel.active = true;
  scanPanel.cancelling = false;
  scanPanel.progressValue = null;
  scanPanel.stats = defaultScanStats();
}

function setScanProgress(payload: CleanerScanJobPayload, source: CleanerSource = form.source): void {
  scanPanel.elapsedSeconds = payload.elapsed_seconds || 0;
  scanPanel.stats = [
    { label: "Mails scannés", value: payload.scanned_count || 0 },
    { label: "Candidats", value: payload.candidate_count || 0 },
    { label: "Factures avec PJ", value: payload.skipped_safety || 0 },
    { label: source === "regex" ? "Hors regex" : "Hors filtre", value: payload.skipped_no_match || 0 },
    { label: "Trop récents", value: payload.skipped_too_recent || 0 },
    ...(payload.current_mailbox ? [{ label: "Boîte", value: payload.current_mailbox }] : []),
  ];
}

function exportCsv(): void {
  const formElement = document.createElement("form");
  formElement.method = "POST";
  formElement.action = "/cleaner/scan";
  formElement.style.display = "none";
  const data = scanFormData({ export_csv: "1" }, reportResult.value?.source ?? form.source, reportResult.value?.scan_offset ?? form.scanOffset);
  data.forEach((value, key) => {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = key;
    input.value = String(value);
    formElement.appendChild(input);
  });
  document.body.appendChild(formElement);
  formElement.submit();
  formElement.remove();
}

function phaseLabel(source: CleanerSource): string {
  return scanPhases.find((phase) => phase.source === source)?.label ?? "IMAP";
}

function phaseStatusLabel(status: PhaseStatus): string {
  if (status === "running") return "En cours";
  if (status === "done") return "Terminé";
  if (status === "cancelled") return "Annulé";
  if (status === "error") return "Erreur";
  return "En attente";
}

function isPhaseSource(source: CleanerSource): source is CleanerPhaseSource {
  return source !== "imap";
}

function selectPhase(source: CleanerPhaseSource, preserveConfirmation = false): void {
  const result = phaseResults[source];
  activePhase.value = source;
  if (!result) return;
  reportResult.value = result;
  form.source = result.source;
  form.minAgeDays = result.min_age_days;
  form.maxMails = result.max_mails;
  form.scanOffset = result.scan_offset;
  if (!preserveConfirmation) {
    confirmMove.value = false;
    confirmThunderbirdClosed.value = false;
  }
  selectedUids.value = new Set(phaseSelections[source]);
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function selectAllCandidates(): void {
  setActiveSelection(new Set(movableCandidates.value.map((candidate) => candidate.uid)));
}

function clearSelection(): void {
  setActiveSelection(new Set());
}

function setSenderSelection(sender: string, selected: boolean): void {
  const next = new Set(selectedUids.value);
  movableCandidates.value
    .filter((candidate) => candidate.sender === sender)
    .forEach((candidate) => {
      if (selected) next.add(candidate.uid);
      else next.delete(candidate.uid);
    });
  setActiveSelection(next);
}

function toggleCandidate(uid: string, selected: boolean): void {
  const next = new Set(selectedUids.value);
  if (selected) next.add(uid);
  else next.delete(uid);
  setActiveSelection(next);
}

function setActiveSelection(next: Set<string>): void {
  selectedUids.value = next;
  phaseSelections[activePhase.value] = Array.from(next);
}

function initializePhaseSelection(source: CleanerPhaseSource, result: CleanerScanResultPayload): void {
  phaseSelections[source] = initialPhaseSelection(result);
}

function senderState(sender: string): string {
  const senderCandidates = movableCandidates.value.filter((candidate) => candidate.sender === sender);
  const checked = senderCandidates.filter((candidate) => selectedUids.value.has(candidate.uid)).length;
  if (checked === 0) return "Exclu";
  if (checked === senderCandidates.length) return "Inclus";
  return "Partiel";
}

function senderRowClass(sender: string): string {
  const state = senderState(sender);
  if (state === "Exclu") return "sender-excluded";
  if (state === "Partiel") return "sender-partial";
  return "sender-included";
}

async function moveAllSelections(): Promise<void> {
  actionError.value = "";
  actionMessage.value = "";
  const missing = missingConfirmationHint("move", confirmMove.value, confirmThunderbirdClosed.value);
  confirmHint.value = missing ? { action: "move", text: missing } : null;
  if (missing) return;
  if (totalSelectedCandidates.value <= 0) return;

  moveAllRunning.value = true;
  moveAllBaseMoved.value = 0;
  moveAllBaseProcessed.value = 0;
  moveAllSkipped.value = 0;
  moveAllCurrentPhase.value = null;
  const phaseMoves = planPhaseMoves(phaseOrder, phaseResults, phaseSelections).map(({ source, uids }) => ({
    phase: scanPhases.find((phase) => phase.source === source)!,
    result: phaseResults[source]!,
    uids,
  }));
  moveAllTotalPlanned.value = phaseMoves.reduce((sum, move) => sum + move.uids.length, 0);
  moveAllPhaseCount.value = phaseMoves.length;
  let movedTotal = 0;
  try {
    for (let index = 0; index < phaseMoves.length; index += 1) {
      if (movePanel.cancelling) break;
      const { phase, result, uids } = phaseMoves[index];
      moveAllCurrentPhase.value = phase.source;
      moveAllCurrentPhaseIndex.value = index + 1;
      selectPhase(phase.source, true);
      try {
        const moved = await moveThunderbirdResults(moveFieldsForPhase(result, uids));
        movedTotal += moved;
        moveAllBaseMoved.value = movedTotal;
        moveAllBaseProcessed.value += uids.length;
      } catch (error) {
        if (!isSkippableMoveError(error)) throw error;
        moveAllSkipped.value += uids.length;
        moveAllBaseProcessed.value += uids.length;
        setMoveAllSummaryProgress(error instanceof Error ? error.message : "Phase ignorée.");
      }
    }
    actionMessage.value = movePanel.cancelling
      ? `${movedTotal} mail(s) déplacé(s) avant l'arrêt demandé.`
      : `${movedTotal} mail(s) déplacé(s) vers la corbeille Thunderbird depuis toutes les phases. ${moveAllSkipped.value} mail(s) ignoré(s) car déjà absents ou refusés.`;
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : "Déplacement en erreur.";
  } finally {
    moveAllRunning.value = false;
    moveAllCurrentPhase.value = null;
  }
}

// L4/t5 : l'extension Thunderbird (« Corbeille scan JobMail ») ne reçoit que cette sélection,
// confirmée ici. Thunderbird reste ouvert sur ce chemin : seule la relecture est exigée.
async function entrustSelectionToExtension(): Promise<void> {
  actionError.value = "";
  actionMessage.value = "";
  if (!confirmMove.value) {
    confirmHint.value = {
      action: "extension",
      text: missingConfirmationHint("extension", confirmMove.value, confirmThunderbirdClosed.value)!,
    };
    return;
  }
  confirmHint.value = null;
  const uids = plannedMoveUids(phaseOrder, phaseResults, phaseSelections);
  if (!uids.length) return;
  extensionRequestRunning.value = true;
  try {
    const data = new FormData();
    uids.forEach((uid) => data.append("selected_uid", uid));
    data.set("confirm_move", "yes");
    const response = await fetch("/api/thunderbird/cleaner/request", { method: "POST", body: data });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Impossible de confier la sélection à l'extension.");
    actionMessage.value = `${payload.candidate_count} mail(s) confié(s) à l'extension Thunderbird. Rien n'est encore déplacé : dans Thunderbird, clique « Corbeille scan JobMail ». Un nouveau scan annule cette demande.`;
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : "Impossible de confier la sélection à l'extension.";
  } finally {
    extensionRequestRunning.value = false;
  }
}

function moveFieldsForPhase(result: CleanerScanResultPayload, uids: string[]): Record<string, string | string[]> {
  const fields: Record<string, string | string[]> = {
    source: result.source,
    min_age_days: String(result.min_age_days),
    max_mails: String(result.max_mails),
    selected_uid: uids,
    confirm_move: "yes",
  };
  if (result.source === "regex") {
    fields.regex_job_id = result.regex_job_id;
  }
  return fields;
}

function isSkippableMoveError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("Aucun mail") || message.includes("ne passe les regles");
}

async function moveThunderbirdResults(fields: Record<string, string | string[]>): Promise<number> {
  if (!reportResult.value) return 0;
  showMovePanel();
  const data = new FormData();
  Object.entries(fields).forEach(([key, value]) => {
    const values = Array.isArray(value) ? value : [value];
    values.forEach((entry) => data.append(key, entry));
  });
  data.set("confirm_thunderbird_closed", "yes");
  const response = await fetch("/cleaner/move-thunderbird-to-trash/start", {
    method: "POST",
    body: data,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    movePanel.title = payload.detail || "Impossible de lancer le déplacement.";
    movePanel.active = false;
    throw new Error(movePanel.title);
  }
  const payload = await response.json() as CleanerMoveJobPayload;
  currentMoveJobId = payload.id;
  setMoveProgress(payload);
  return await pollMove(payload.id);
}

function showMovePanel(): void {
  movePanel.visible = true;
  movePanel.title = moveAllRunning.value && moveAllCurrentPhase.value
    ? `Déplacement en cours : ${phaseLabel(moveAllCurrentPhase.value)}`
    : "Déplacement en cours";
  movePanel.elapsedSeconds = 0;
  movePanel.active = true;
  movePanel.cancelling = false;
  movePanel.progressValue = null;
  movePanel.stats = [
    { label: "Messages prévus", value: 0 },
    { label: "Messages déplacés", value: 0 },
  ];
}

async function pollMove(jobId: string): Promise<number> {
  const response = await fetch(`/cleaner/move/status/${jobId}`);
  if (!response.ok) throw new Error("Impossible de lire le statut du déplacement.");
  const payload = await response.json() as CleanerMoveJobPayload;
  setMoveProgress(payload);
  if (payload.status === "done") {
    movePanel.title = "Déplacement terminé";
    movePanel.active = false;
    return await loadMoveResult(payload.result_json_url || `/cleaner/move/status/${jobId}/result-json`);
  }
  if (payload.status === "cancelled") {
    movePanel.title = "Déplacement annulé";
    movePanel.active = false;
    movePanel.cancelling = false;
    return payload.moved_count || 0;
  }
  if (payload.status === "error") {
    movePanel.title = payload.error || "Déplacement en erreur";
    movePanel.active = false;
    movePanel.cancelling = false;
    throw new Error(movePanel.title);
  }
  await sleep(700);
  return pollMove(jobId);
}

async function loadMoveResult(url: string): Promise<number> {
  const response = await fetch(url);
  if (!response.ok) return 0;
  const payload = await response.json();
  actionMessage.value = `${payload.moved_count} mail(s) déplacé(s) vers ${payload.moved_destination}.`;
  if (reportResult.value) {
    reportResult.value.source = payload.source ?? reportResult.value.source;
    reportResult.value.report = payload.report;
    reportResult.value.regex_rules = payload.regex_rules;
    if (isPhaseSource(reportResult.value.source)) {
      phaseResults[reportResult.value.source] = reportResult.value;
      initializePhaseSelection(reportResult.value.source, reportResult.value);
    }
  }
  return Number(payload.moved_count || 0);
}

async function cancelMove(): Promise<void> {
  if (!currentMoveJobId) return;
  movePanel.cancelling = true;
  movePanel.title = "Arrêt demandé";
  await fetch(`/cleaner/move/cancel/${currentMoveJobId}`, { method: "POST" }).catch(() => {});
}

function setMoveProgress(payload: CleanerMoveJobPayload): void {
  movePanel.elapsedSeconds = payload.elapsed_seconds || 0;
  const total = payload.total_count || 0;
  const moved = payload.moved_count || 0;
  if (moveAllRunning.value && moveAllCurrentPhase.value) {
    const globalMoved = moveAllBaseMoved.value + moved;
    const globalProcessed = moveAllBaseProcessed.value + moved;
    movePanel.title = `Déplacement en cours : ${phaseLabel(moveAllCurrentPhase.value)}`;
    movePanel.progressValue = moveAllTotalPlanned.value > 0
      ? Math.round((globalProcessed / moveAllTotalPlanned.value) * 100)
      : null;
    movePanel.stats = [
      { label: "Phase", value: `${moveAllCurrentPhaseIndex.value}/${moveAllPhaseCount.value}` },
      { label: "Étape", value: phaseLabel(moveAllCurrentPhase.value) },
      { label: "Total prévu", value: moveAllTotalPlanned.value },
      { label: "Total traité", value: globalProcessed },
      { label: "Total déplacé", value: globalMoved },
      { label: "Ignorés", value: moveAllSkipped.value },
      { label: "Phase prévue", value: total },
      { label: "Phase déplacée", value: moved },
    ];
    return;
  }
  movePanel.progressValue = total > 0 ? Math.round((moved / total) * 100) : null;
  movePanel.stats = [
    { label: "Messages prévus", value: total },
    { label: "Messages déplacés", value: moved },
  ];
}

function setMoveAllSummaryProgress(title: string): void {
  movePanel.visible = true;
  movePanel.title = title;
  movePanel.active = moveAllRunning.value;
  movePanel.progressValue = moveAllTotalPlanned.value > 0
    ? Math.round((moveAllBaseProcessed.value / moveAllTotalPlanned.value) * 100)
    : null;
  movePanel.stats = [
    { label: "Phase", value: `${moveAllCurrentPhaseIndex.value}/${moveAllPhaseCount.value}` },
    { label: "Étape", value: moveAllCurrentPhase.value ? phaseLabel(moveAllCurrentPhase.value) : "-" },
    { label: "Total prévu", value: moveAllTotalPlanned.value },
    { label: "Total traité", value: moveAllBaseProcessed.value },
    { label: "Total déplacé", value: moveAllBaseMoved.value },
    { label: "Ignorés", value: moveAllSkipped.value },
  ];
}

</script>

<template>
  <div class="vue-cleaner-app">
    <div v-if="actionMessage" class="alert alert-ok">{{ actionMessage }}</div>
    <div v-if="actionError" class="alert alert-error">{{ actionError }}</div>

    <section class="vue-panel">
      <div class="cleaner-flow-head">
        <div>
          <span class="label-title">Nettoyage complet</span>
          <p class="muted small">
            Un seul scan, en lecture seule, enchaîne les phases pubs anciennes, règles regex, offres déjà traitées et doublons. Rien n'est déplacé sans tes deux confirmations.
          </p>
        </div>
        <Button type="button" :disabled="fullScanRunning" @click="startFullScan">
          <Search :size="16" />
          {{ fullScanRunning ? 'Scan en cours…' : 'Scanner le nettoyage' }}
        </Button>
      </div>

      <div class="filter-form cleaner-options">
        <label>
          Plus vieux que (jours)
          <input v-model.number="form.minAgeDays" type="number" min="1" max="3650">
        </label>
        <label>
          Mails au plus par phase
          <input v-model.number="form.maxMails" type="number" min="0">
        </label>
        <label>
          Ignorer les N premiers
          <input v-model.number="form.scanOffset" type="number" min="0">
        </label>
      </div>

      <div class="phase-strip">
        <button
          v-for="phase in scanPhases"
          :key="phase.source"
          type="button"
          class="phase-card"
          :class="[`phase-${phaseStatuses[phase.source]}`, { active: activePhase === phase.source }]"
          :aria-pressed="activePhase === phase.source"
          @click="selectPhase(phase.source)"
        >
          <span class="phase-card-head">
            <strong>{{ phase.label }}</strong>
            <span>{{ phaseStatusLabel(phaseStatuses[phase.source]) }}</span>
          </span>
          <span class="muted small">{{ phase.description }}</span>
          <span v-if="phaseResults[phase.source]" class="phase-counts">
            <strong>{{ phaseResults[phase.source]?.report.candidate_count }}</strong> candidat(s)
            <span>{{ phaseResults[phase.source]?.report.scanned_count }} scannés</span>
          </span>
          <span v-else-if="phaseErrors[phase.source]" class="phase-error">{{ phaseErrors[phase.source] }}</span>
        </button>
      </div>
      <p class="muted small cleaner-source-note">{{ sourceDescription(activePhase) }}</p>
    </section>

    <section class="vue-panel">
      <div class="regex-rule-list">
        <div class="regex-rule-head">
          <span class="label-title">Règles regex</span>
          <Button type="button" variant="ghost" size="sm" @click="addRegexRule">
            <Plus :size="14" />
            Ajouter une règle
          </Button>
          <span class="muted small" :class="`regex-save-${regexSaveState}`">{{ regexSaveLabel }}</span>
        </div>
        <div class="regex-rule-scroll">
          <table class="compact-table regex-rule-table">
            <thead>
              <tr>
                <th>Expéditeur</th>
                <th>Objet</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(rule, index) in regexRules" :key="index" :class="{ 'regex-rule-blank': !rule.sender_regex.trim() && !rule.subject_regex.trim() }">
                <td data-label="Expéditeur"><input v-model="rule.sender_regex" type="text" placeholder="amazon|googleplay" :aria-label="`Regex expéditeur, ligne ${index + 1}`"></td>
                <td data-label="Objet"><input v-model="rule.subject_regex" type="text" placeholder="promo|soldes|recommande" :aria-label="`Regex objet, ligne ${index + 1}`"></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p class="muted small">
        Dans une ligne, les champs remplis doivent tous correspondre. Les lignes sont combinées en OU global.
        Ces règles sont sauvegardées automatiquement et utilisées pendant la phase Règles regex.
      </p>
    </section>

    <ProgressPanel
      v-if="scanPanel.visible"
      :title="scanPanel.title"
      :elapsed-seconds="scanPanel.elapsedSeconds"
      :active="scanPanel.active"
      :cancelling="scanPanel.cancelling"
      :progress-value="scanPanel.progressValue"
      :stats="scanPanel.stats"
      @cancel="cancelScan"
    />

    <section v-if="reportResult && currentReport" class="cleaner-report vue-report">
      <div class="stats-grid report-stats">
        <div class="stat-box">
          <span class="muted">Mails scannés</span>
          <strong>{{ currentReport.scanned_count }}</strong>
        </div>
        <div v-if="reportResult.source === 'thunderbird' && reportResult.scan_offset" class="stat-box">
          <span class="muted">Mails ignorés avant scan</span>
          <strong>{{ reportResult.scan_offset }}</strong>
        </div>
        <div class="stat-box">
          <span class="muted">Candidats trouvés</span>
          <strong>{{ currentReport.candidate_count }}</strong>
        </div>
        <div class="stat-box">
          <span class="muted">Factures avec PJ</span>
          <strong>{{ currentReport.skipped_safety }}</strong>
        </div>
        <div class="stat-box">
          <span class="muted">Hors filtre</span>
          <strong>{{ currentReport.skipped_no_match }}</strong>
        </div>
        <div class="stat-box">
          <span class="muted">Trop récents</span>
          <strong>{{ currentReport.skipped_too_recent }}</strong>
        </div>
      </div>

      <div class="report-head-actions">
        <div>
          <span class="label-title">Rapport actif</span>
          <h2>{{ phaseLabel(reportResult.source) }}</h2>
        </div>
        <div class="bulk-actions">
          <span class="muted small"><strong>{{ totalPhaseCandidates }}</strong> candidat(s) toutes phases confondues</span>
          <Button type="button" variant="ghost" @click="exportCsv">
            <Download :size="16" />
            Exporter cette phase en CSV
          </Button>
        </div>
      </div>

      <div v-if="totalPhaseCandidates" class="danger-action cleaner-action-bar">
        <div>
          <strong>Action Thunderbird locale : toutes les phases scannées.</strong>
          <p class="muted">
            {{ totalSelectedCandidates }} mail(s) sélectionné(s) seront déplacés vers la corbeille Thunderbird.
            Un mail trouvé par plusieurs phases n'est compté et déplacé qu'une fois.
          </p>
        </div>
        <div class="cleaner-action-controls">
          <label class="confirm-line">
            <input v-model="confirmThunderbirdClosed" type="checkbox">
            Thunderbird est fermé.
          </label>
          <label class="confirm-line">
            <input v-model="confirmMove" type="checkbox">
            Rapport relu, lancer le déplacement.
          </label>
          <Button
            type="button"
            variant="destructive"
            :disabled="!totalSelectedCandidates || moveAllRunning"
            :aria-describedby="confirmHint?.action === 'move' ? 'cleaner-confirm-hint' : undefined"
            @click="moveAllSelections"
          >
            <Trash2 :size="16" />
            {{ moveAllRunning ? 'Déplacement en cours…' : 'Déplacer toutes les phases sélectionnées' }}
          </Button>
          <Button
            type="button"
            variant="ghost"
            title="Thunderbird reste ouvert : son extension déplacera cette sélection, et elle seule, quand tu cliqueras « Corbeille scan JobMail »."
            :disabled="!totalSelectedCandidates || moveAllRunning || extensionRequestRunning"
            :aria-describedby="confirmHint?.action === 'extension' ? 'cleaner-confirm-hint' : undefined"
            @click="entrustSelectionToExtension"
          >
            <Send :size="16" />
            Confier la sélection à l'extension Thunderbird
          </Button>
          <p v-if="confirmHint" id="cleaner-confirm-hint" class="cleaner-confirm-hint" role="alert">{{ confirmHint.text }}</p>
        </div>

        <ProgressPanel
          v-if="movePanel.visible"
          :title="movePanel.title"
          :elapsed-seconds="movePanel.elapsedSeconds"
          :active="movePanel.active"
          :cancelling="movePanel.cancelling"
          :progress-value="movePanel.progressValue"
          :stats="movePanel.stats"
          @cancel="cancelMove"
        />
      </div>

      <h2>Top expéditeurs</h2>
      <div v-if="currentReport.top_senders.length && reportResult.source !== 'regex'" class="bulk-actions">
        <Button type="button" size="sm" @click="selectAllCandidates">Tout sélectionner</Button>
        <Button type="button" size="sm" variant="ghost" @click="clearSelection">Tout exclure</Button>
        <span class="muted small"><strong>{{ selectedCount }}</strong> mail(s) sélectionné(s) dans cette phase</span>
      </div>
      <div v-if="currentReport.top_senders.length" class="cleaner-table-scroll">
      <table class="compact-table sender-table">
        <thead>
          <tr>
            <th>Expéditeur</th>
            <th v-if="reportResult.source !== 'regex'">Actions</th>
            <th>Nombre</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="sender in currentReport.top_senders"
            :key="sender.sender"
            :class="reportResult.source !== 'regex' ? senderRowClass(sender.sender) : ''"
          >
            <td>{{ sender.sender }}</td>
            <td v-if="reportResult.source !== 'regex'" class="sender-actions">
              <span class="sender-state">{{ senderState(sender.sender) }}</span>
              <Button type="button" size="sm" @click="setSenderSelection(sender.sender, true)">Inclure</Button>
              <Button type="button" size="sm" variant="ghost" @click="setSenderSelection(sender.sender, false)">Exclure</Button>
            </td>
            <td><strong>{{ sender.count }}</strong></td>
          </tr>
        </tbody>
      </table>
      </div>
      <p v-else class="empty">Aucun expéditeur candidat.</p>

      <div class="cleaner-candidates-head">
        <h2>Mails candidats</h2>
        <template v-if="currentReport.candidates.length">
          <span class="muted small cleaner-candidates-count">
            <strong>{{ currentReport.candidates.length }}</strong> candidat(s) dans cette phase,
            <strong>{{ selectedCount }}</strong> sélectionné(s)
          </span>
          <Button
            id="cleaner-candidates-toggle"
            type="button"
            size="sm"
            variant="ghost"
            class="cleaner-candidates-toggle"
            :aria-expanded="candidatesOpen"
            aria-controls="cleaner-candidates-list"
            @click="toggleCandidates"
          >
            <component :is="candidatesOpen ? ChevronUp : ChevronDown" :size="14" />
            {{ candidatesOpen ? 'Replier la liste' : 'Afficher la liste' }}
          </Button>
        </template>
      </div>
      <div
        v-if="currentReport.candidates.length"
        v-show="candidatesOpen"
        id="cleaner-candidates-list"
        class="cleaner-table-scroll cleaner-cards-scroll"
      >
      <table class="offers cleaner-table">
        <thead>
          <tr>
            <th>Sélection</th>
            <th>Source</th>
            <th>Date</th>
            <th>Expéditeur</th>
            <th>Sujet</th>
            <th v-if="reportResult.source === 'parsed_jobs'">Offre</th>
            <th v-if="reportResult.source === 'duplicates'">Doublon</th>
            <th>Raison</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="candidate in currentReport.candidates" :key="candidate.uid">
            <td data-label="Sélection">
              <span v-if="reportResult.source === 'regex'" class="chip">regex</span>
              <input
                v-else-if="candidate.can_move"
                type="checkbox"
                :aria-label="`Sélectionner : ${candidate.subject || candidate.sender}`"
                :checked="selectedUids.has(candidate.uid)"
                @change="toggleCandidate(candidate.uid, ($event.target as HTMLInputElement).checked)"
              >
              <span v-else class="muted small">lecture seule</span>
            </td>
            <td data-label="Source">
              <span class="chip">{{ candidate.source }}</span>
              <span v-if="candidate.mailbox" class="muted small">{{ candidate.mailbox }}</span>
            </td>
            <td class="muted small cleaner-date" data-label="Date">{{ candidate.received_date }}</td>
            <td data-label="Expéditeur">{{ candidate.sender }}</td>
            <td data-label="Sujet">{{ candidate.subject }}</td>
            <td v-if="reportResult.source === 'parsed_jobs'" data-label="Offre">
              <a v-if="candidate.offer_id" class="btn btn-sm btn-ghost" :href="`/offers/${candidate.offer_id}`">
                <ExternalLink :size="13" />
                Voir
              </a>
              <span v-else class="muted small">-</span>
            </td>
            <td v-if="reportResult.source === 'duplicates'" data-label="Doublon">
              <span class="muted small">{{ candidate.duplicate_of }}</span>
            </td>
            <td data-label="Raison"><span class="chip">{{ candidate.reason }}</span></td>
          </tr>
        </tbody>
      </table>
      <div class="cleaner-candidates-foot">
        <Button type="button" size="sm" variant="ghost" @click="collapseCandidatesFromBottom">
          <ChevronUp :size="14" />
          Replier la liste
        </Button>
      </div>
      </div>
      <p v-else class="empty">{{ emptyCandidatesMessage }}</p>

    </section>
  </div>
</template>
