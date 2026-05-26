<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { Download, ExternalLink, Plus, Search, Trash2 } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import ProgressPanel from "./ProgressPanel.vue";
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
    description: "Heuristique newsletters et publicites anciennes.",
  },
  {
    source: "regex",
    label: "Regles regex",
    description: "Filtres expediteur/objet que tu pilotes.",
  },
  {
    source: "parsed_jobs",
    label: "Jobs cleanup",
    description: "Mails de jobs deja extraits et peu utiles.",
  },
  {
    source: "duplicates",
    label: "Doublons",
    description: "Copies Orange deja presentes cote Gmail.",
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
const moveAllBaseMoved = ref(0);
const moveAllTotalPlanned = ref(0);
const moveAllCurrentPhaseIndex = ref(0);
const moveAllPhaseCount = ref(0);
const moveAllCurrentPhase = ref<CleanerPhaseSource | null>(null);
const selectedUids = ref<Set<string>>(new Set());
const confirmMove = ref(false);
const confirmThunderbirdClosed = ref(false);
const actionMessage = ref("");
const actionError = ref("");
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
  title: "Deplacement en cours",
  elapsedSeconds: 0,
  active: false,
  cancelling: false,
  progressValue: null,
  stats: [
    { label: "Messages prevus", value: 0 },
    { label: "Messages deplaces", value: 0 },
  ],
});

const currentReport = computed<CleanerReportPayload | null>(() => reportResult.value?.report ?? null);
const movableCandidates = computed(() => currentReport.value?.candidates.filter((candidate) => candidate.can_move) ?? []);
const selectedCount = computed(() => selectedUids.value.size);
const totalPhaseCandidates = computed(() => scanPhases.reduce((sum, phase) => sum + (phaseResults[phase.source]?.report.candidate_count ?? 0), 0));
const totalSelectedCandidates = computed(() => {
  const uids = new Set<string>();
  scanPhases.forEach((phase) => {
    const result = phaseResults[phase.source];
    if (!result) return;
    const selected = phase.source === "regex"
      ? result.report.candidates.map((candidate) => candidate.uid)
      : phaseSelections[phase.source];
    selected.forEach((uid) => uids.add(uid));
  });
  return uids.size;
});
const regexSaveLabel = computed(() => {
  if (regexSaveState.value === "saving") return "Sauvegarde...";
  if (regexSaveState.value === "dirty") return "Modifications non sauvegardees";
  if (regexSaveState.value === "error") return "Sauvegarde en erreur";
  return "Regles sauvegardees";
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
    { label: "Mails scannes", value: 0 },
    { label: "Candidats", value: 0 },
    { label: "Factures avec PJ", value: 0 },
    { label: form.source === "regex" ? "Hors regex" : "Hors filtre", value: 0 },
    { label: "Trop recents", value: 0 },
  ];
}

function sourceDescription(source: CleanerSource): string {
  if (source === "parsed_jobs") {
    return "Source SQLite : mails de jobs deja extraits. Seuls les mails associes a une offre ignored ou score <= 3 sont proposes.";
  }
  if (source === "duplicates") {
    return "Source Thunderbird : propose uniquement les copies Orange dont le meme Message-Id existe dans une boite Gmail.";
  }
  if (source === "regex") {
    return "Les lignes regex sont combinees en OU global. Dans une ligne, les champs remplis doivent tous correspondre.";
  }
  if (source === "imap") {
    return props.initial.imap_enabled ? `Source IMAP configuree, deplacement vers ${props.initial.delete_folder}.` : "IMAP n'est pas configure.";
  }
  return `MBOX scannes : ${props.initial.mbox_patterns.join(", ")}`;
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
  } catch (error) {
    scanPanel.title = error instanceof Error ? error.message : "Scan en erreur";
    scanPanel.active = false;
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
    scanPanel.title = fullScanRunning.value ? `Phase terminee : ${phaseLabel(source)}` : "Scan termine";
    scanPanel.active = false;
    return await loadScanResult(payload.result_json_url, false);
  }
  if (payload.status === "cancelled") {
    scanPanel.title = "Scan annule";
    scanPanel.active = false;
    scanPanel.cancelling = false;
    return null;
  }
  if (payload.status === "error") {
    scanPanel.title = payload.error || "Scan en erreur";
    scanPanel.active = false;
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
  scanPanel.title = "Arret demande";
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
    { label: "Mails scannes", value: payload.scanned_count || 0 },
    { label: "Candidats", value: payload.candidate_count || 0 },
    { label: "Factures avec PJ", value: payload.skipped_safety || 0 },
    { label: source === "regex" ? "Hors regex" : "Hors filtre", value: payload.skipped_no_match || 0 },
    { label: "Trop recents", value: payload.skipped_too_recent || 0 },
    ...(payload.current_mailbox ? [{ label: "Boite", value: payload.current_mailbox }] : []),
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
  if (status === "done") return "Termine";
  if (status === "cancelled") return "Annule";
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
  phaseSelections[source] = result.report.candidates.filter((candidate) => candidate.can_move).map((candidate) => candidate.uid);
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
  if (!confirmMove.value || !confirmThunderbirdClosed.value) {
    actionError.value = "Confirmation obligatoire avant tout deplacement.";
    return;
  }
  if (totalSelectedCandidates.value <= 0) return;

  moveAllRunning.value = true;
  moveAllBaseMoved.value = 0;
  moveAllCurrentPhase.value = null;
  const alreadyQueued = new Set<string>();
  const phaseMoves = scanPhases.flatMap((phase) => {
    const result = phaseResults[phase.source];
    if (!result) return [];
    const uids = selectedUidsForMove(phase.source, result).filter((uid) => {
      if (alreadyQueued.has(uid)) return false;
      alreadyQueued.add(uid);
      return true;
    });
    return uids.length ? [{ phase, result, uids }] : [];
  });
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
      const moved = await moveThunderbirdResults(moveFieldsForPhase(result, uids));
      movedTotal += moved;
      moveAllBaseMoved.value = movedTotal;
    }
    actionMessage.value = movePanel.cancelling
      ? `${movedTotal} mail(s) deplace(s) avant l'arret demande.`
      : `${movedTotal} mail(s) deplace(s) vers la corbeille Thunderbird depuis toutes les phases.`;
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : "Deplacement en erreur.";
  } finally {
    moveAllRunning.value = false;
    moveAllCurrentPhase.value = null;
  }
}

function selectedUidsForMove(source: CleanerPhaseSource, result: CleanerScanResultPayload): string[] {
  if (source === "regex") {
    return result.report.candidates.map((candidate) => candidate.uid);
  }
  return phaseSelections[source];
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

async function moveThunderbirdResults(fields?: Record<string, string | string[]>): Promise<number> {
  if (!reportResult.value) return 0;
  showMovePanel();
  const data = new FormData();
  if (fields) {
    Object.entries(fields).forEach(([key, value]) => {
      const values = Array.isArray(value) ? value : [value];
      values.forEach((entry) => data.append(key, entry));
    });
  } else {
    data.set("source", "regex");
    data.set("regex_job_id", reportResult.value.regex_job_id);
    data.set("confirm_move", "yes");
  }
  data.set("confirm_thunderbird_closed", "yes");
  const response = await fetch("/cleaner/move-thunderbird-to-trash/start", {
    method: "POST",
    body: data,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    movePanel.title = payload.detail || "Impossible de lancer le deplacement.";
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
    ? `Deplacement en cours : ${phaseLabel(moveAllCurrentPhase.value)}`
    : "Deplacement en cours";
  movePanel.elapsedSeconds = 0;
  movePanel.active = true;
  movePanel.cancelling = false;
  movePanel.progressValue = null;
  movePanel.stats = [
    { label: "Messages prevus", value: 0 },
    { label: "Messages deplaces", value: 0 },
  ];
}

async function pollMove(jobId: string): Promise<number> {
  const response = await fetch(`/cleaner/move/status/${jobId}`);
  if (!response.ok) throw new Error("Impossible de lire le statut du deplacement.");
  const payload = await response.json() as CleanerMoveJobPayload;
  setMoveProgress(payload);
  if (payload.status === "done") {
    movePanel.title = "Deplacement termine";
    movePanel.active = false;
    return await loadMoveResult(payload.result_json_url || `/cleaner/move/status/${jobId}/result-json`);
  }
  if (payload.status === "cancelled") {
    movePanel.title = "Deplacement annule";
    movePanel.active = false;
    movePanel.cancelling = false;
    return payload.moved_count || 0;
  }
  if (payload.status === "error") {
    movePanel.title = payload.error || "Deplacement en erreur";
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
  actionMessage.value = `${payload.moved_count} mail(s) deplace(s) vers ${payload.moved_destination}.`;
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
  movePanel.title = "Arret demande";
  await fetch(`/cleaner/move/cancel/${currentMoveJobId}`, { method: "POST" }).catch(() => {});
}

function setMoveProgress(payload: CleanerMoveJobPayload): void {
  movePanel.elapsedSeconds = payload.elapsed_seconds || 0;
  const total = payload.total_count || 0;
  const moved = payload.moved_count || 0;
  if (moveAllRunning.value && moveAllCurrentPhase.value) {
    const globalMoved = moveAllBaseMoved.value + moved;
    movePanel.title = `Deplacement en cours : ${phaseLabel(moveAllCurrentPhase.value)}`;
    movePanel.progressValue = moveAllTotalPlanned.value > 0
      ? Math.round((globalMoved / moveAllTotalPlanned.value) * 100)
      : null;
    movePanel.stats = [
      { label: "Phase", value: `${moveAllCurrentPhaseIndex.value}/${moveAllPhaseCount.value}` },
      { label: "Etape", value: phaseLabel(moveAllCurrentPhase.value) },
      { label: "Total prevu", value: moveAllTotalPlanned.value },
      { label: "Total deplace", value: globalMoved },
      { label: "Phase prevue", value: total },
      { label: "Phase deplacee", value: moved },
    ];
    return;
  }
  movePanel.progressValue = total > 0 ? Math.round((moved / total) * 100) : null;
  movePanel.stats = [
    { label: "Messages prevus", value: total },
    { label: "Messages deplaces", value: moved },
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
            Un seul scan lance les phases pubs anciennes, regex, jobs cleanup et doublons.
          </p>
        </div>
        <Button type="button" :disabled="fullScanRunning" @click="startFullScan">
          <Search :size="16" />
          {{ fullScanRunning ? 'Scan en cours...' : 'Scanner le nettoyage' }}
        </Button>
      </div>

      <div class="filter-form cleaner-options">
        <label>
          Plus vieux que (jours)
          <input v-model.number="form.minAgeDays" type="number" min="1" max="3650">
        </label>
        <label>
          Limite max-mails
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
          @click="selectPhase(phase.source)"
        >
          <span class="phase-card-head">
            <strong>{{ phase.label }}</strong>
            <span>{{ phaseStatusLabel(phaseStatuses[phase.source]) }}</span>
          </span>
          <span class="muted small">{{ phase.description }}</span>
          <span v-if="phaseResults[phase.source]" class="phase-counts">
            <strong>{{ phaseResults[phase.source]?.report.candidate_count }}</strong> candidat(s)
            <span>{{ phaseResults[phase.source]?.report.scanned_count }} scannes</span>
          </span>
          <span v-else-if="phaseErrors[phase.source]" class="phase-error">{{ phaseErrors[phase.source] }}</span>
        </button>
      </div>
      <p class="muted small">{{ sourceDescription(activePhase) }}</p>
    </section>

    <section class="vue-panel">
      <div class="regex-rule-list">
        <div class="regex-rule-head">
          <span class="label-title">Regles regex</span>
          <Button type="button" variant="ghost" size="sm" @click="addRegexRule">
            <Plus :size="14" />
            Ajouter une regle
          </Button>
          <span class="muted small" :class="`regex-save-${regexSaveState}`">{{ regexSaveLabel }}</span>
        </div>
        <div class="regex-rule-scroll">
          <table class="compact-table regex-rule-table">
            <thead>
              <tr>
                <th>Expediteur</th>
                <th>Objet</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(rule, index) in regexRules" :key="index">
                <td><input v-model="rule.sender_regex" type="text" placeholder="amazon|googleplay"></td>
                <td><input v-model="rule.subject_regex" type="text" placeholder="promo|soldes|recommande"></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p class="muted small">
        Dans une ligne, les champs remplis doivent tous correspondre. Les lignes sont combinees en OU global.
        Ces regles sont sauvegardees automatiquement et utilisees pendant la phase Regex Thunderbird.
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
          <span class="muted">Mails scannes</span>
          <strong>{{ currentReport.scanned_count }}</strong>
        </div>
        <div v-if="reportResult.source === 'thunderbird' && reportResult.scan_offset" class="stat-box">
          <span class="muted">Mails ignores avant scan</span>
          <strong>{{ reportResult.scan_offset }}</strong>
        </div>
        <div class="stat-box">
          <span class="muted">Candidats trouves</span>
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
          <span class="muted">Trop recents</span>
          <strong>{{ currentReport.skipped_too_recent }}</strong>
        </div>
      </div>

      <div class="report-head-actions">
        <div>
          <span class="label-title">Rapport actif</span>
          <h2>{{ phaseLabel(reportResult.source) }}</h2>
        </div>
        <div class="bulk-actions">
          <span class="muted small"><strong>{{ totalPhaseCandidates }}</strong> candidat(s) sur tout le nettoyage</span>
          <Button type="button" variant="ghost" @click="exportCsv">
            <Download :size="16" />
            Exporter cette phase CSV
          </Button>
        </div>
      </div>

      <div v-if="totalPhaseCandidates" class="danger-action cleaner-action-bar">
        <div>
          <strong>Action Thunderbird locale : toutes les phases scannees.</strong>
          <p class="muted">
            {{ totalSelectedCandidates }} mail(s) selectionne(s) seront deplaces vers la corbeille Thunderbird.
            Les doublons entre phases sont ignores pour ne pas traiter deux fois le meme message.
          </p>
        </div>
        <div class="cleaner-action-controls">
          <label class="confirm-line">
            <input v-model="confirmThunderbirdClosed" type="checkbox">
            Thunderbird est ferme.
          </label>
          <label class="confirm-line">
            <input v-model="confirmMove" type="checkbox">
            Rapport relu, lancer le deplacement.
          </label>
          <Button
            type="button"
            variant="destructive"
            :disabled="!totalSelectedCandidates || moveAllRunning"
            @click="moveAllSelections"
          >
            <Trash2 :size="16" />
            {{ moveAllRunning ? 'Deplacement en cours...' : 'Deplacer toutes les phases selectionnees' }}
          </Button>
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

      <h2>Top expediteurs</h2>
      <div v-if="currentReport.top_senders.length && reportResult.source !== 'regex'" class="bulk-actions">
        <Button type="button" size="sm" @click="selectAllCandidates">Tout selectionner</Button>
        <Button type="button" size="sm" variant="ghost" @click="clearSelection">Tout exclure</Button>
        <span class="muted small"><strong>{{ selectedCount }}</strong> mail(s) selectionne(s)</span>
      </div>
      <table v-if="currentReport.top_senders.length" class="compact-table sender-table">
        <thead>
          <tr>
            <th>Expediteur</th>
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
      <p v-else class="empty">Aucun expediteur candidat.</p>

      <h2>Mails candidats</h2>
      <table v-if="currentReport.candidates.length" class="offers cleaner-table">
        <thead>
          <tr>
            <th>Selection</th>
            <th>Source</th>
            <th>Date</th>
            <th>Expediteur</th>
            <th>Sujet</th>
            <th v-if="reportResult.source === 'parsed_jobs'">Offre</th>
            <th v-if="reportResult.source === 'duplicates'">Doublon</th>
            <th>Raison</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="candidate in currentReport.candidates" :key="candidate.uid">
            <td>
              <span v-if="reportResult.source === 'regex'" class="chip">regex</span>
              <input
                v-else-if="candidate.can_move"
                type="checkbox"
                :checked="selectedUids.has(candidate.uid)"
                @change="toggleCandidate(candidate.uid, ($event.target as HTMLInputElement).checked)"
              >
              <span v-else class="muted small">scan only</span>
            </td>
            <td>
              <span class="chip">{{ candidate.source }}</span>
              <span v-if="candidate.mailbox" class="muted small">{{ candidate.mailbox }}</span>
            </td>
            <td class="muted small">{{ candidate.received_date }}</td>
            <td>{{ candidate.sender }}</td>
            <td>{{ candidate.subject }}</td>
            <td v-if="reportResult.source === 'parsed_jobs'">
              <a v-if="candidate.offer_id" class="btn btn-sm btn-ghost" :href="`/offers/${candidate.offer_id}`">
                <ExternalLink :size="13" />
                Voir
              </a>
              <span v-else class="muted small">-</span>
            </td>
            <td v-if="reportResult.source === 'duplicates'">
              <span class="muted small">{{ candidate.duplicate_of }}</span>
            </td>
            <td><span class="chip">{{ candidate.reason }}</span></td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">Aucun candidat trouve avec ces criteres.</p>

    </section>
  </div>
</template>
