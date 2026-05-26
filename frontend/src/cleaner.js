import { createApp } from "vue";

const countChecked = (checkboxes) => checkboxes.filter((box) => box.checked).length;

createApp({
  delimiters: ["[[", "]]"],
  render() {
    return null;
  },
  data() {
    return {
      currentScanJobId: "",
      activeScanButton: null,
      currentMoveJobId: "",
    };
  },
  mounted() {
    this.initCandidateSelection();
    this.initRegexRules();
    this.initScanForms();
    this.initMoveForm();
  },
  methods: {
    initCandidateSelection() {
      const checkboxes = Array.from(document.querySelectorAll("[data-candidate-checkbox]"));
      if (!checkboxes.length) return;

      const selectedCount = document.querySelector("[data-selected-count]");
      const senderRows = Array.from(document.querySelectorAll("[data-sender-row]"));
      const updateSenderRows = () => {
        senderRows.forEach((senderRow) => {
          const sender = senderRow.dataset.senderRow;
          const senderBoxes = checkboxes.filter((box) => box.closest("[data-sender]")?.dataset.sender === sender);
          const checkedCount = countChecked(senderBoxes);
          const state = senderRow.querySelector("[data-sender-state]");
          senderRow.classList.remove("sender-excluded", "sender-partial", "sender-included");
          if (checkedCount === 0) {
            senderRow.classList.add("sender-excluded");
            if (state) state.textContent = "Exclu";
          } else if (checkedCount === senderBoxes.length) {
            senderRow.classList.add("sender-included");
            if (state) state.textContent = "Inclus";
          } else {
            senderRow.classList.add("sender-partial");
            if (state) state.textContent = "Partiel";
          }
        });
      };
      const updateCount = () => {
        if (selectedCount) selectedCount.textContent = String(countChecked(checkboxes));
        updateSenderRows();
      };
      const setAll = (checked) => {
        checkboxes.forEach((box) => { box.checked = checked; });
        updateCount();
      };
      const setSender = (sender, checked) => {
        checkboxes.forEach((box) => {
          const row = box.closest("[data-sender]");
          if (row && row.dataset.sender === sender) box.checked = checked;
        });
        updateCount();
      };

      document.querySelector("[data-select-all-candidates]")?.addEventListener("click", () => setAll(true));
      document.querySelector("[data-clear-all-candidates]")?.addEventListener("click", () => setAll(false));
      document.querySelectorAll("[data-include-sender]").forEach((button) => {
        button.addEventListener("click", () => setSender(button.dataset.includeSender, true));
      });
      document.querySelectorAll("[data-exclude-sender]").forEach((button) => {
        button.addEventListener("click", () => setSender(button.dataset.excludeSender, false));
      });
      checkboxes.forEach((box) => box.addEventListener("change", updateCount));
      updateCount();
    },

    initRegexRules() {
      const ruleBody = document.querySelector("[data-regex-rules]");
      const addButton = document.querySelector("[data-add-regex-rule]");
      if (!ruleBody || !addButton) return;

      addButton.addEventListener("click", () => {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td><input type="text" name="sender_regex_rule" placeholder="amazon|googleplay"></td>
          <td><input type="text" name="subject_regex_rule" placeholder="promo|soldes|recommande"></td>
        `;
        ruleBody.appendChild(row);
        row.querySelector("input")?.focus();
      });
    },

    initScanForms() {
      const forms = Array.from(document.querySelectorAll("[data-async-scan-form]"));
      const progress = document.querySelector("[data-scan-progress]");
      if (!forms.length || !progress) return;

      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "btn btn-sm btn-ghost";
      cancelButton.textContent = "Arreter";
      cancelButton.hidden = true;
      progress.querySelector(".scan-progress-head")?.appendChild(cancelButton);

      cancelButton.addEventListener("click", async () => {
        if (!this.currentScanJobId) return;
        cancelButton.disabled = true;
        this.setProgressTitle(progress, "Arret demande");
        await fetch(`/cleaner/scan/cancel/${this.currentScanJobId}`, { method: "POST" }).catch(() => {});
      });

      forms.forEach((form) => {
        const startButton = form.querySelector("[data-start-regex-scan]");
        startButton?.addEventListener("click", (event) => this.startScan(event, form, startButton, progress, cancelButton));
        form.addEventListener("submit", async (event) => {
          const submitter = event.submitter;
          if (submitter && submitter.name === "export_csv") return;
          await this.startScan(event, form, submitter, progress, cancelButton);
        });
      });
    },

    async startScan(event, form, submitButton, progress, cancelButton) {
      event.preventDefault();
      progress.hidden = false;
      progress.scrollIntoView({ block: "nearest", behavior: "smooth" });
      cancelButton.hidden = false;
      cancelButton.disabled = false;
      this.setProgressTitle(progress, "Scan en cours");
      this.activeScanButton = submitButton
        || form.querySelector("[data-start-regex-scan]")
        || form.querySelector("button[type='submit']:not([name='export_csv'])");
      if (this.activeScanButton) this.activeScanButton.disabled = true;
      try {
        const response = await fetch("/cleaner/scan/start", {
          method: "POST",
          body: new FormData(form),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload.detail || "Impossible de lancer le scan.");
        }
        const payload = await response.json();
        this.currentScanJobId = payload.id;
        this.setScanProgress(progress, payload);
        await this.pollScan(payload.id, progress, cancelButton);
      } catch (error) {
        this.setProgressTitle(progress, error.message || "Scan en erreur");
        if (this.activeScanButton) this.activeScanButton.disabled = false;
        cancelButton.hidden = true;
        cancelButton.disabled = false;
      }
    },

    async pollScan(jobId, progress, cancelButton) {
      const response = await fetch(`/cleaner/scan/status/${jobId}`);
      if (!response.ok) throw new Error("Impossible de lire le statut du scan.");
      const payload = await response.json();
      this.setScanProgress(progress, payload);
      if (payload.status === "done") {
        this.setProgressTitle(progress, "Scan termine");
        window.location.href = payload.result_url;
        return;
      }
      if (payload.status === "cancelled") {
        this.setProgressTitle(progress, "Scan annule");
        if (this.activeScanButton) this.activeScanButton.disabled = false;
        cancelButton.hidden = true;
        cancelButton.disabled = false;
        return;
      }
      if (payload.status === "error") {
        this.setProgressTitle(progress, payload.error || "Scan en erreur");
        if (this.activeScanButton) this.activeScanButton.disabled = false;
        cancelButton.hidden = true;
        cancelButton.disabled = false;
        return;
      }
      window.setTimeout(() => this.pollScan(jobId, progress, cancelButton).catch((error) => {
        this.setProgressTitle(progress, error.message);
        if (this.activeScanButton) this.activeScanButton.disabled = false;
        cancelButton.hidden = true;
        cancelButton.disabled = false;
      }), 700);
    },

    setScanProgress(progress, payload) {
      progress.querySelector("[data-scan-progress-scanned]").textContent = String(payload.scanned_count || 0);
      progress.querySelector("[data-scan-progress-candidates]").textContent = String(payload.candidate_count || 0);
      progress.querySelector("[data-scan-progress-safety]").textContent = String(payload.skipped_safety || 0);
      progress.querySelector("[data-scan-progress-no-match]").textContent = String(payload.skipped_no_match || 0);
      progress.querySelector("[data-scan-progress-too-recent]").textContent = String(payload.skipped_too_recent || 0);
      progress.querySelector("[data-scan-progress-mailbox]").textContent = payload.current_mailbox ? `Boite ${payload.current_mailbox}` : "";
      progress.querySelector("[data-scan-progress-time]").textContent = `${payload.elapsed_seconds || 0}s`;
    },

    setProgressTitle(progress, text) {
      const title = progress.querySelector("[data-scan-progress-title], [data-move-progress-title]");
      if (title) title.textContent = text;
    },

    initMoveForm() {
      const form = document.querySelector("[data-regex-move-form]");
      const progress = document.querySelector("[data-move-progress]");
      if (!form || !progress) return;

      const submitButton = form.querySelector("button[type='submit']");
      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "btn btn-sm btn-ghost";
      cancelButton.textContent = "Arreter";
      cancelButton.hidden = true;
      progress.querySelector(".scan-progress-head")?.appendChild(cancelButton);

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        progress.hidden = false;
        cancelButton.hidden = false;
        this.setProgressTitle(progress, "Deplacement en cours");
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
          const payload = await response.json();
          this.currentMoveJobId = payload.id;
          this.setMoveProgress(progress, payload);
          await this.pollMove(payload.id, progress, cancelButton, submitButton);
        } catch (error) {
          this.setProgressTitle(progress, error.message || "Deplacement en erreur");
          if (submitButton) submitButton.disabled = false;
          cancelButton.hidden = true;
        }
      });

      cancelButton.addEventListener("click", async () => {
        if (!this.currentMoveJobId) return;
        cancelButton.disabled = true;
        this.setProgressTitle(progress, "Arret demande");
        await fetch(`/cleaner/move/cancel/${this.currentMoveJobId}`, { method: "POST" }).catch(() => {});
      });
    },

    async pollMove(jobId, progress, cancelButton, submitButton) {
      const response = await fetch(`/cleaner/move/status/${jobId}`);
      if (!response.ok) throw new Error("Impossible de lire le statut du deplacement.");
      const payload = await response.json();
      this.setMoveProgress(progress, payload);
      if (payload.status === "done") {
        this.setProgressTitle(progress, "Deplacement termine");
        window.location.href = payload.result_url;
        return;
      }
      if (payload.status === "cancelled") {
        this.setProgressTitle(progress, "Deplacement annule");
        if (submitButton) submitButton.disabled = false;
        cancelButton.hidden = true;
        return;
      }
      if (payload.status === "error") {
        this.setProgressTitle(progress, payload.error || "Deplacement en erreur");
        if (submitButton) submitButton.disabled = false;
        return;
      }
      window.setTimeout(() => this.pollMove(jobId, progress, cancelButton, submitButton).catch((error) => {
        this.setProgressTitle(progress, error.message);
        if (submitButton) submitButton.disabled = false;
      }), 700);
    },

    setMoveProgress(progress, payload) {
      progress.querySelector("[data-move-progress-moved]").textContent = String(payload.moved_count || 0);
      progress.querySelector("[data-move-progress-total]").textContent = String(payload.total_count || 0);
      progress.querySelector("[data-move-progress-time]").textContent = `${payload.elapsed_seconds || 0}s`;
    },
  },
}).mount("#cleaner-vue-root");
