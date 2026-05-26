import { query, queryAll, text } from "./dom";

const countChecked = (checkboxes: HTMLInputElement[]) => checkboxes.filter((box) => box.checked).length;

export function useCandidateSelection() {
  function initCandidateSelection(): void {
    const checkboxes = queryAll<HTMLInputElement>("[data-candidate-checkbox]");
    if (!checkboxes.length) return;

    const selectedCount = query("[data-selected-count]");
    const senderRows = queryAll<HTMLElement>("[data-sender-row]");

    const updateSenderRows = () => {
      senderRows.forEach((senderRow) => {
        const sender = senderRow.dataset.senderRow ?? "";
        const senderBoxes = checkboxes.filter((box) => box.closest<HTMLElement>("[data-sender]")?.dataset.sender === sender);
        const checkedCount = countChecked(senderBoxes);
        const state = query("[data-sender-state]", senderRow);
        senderRow.classList.remove("sender-excluded", "sender-partial", "sender-included");
        if (checkedCount === 0) {
          senderRow.classList.add("sender-excluded");
          text(state, "Exclu");
        } else if (checkedCount === senderBoxes.length) {
          senderRow.classList.add("sender-included");
          text(state, "Inclus");
        } else {
          senderRow.classList.add("sender-partial");
          text(state, "Partiel");
        }
      });
    };

    const updateCount = () => {
      text(selectedCount, String(countChecked(checkboxes)));
      updateSenderRows();
    };

    const setAll = (checked: boolean) => {
      checkboxes.forEach((box) => {
        box.checked = checked;
      });
      updateCount();
    };

    const setSender = (sender: string | undefined, checked: boolean) => {
      if (!sender) return;
      checkboxes.forEach((box) => {
        const row = box.closest<HTMLElement>("[data-sender]");
        if (row?.dataset.sender === sender) box.checked = checked;
      });
      updateCount();
    };

    query("[data-select-all-candidates]")?.addEventListener("click", () => setAll(true));
    query("[data-clear-all-candidates]")?.addEventListener("click", () => setAll(false));
    queryAll<HTMLElement>("[data-include-sender]").forEach((button) => {
      button.addEventListener("click", () => setSender(button.dataset.includeSender, true));
    });
    queryAll<HTMLElement>("[data-exclude-sender]").forEach((button) => {
      button.addEventListener("click", () => setSender(button.dataset.excludeSender, false));
    });
    checkboxes.forEach((box) => box.addEventListener("change", updateCount));
    updateCount();
  }

  return { initCandidateSelection };
}
