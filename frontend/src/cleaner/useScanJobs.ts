import { getSubmitter, query, queryAll, text } from "./dom";
import type { CleanerScanJobPayload } from "./types";

export function useScanJobs() {
  let currentScanJobId = "";
  let activeScanButton: HTMLElement | null = null;

  function initScanForms(): void {
    const forms = queryAll<HTMLFormElement>("[data-async-scan-form]");
    const progress = query<HTMLElement>("[data-scan-progress]");
    if (!forms.length || !progress) return;

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.className = "btn btn-sm btn-ghost";
    cancelButton.textContent = "Arreter";
    cancelButton.hidden = true;
    query(".scan-progress-head", progress)?.appendChild(cancelButton);

    cancelButton.addEventListener("click", async () => {
      if (!currentScanJobId) return;
      cancelButton.disabled = true;
      setProgressTitle(progress, "Arret demande");
      await fetch(`/cleaner/scan/cancel/${currentScanJobId}`, { method: "POST" }).catch(() => {});
    });

    forms.forEach((form) => {
      const startButton = query<HTMLButtonElement>("[data-start-regex-scan]", form);
      startButton?.addEventListener("click", (event) => startScan(event, form, startButton, progress, cancelButton));
      form.addEventListener("submit", async (event) => {
        const submitter = getSubmitter(event);
        if (submitter instanceof HTMLButtonElement && submitter.name === "export_csv") return;
        await startScan(event, form, submitter, progress, cancelButton);
      });
    });
  }

  async function startScan(
    event: Event,
    form: HTMLFormElement,
    submitButton: HTMLElement | null,
    progress: HTMLElement,
    cancelButton: HTMLButtonElement,
  ): Promise<void> {
    event.preventDefault();
    progress.hidden = false;
    progress.scrollIntoView({ block: "nearest", behavior: "smooth" });
    cancelButton.hidden = false;
    cancelButton.disabled = false;
    setProgressTitle(progress, "Scan en cours");
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
      setScanProgress(progress, payload);
      await pollScan(payload.id, progress, cancelButton);
    } catch (error) {
      setProgressTitle(progress, error instanceof Error ? error.message : "Scan en erreur");
      if (activeScanButton instanceof HTMLButtonElement) activeScanButton.disabled = false;
      cancelButton.hidden = true;
      cancelButton.disabled = false;
    }
  }

  async function pollScan(jobId: string, progress: HTMLElement, cancelButton: HTMLButtonElement): Promise<void> {
    const response = await fetch(`/cleaner/scan/status/${jobId}`);
    if (!response.ok) throw new Error("Impossible de lire le statut du scan.");
    const payload = await response.json() as CleanerScanJobPayload;
    setScanProgress(progress, payload);
    if (payload.status === "done") {
      setProgressTitle(progress, "Scan termine");
      window.location.href = payload.result_url;
      return;
    }
    if (payload.status === "cancelled") {
      setProgressTitle(progress, "Scan annule");
      if (activeScanButton instanceof HTMLButtonElement) activeScanButton.disabled = false;
      cancelButton.hidden = true;
      cancelButton.disabled = false;
      return;
    }
    if (payload.status === "error") {
      setProgressTitle(progress, payload.error || "Scan en erreur");
      if (activeScanButton instanceof HTMLButtonElement) activeScanButton.disabled = false;
      cancelButton.hidden = true;
      cancelButton.disabled = false;
      return;
    }
    window.setTimeout(() => {
      pollScan(jobId, progress, cancelButton).catch((error: unknown) => {
        setProgressTitle(progress, error instanceof Error ? error.message : "Scan en erreur");
        if (activeScanButton instanceof HTMLButtonElement) activeScanButton.disabled = false;
        cancelButton.hidden = true;
        cancelButton.disabled = false;
      });
    }, 700);
  }

  function setScanProgress(progress: HTMLElement, payload: CleanerScanJobPayload): void {
    text(query("[data-scan-progress-scanned]", progress), String(payload.scanned_count || 0));
    text(query("[data-scan-progress-candidates]", progress), String(payload.candidate_count || 0));
    text(query("[data-scan-progress-safety]", progress), String(payload.skipped_safety || 0));
    text(query("[data-scan-progress-no-match]", progress), String(payload.skipped_no_match || 0));
    text(query("[data-scan-progress-too-recent]", progress), String(payload.skipped_too_recent || 0));
    text(query("[data-scan-progress-mailbox]", progress), payload.current_mailbox ? `Boite ${payload.current_mailbox}` : "");
    text(query("[data-scan-progress-time]", progress), `${payload.elapsed_seconds || 0}s`);
  }

  function setProgressTitle(progress: HTMLElement, value: string): void {
    text(query("[data-scan-progress-title]", progress), value);
  }

  return { initScanForms };
}
