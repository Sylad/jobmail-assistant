import { reactive } from "vue";
import { query } from "./dom";
import type { CleanerMoveJobPayload, ProgressPanelState } from "./types";

export function useMoveJobs() {
  let currentMoveJobId = "";
  const panel = reactive<ProgressPanelState>({
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

  function initMoveForm(): void {
    const form = query<HTMLFormElement>("[data-regex-move-form]");
    if (!form) return;

    const submitButton = query<HTMLButtonElement>("button[type='submit']", form);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      showPanel("Deplacement en cours");
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
        setMoveProgress(payload);
        await pollMove(payload.id, submitButton);
      } catch (error) {
        panel.title = error instanceof Error ? error.message : "Deplacement en erreur";
        panel.active = false;
        if (submitButton) submitButton.disabled = false;
      }
    });
  }

  async function pollMove(
    jobId: string,
    submitButton: HTMLButtonElement | null,
  ): Promise<void> {
    const response = await fetch(`/cleaner/move/status/${jobId}`);
    if (!response.ok) throw new Error("Impossible de lire le statut du deplacement.");
    const payload = await response.json() as CleanerMoveJobPayload;
    setMoveProgress(payload);
    if (payload.status === "done") {
      panel.title = "Deplacement termine";
      panel.active = false;
      window.location.href = payload.result_url;
      return;
    }
    if (payload.status === "cancelled") {
      panel.title = "Deplacement annule";
      panel.active = false;
      panel.cancelling = false;
      if (submitButton) submitButton.disabled = false;
      return;
    }
    if (payload.status === "error") {
      panel.title = payload.error || "Deplacement en erreur";
      panel.active = false;
      panel.cancelling = false;
      if (submitButton) submitButton.disabled = false;
      return;
    }
    window.setTimeout(() => {
      pollMove(jobId, submitButton).catch((error: unknown) => {
        panel.title = error instanceof Error ? error.message : "Deplacement en erreur";
        panel.active = false;
        panel.cancelling = false;
        if (submitButton) submitButton.disabled = false;
      });
    }, 700);
  }

  async function cancelMove(): Promise<void> {
    if (!currentMoveJobId) return;
    panel.cancelling = true;
    panel.title = "Arret demande";
    await fetch(`/cleaner/move/cancel/${currentMoveJobId}`, { method: "POST" }).catch(() => {});
  }

  function showPanel(title: string): void {
    panel.visible = true;
    panel.title = title;
    panel.elapsedSeconds = 0;
    panel.active = true;
    panel.cancelling = false;
    panel.progressValue = null;
    panel.stats = [
      { label: "Messages prevus", value: 0 },
      { label: "Messages deplaces", value: 0 },
    ];
  }

  function setMoveProgress(payload: CleanerMoveJobPayload): void {
    panel.elapsedSeconds = payload.elapsed_seconds || 0;
    const total = payload.total_count || 0;
    const moved = payload.moved_count || 0;
    panel.progressValue = total > 0 ? Math.round((moved / total) * 100) : null;
    panel.stats = [
      { label: "Messages prevus", value: total },
      { label: "Messages deplaces", value: moved },
    ];
  }

  return { cancelMove, initMoveForm, panel };
}
