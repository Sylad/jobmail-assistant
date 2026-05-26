<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { Download, ExternalLink, Plus, RotateCcw, Search, Trash2 } from "@lucide/vue";
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

const sources: Array<{ value: CleanerSource; label: string }> = [
  { value: "thunderbird", label: "Thunderbird MBOX" },
  { value: "regex", label: "Regex Thunderbird" },
  { value: "parsed_jobs", label: "Jobs deja parses" },
  { value: "duplicates", label: "Doublons Orange/Gmail" },
  { value: "imap", label: "IMAP" },
];

const form = reactive({
  source: props.initial.source ?? "thunderbird",
  minAgeDays: props.initial.min_age_days ?? 7,
  maxMails: props.initial.max_mails ?? 250,
  scanOffset: props.initial.scan_offset ?? 0,
});

const regexRules = ref<RegexRule[]>(normalizeRules(props.initial.regex_rules ?? []));
const reportResult = ref<CleanerScanResultPayload | null>(null);
const selectedUids = ref<Set<string>>(new Set());
const confirmMove = ref(false);
const confirmThunderbirdClosed = ref(false);
const actionMessage = ref("");
const actionError = ref("");
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
const canMoveSelection = computed(() => {
  if (!reportResult.value || !currentReport.value?.candidate_count) return false;
  if (reportResult.value.source === "regex") return currentReport.value.candidate_count > 0;
  return selectedCount.value > 0;
});

function normalizeRules(rules: RegexRule[]): RegexRule[] {
  const clean = rules.filter((rule) => rule.sender_regex || rule.subject_regex);
  while (clean.length < 5) clean.push({ sender_regex: "", subject_regex: "" });
  return clean;
}

function defaultScanStats() {
  return [
    { label: "Mails scannes", value: 0 },
    { label: "Candidats", value: 0 },
    { label: "Factures", value: 0 },
    { label: "Hors regex", value: 0 },
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

function scanButtonLabel(source: CleanerSource): string {
  if (source === "parsed_jobs") return "Scanner jobs nettoyables";
  if (source === "duplicates") return "Scanner doublons";
  if (source === "regex") return "Scanner regex";
  return "Scanner pubs anciennes";
}

function moveHelpText(): string {
  if (reportResult.value?.source === "imap") {
    return `Les messages selectionnes seront deplaces vers ${reportResult.value.delete_folder}.`;
  }
  return "Ferme Thunderbird avant de lancer l'action. JobMail fera un backup hors des dossiers Mail Thunderbird puis deplacera les messages vers la corbeille locale.";
}

function addRegexRule(): void {
  regexRules.value.push({ sender_regex: "", subject_regex: "" });
}

function cleanRegexRules(): RegexRule[] {
  return regexRules.value
    .map((rule) => ({
      sender_regex: rule.sender_regex.trim(),
      subject_regex: rule.subject_regex.trim(),
    }))
    .filter((rule) => rule.sender_regex || rule.subject_regex);
}

function scanFormData(extra?: Record<string, string>): FormData {
  const data = new FormData();
  data.set("source", form.source);
  data.set("min_age_days", String(form.minAgeDays));
  data.set("max_mails", String(form.maxMails));
  data.set("scan_offset", String(form.scanOffset));
  if (form.source === "regex") {
    cleanRegexRules().forEach((rule) => {
      data.append("sender_regex_rule", rule.sender_regex);
      data.append("subject_regex_rule", rule.subject_regex);
    });
  }
  Object.entries(extra ?? {}).forEach(([key, value]) => data.set(key, value));
  return data;
}

async function startScan(offset = form.scanOffset): Promise<void> {
  actionMessage.value = "";
  actionError.value = "";
  form.scanOffset = Math.max(0, offset);
  reportResult.value = null;
  selectedUids.value = new Set();
  confirmMove.value = false;
  confirmThunderbirdClosed.value = false;
  showScanPanel("Scan en cours");

  try {
    const response = await fetch("/cleaner/scan/start", {
      method: "POST",
      body: scanFormData(),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "Impossible de lancer le scan.");
    }
    const payload = await response.json() as CleanerScanJobPayload;
    currentScanJobId = payload.id;
    setScanProgress(payload);
    await pollScan(payload.id);
  } catch (error) {
    scanPanel.title = error instanceof Error ? error.message : "Scan en erreur";
    scanPanel.active = false;
  }
}

async function pollScan(jobId: string): Promise<void> {
  const response = await fetch(`/cleaner/scan/status/${jobId}`);
  if (!response.ok) throw new Error("Impossible de lire le statut du scan.");
  const payload = await response.json() as CleanerScanJobPayload;
  setScanProgress(payload);

  if (payload.status === "done") {
    scanPanel.title = "Scan termine";
    scanPanel.active = false;
    await loadScanResult(payload.result_json_url);
    return;
  }
  if (payload.status === "cancelled") {
    scanPanel.title = "Scan annule";
    scanPanel.active = false;
    scanPanel.cancelling = false;
    return;
  }
  if (payload.status === "error") {
    scanPanel.title = payload.error || "Scan en erreur";
    scanPanel.active = false;
    scanPanel.cancelling = false;
    return;
  }
  window.setTimeout(() => {
    pollScan(jobId).catch((error: unknown) => {
      scanPanel.title = error instanceof Error ? error.message : "Scan en erreur";
      scanPanel.active = false;
      scanPanel.cancelling = false;
    });
  }, 700);
}

async function loadScanResult(url: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Impossible de charger le rapport.");
  }
  const payload = await response.json() as CleanerScanResultPayload;
  reportResult.value = payload;
  form.source = payload.source;
  form.minAgeDays = payload.min_age_days;
  form.maxMails = payload.max_mails;
  form.scanOffset = payload.scan_offset;
  regexRules.value = normalizeRules(payload.regex_rules);
  selectAllCandidates();
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

function setScanProgress(payload: CleanerScanJobPayload): void {
  scanPanel.elapsedSeconds = payload.elapsed_seconds || 0;
  scanPanel.stats = [
    { label: "Mails scannes", value: payload.scanned_count || 0 },
    { label: "Candidats", value: payload.candidate_count || 0 },
    { label: "Factures", value: payload.skipped_safety || 0 },
    { label: "Hors regex", value: payload.skipped_no_match || 0 },
    { label: "Trop recents", value: payload.skipped_too_recent || 0 },
    ...(payload.current_mailbox ? [{ label: "Boite", value: payload.current_mailbox }] : []),
  ];
}

function exportCsv(): void {
  const formElement = document.createElement("form");
  formElement.method = "POST";
  formElement.action = "/cleaner/scan";
  formElement.style.display = "none";
  const data = scanFormData({ export_csv: "1" });
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

function selectAllCandidates(): void {
  selectedUids.value = new Set(movableCandidates.value.map((candidate) => candidate.uid));
}

function clearSelection(): void {
  selectedUids.value = new Set();
}

function setSenderSelection(sender: string, selected: boolean): void {
  const next = new Set(selectedUids.value);
  movableCandidates.value
    .filter((candidate) => candidate.sender === sender)
    .forEach((candidate) => {
      if (selected) next.add(candidate.uid);
      else next.delete(candidate.uid);
    });
  selectedUids.value = next;
}

function toggleCandidate(uid: string, selected: boolean): void {
  const next = new Set(selectedUids.value);
  if (selected) next.add(uid);
  else next.delete(uid);
  selectedUids.value = next;
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

function submitHtmlMove(action: string, fields: Record<string, string | string[]>): void {
  const formElement = document.createElement("form");
  formElement.method = "POST";
  formElement.action = action;
  formElement.style.display = "none";
  Object.entries(fields).forEach(([key, value]) => {
    const values = Array.isArray(value) ? value : [value];
    values.forEach((entry) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = key;
      input.value = entry;
      formElement.appendChild(input);
    });
  });
  document.body.appendChild(formElement);
  formElement.submit();
  formElement.remove();
}

async function moveSelection(): Promise<void> {
  actionError.value = "";
  actionMessage.value = "";
  if (!reportResult.value || !canMoveSelection.value) return;
  if (!confirmMove.value || (reportResult.value.source !== "imap" && !confirmThunderbirdClosed.value)) {
    actionError.value = "Confirmation obligatoire avant tout deplacement.";
    return;
  }

  if (reportResult.value.source === "regex") {
    await moveRegexResults();
    return;
  }

  const fields: Record<string, string | string[]> = {
    source: reportResult.value.source,
    min_age_days: String(reportResult.value.min_age_days),
    max_mails: String(reportResult.value.max_mails),
    selected_uid: Array.from(selectedUids.value),
    confirm_move: "yes",
  };
  if (reportResult.value.source === "imap") {
    submitHtmlMove("/cleaner/move-to-delete", fields);
  } else {
    submitHtmlMove("/cleaner/move-thunderbird-to-trash", {
      ...fields,
      confirm_thunderbird_closed: "yes",
    });
  }
}

async function moveRegexResults(): Promise<void> {
  if (!reportResult.value) return;
  showMovePanel();
  const data = new FormData();
  data.set("source", "regex");
  data.set("regex_job_id", reportResult.value.regex_job_id);
  data.set("confirm_move", "yes");
  data.set("confirm_thunderbird_closed", "yes");
  const response = await fetch("/cleaner/move-thunderbird-to-trash/start", {
    method: "POST",
    body: data,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    movePanel.title = payload.detail || "Impossible de lancer le deplacement.";
    movePanel.active = false;
    return;
  }
  const payload = await response.json() as CleanerMoveJobPayload;
  currentMoveJobId = payload.id;
  setMoveProgress(payload);
  await pollMove(payload.id);
}

function showMovePanel(): void {
  movePanel.visible = true;
  movePanel.title = "Deplacement en cours";
  movePanel.elapsedSeconds = 0;
  movePanel.active = true;
  movePanel.cancelling = false;
  movePanel.progressValue = null;
  movePanel.stats = [
    { label: "Messages prevus", value: 0 },
    { label: "Messages deplaces", value: 0 },
  ];
}

async function pollMove(jobId: string): Promise<void> {
  const response = await fetch(`/cleaner/move/status/${jobId}`);
  if (!response.ok) throw new Error("Impossible de lire le statut du deplacement.");
  const payload = await response.json() as CleanerMoveJobPayload;
  setMoveProgress(payload);
  if (payload.status === "done") {
    movePanel.title = "Deplacement termine";
    movePanel.active = false;
    await loadMoveResult(`/cleaner/move/status/${jobId}/result-json`);
    return;
  }
  if (payload.status === "cancelled") {
    movePanel.title = "Deplacement annule";
    movePanel.active = false;
    movePanel.cancelling = false;
    return;
  }
  if (payload.status === "error") {
    movePanel.title = payload.error || "Deplacement en erreur";
    movePanel.active = false;
    movePanel.cancelling = false;
    return;
  }
  window.setTimeout(() => pollMove(jobId).catch((error: unknown) => {
    movePanel.title = error instanceof Error ? error.message : "Deplacement en erreur";
    movePanel.active = false;
    movePanel.cancelling = false;
  }), 700);
}

async function loadMoveResult(url: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) return;
  const payload = await response.json();
  actionMessage.value = `${payload.moved_count} mail(s) deplace(s) vers ${payload.moved_destination}.`;
  if (reportResult.value) {
    reportResult.value.report = payload.report;
    reportResult.value.regex_rules = payload.regex_rules;
  }
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
  movePanel.progressValue = total > 0 ? Math.round((moved / total) * 100) : null;
  movePanel.stats = [
    { label: "Messages prevus", value: total },
    { label: "Messages deplaces", value: moved },
  ];
}

function nextBatchOffset(): number {
  if (!reportResult.value) return form.scanOffset;
  return reportResult.value.scan_offset + reportResult.value.report.scanned_count;
}

function moveButtonLabel(): string {
  if (!reportResult.value) return "Deplacer la selection";
  if (reportResult.value.source === "regex") return "Deplacer tous les resultats regex vers la corbeille Thunderbird";
  if (reportResult.value.source === "duplicates") return "Deplacer les doublons selectionnes vers la corbeille Thunderbird";
  if (reportResult.value.source === "imap") return `Deplacer la selection vers ${reportResult.value.delete_folder}`;
  return "Deplacer la selection vers la corbeille Thunderbird";
}
</script>

<template>
  <div class="vue-cleaner-app">
    <div v-if="actionMessage" class="alert alert-ok">{{ actionMessage }}</div>
    <div v-if="actionError" class="alert alert-error">{{ actionError }}</div>

    <section class="vue-panel">
      <div class="filter-form">
        <label>
          Source
          <select v-model="form.source">
            <option v-for="source in sources" :key="source.value" :value="source.value">
              {{ source.label }}
            </option>
          </select>
        </label>
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
        <Button type="button" @click="startScan()">
          <Search :size="16" />
          {{ scanButtonLabel(form.source) }}
        </Button>
        <Button type="button" variant="ghost" @click="exportCsv">
          <Download :size="16" />
          Exporter rapport CSV
        </Button>
      </div>
      <p class="muted small">{{ sourceDescription(form.source) }}</p>
    </section>

    <section class="vue-panel">
      <div class="regex-rule-list">
        <span class="label-title">Regles regex</span>
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
        <Button type="button" variant="ghost" size="sm" @click="addRegexRule">
          <Plus :size="14" />
          Ajouter une regle
        </Button>
      </div>
      <p class="muted small">
        Dans une ligne, les champs remplis doivent tous correspondre. Les lignes sont combinees en OU global.
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
      <div class="stats-grid">
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
          <span class="muted">Exclus facture</span>
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

      <div v-if="reportResult.source === 'thunderbird'" class="bulk-actions">
        <Button type="button" variant="secondary" @click="startScan(nextBatchOffset())">
          <RotateCcw :size="15" />
          Scanner les {{ reportResult.max_mails }} suivants
        </Button>
        <span class="muted small">
          Tranche actuelle : {{ reportResult.scan_offset + 1 }} - {{ reportResult.scan_offset + currentReport.scanned_count }}
        </span>
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

      <div v-if="currentReport.candidates.length" class="danger-action">
        <strong>{{ reportResult.source === 'imap' ? 'Action IMAP.' : 'Action Thunderbird locale.' }}</strong>
        <p class="muted">{{ moveHelpText() }}</p>
        <label v-if="reportResult.source !== 'imap'" class="confirm-line">
          <input v-model="confirmThunderbirdClosed" type="checkbox">
          Je confirme que Thunderbird est ferme.
        </label>
        <label class="confirm-line">
          <input v-model="confirmMove" type="checkbox">
          Je confirme avoir relu le rapport et veux lancer le deplacement.
        </label>
        <Button type="button" variant="destructive" :disabled="!canMoveSelection" @click="moveSelection">
          <Trash2 :size="16" />
          {{ moveButtonLabel() }}
        </Button>

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
    </section>
  </div>
</template>
