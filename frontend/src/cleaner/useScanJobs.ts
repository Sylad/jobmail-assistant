import { reactive } from "vue";
import { getSubmitter, query, queryAll } from "./dom";
import type { CleanerScanJobPayload, ProgressPanelState } from "./types";

export function useScanJobs() {
  let currentScanJobId = "";
  let activeScanButton: HTMLElement | null = null;
  const panel = reactive<ProgressPanelState>({
    visible: false,
    title: "Scan en cours",
    elapsedSeconds: 0,
    active: false,
    cancelling: false,
    progressValue: null,
    stats: [
      { label: "Mails scannes", value: 0 },
      { label: "Candidats", value: 0 },
      { label: "Factures", value: 0 },
      { label: "Hors regex", value: 0 },
      { label: "Trop recents", value: 0 },
    ],
  });

  function initScanForms(): void {
    const forms = queryAll<HTMLFormElement>("[data-async-scan-form]");
    if (!forms.length) return;

    forms.forEach((form) => {
      const startButton = query<HTMLButtonElement>("[data-start-regex-scan]", form);
      startButton?.addEventListener("click", (event) => startScan(event, form, startButton));
      form.addEventListener("submit", async (event) => {
        const submitter = getSubmitter(event);
        if (submitter instanceof HTMLButtonElement && submitter.name === "export_csv") return;
        await startScan(event, form, submitter);
      });
    });
  }

  async function startScan(
    event: Event,
    form: HTMLFormElement,
    submitButton: HTMLElement | null,
  ): Promise<void> {
    event.preventDefault();
    showPanel("Scan en cours");
    document.querySelector("#cleaner-vue-root")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    activeScanButton = submitButton
      || query<HTMLButtonElement>("[data-start-regex-scan]", form)
      || query<HTMLButtonElement>("button[type='submit']:not([name='export_csv'])", form);
    if (activeScanButton instanceof HTMLButtonElement) activeScanButton.disabled = true;

    try {
      const response = await fetch("/cleaner/scan/start", {
        method: "POST",
        body: new FormData(form),
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
      panel.title = error instanceof Error ? error.message : "Scan en erreur";
      panel.active = false;
      if (activeScanButton instanceof HTMLButtonElement) activeScanButton.disabled = false;
    }
  }

  async function pollScan(jobId: string): Promise<void> {
    const response = await fetch(`/cleaner/scan/status/${jobId}`);
    if (!response.ok) throw new Error("Impossible de lire le statut du scan.");
    const payload = await response.json() as CleanerScanJobPayload;
    setScanProgress(payload);
    if (payload.status === "done") {
      panel.title = "Scan termine";
      panel.active = false;
      window.location.href = payload.result_url;
      return;
    }
    if (payload.status === "cancelled") {
      panel.title = "Scan annule";
      panel.active = false;
      panel.cancelling = false;
      if (activeScanButton instanceof HTMLButtonElement) activeScanButton.disabled = false;
      return;
    }
    if (payload.status === "error") {
      panel.title = payload.error || "Scan en erreur";
      panel.active = false;
      panel.cancelling = false;
      if (activeScanButton instanceof HTMLButtonElement) activeScanButton.disabled = false;
      return;
    }
    window.setTimeout(() => {
      pollScan(jobId).catch((error: unknown) => {
        panel.title = error instanceof Error ? error.message : "Scan en erreur";
        panel.active = false;
        panel.cancelling = false;
        if (activeScanButton instanceof HTMLButtonElement) activeScanButton.disabled = false;
      });
    }, 700);
  }

  async function cancelScan(): Promise<void> {
    if (!currentScanJobId) return;
    panel.cancelling = true;
    panel.title = "Arret demande";
    await fetch(`/cleaner/scan/cancel/${currentScanJobId}`, { method: "POST" }).catch(() => {});
  }

  function showPanel(title: string): void {
    panel.visible = true;
    panel.title = title;
    panel.elapsedSeconds = 0;
    panel.active = true;
    panel.cancelling = false;
    panel.progressValue = null;
    panel.stats = [
      { label: "Mails scannes", value: 0 },
      { label: "Candidats", value: 0 },
      { label: "Factures", value: 0 },
      { label: "Hors regex", value: 0 },
      { label: "Trop recents", value: 0 },
    ];
  }

  function setScanProgress(payload: CleanerScanJobPayload): void {
    panel.elapsedSeconds = payload.elapsed_seconds || 0;
    panel.stats = [
      { label: "Mails scannes", value: payload.scanned_count || 0 },
      { label: "Candidats", value: payload.candidate_count || 0 },
      { label: "Factures", value: payload.skipped_safety || 0 },
      { label: "Hors regex", value: payload.skipped_no_match || 0 },
      { label: "Trop recents", value: payload.skipped_too_recent || 0 },
      ...(payload.current_mailbox ? [{ label: "Boite", value: payload.current_mailbox }] : []),
    ];
  }

  return { cancelScan, initScanForms, panel };
}
