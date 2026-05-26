import { query, text } from "./dom";
import type { CleanerMoveJobPayload } from "./types";

export function useMoveJobs() {
  let currentMoveJobId = "";

  function initMoveForm(): void {
    const form = query<HTMLFormElement>("[data-regex-move-form]");
    const progress = query<HTMLElement>("[data-move-progress]");
    if (!form || !progress) return;

    const submitButton = query<HTMLButtonElement>("button[type='submit']", form);
    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.className = "btn btn-sm btn-ghost";
    cancelButton.textContent = "Arreter";
    cancelButton.hidden = true;
    query(".scan-progress-head", progress)?.appendChild(cancelButton);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      progress.hidden = false;
      cancelButton.hidden = false;
      setProgressTitle(progress, "Deplacement en cours");
      if (submitButton) submitButton.disabled = true;
      try {
        const response = await fetch("/cleaner/move-thunderbird-to-trash/start", {
          method: "POST",
          body: new FormData(form),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload.detail || "Impossible de lancer le deplacement.");
        }
        const payload = await response.json() as CleanerMoveJobPayload;
        currentMoveJobId = payload.id;
        setMoveProgress(progress, payload);
        await pollMove(payload.id, progress, cancelButton, submitButton);
      } catch (error) {
        setProgressTitle(progress, error instanceof Error ? error.message : "Deplacement en erreur");
        if (submitButton) submitButton.disabled = false;
        cancelButton.hidden = true;
      }
    });

    cancelButton.addEventListener("click", async () => {
      if (!currentMoveJobId) return;
      cancelButton.disabled = true;
      setProgressTitle(progress, "Arret demande");
      await fetch(`/cleaner/move/cancel/${currentMoveJobId}`, { method: "POST" }).catch(() => {});
    });
  }

  async function pollMove(
    jobId: string,
    progress: HTMLElement,
    cancelButton: HTMLButtonElement,
    submitButton: HTMLButtonElement | null,
  ): Promise<void> {
    const response = await fetch(`/cleaner/move/status/${jobId}`);
    if (!response.ok) throw new Error("Impossible de lire le statut du deplacement.");
    const payload = await response.json() as CleanerMoveJobPayload;
    setMoveProgress(progress, payload);
    if (payload.status === "done") {
      setProgressTitle(progress, "Deplacement termine");
      window.location.href = payload.result_url;
      return;
    }
    if (payload.status === "cancelled") {
      setProgressTitle(progress, "Deplacement annule");
      if (submitButton) submitButton.disabled = false;
      cancelButton.hidden = true;
      return;
    }
    if (payload.status === "error") {
      setProgressTitle(progress, payload.error || "Deplacement en erreur");
      if (submitButton) submitButton.disabled = false;
      return;
    }
    window.setTimeout(() => {
      pollMove(jobId, progress, cancelButton, submitButton).catch((error: unknown) => {
        setProgressTitle(progress, error instanceof Error ? error.message : "Deplacement en erreur");
        if (submitButton) submitButton.disabled = false;
      });
    }, 700);
  }

  function setMoveProgress(progress: HTMLElement, payload: CleanerMoveJobPayload): void {
    text(query("[data-move-progress-moved]", progress), String(payload.moved_count || 0));
    text(query("[data-move-progress-total]", progress), String(payload.total_count || 0));
    text(query("[data-move-progress-time]", progress), `${payload.elapsed_seconds || 0}s`);
  }

  function setProgressTitle(progress: HTMLElement, value: string): void {
    text(query("[data-move-progress-title]", progress), value);
  }

  return { initMoveForm };
}
