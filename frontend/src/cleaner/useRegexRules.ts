import { query } from "./dom";

export function useRegexRules() {
  function initRegexRules(): void {
    const ruleBody = query<HTMLTableSectionElement>("[data-regex-rules]");
    const addButton = query<HTMLButtonElement>("[data-add-regex-rule]");
    if (!ruleBody || !addButton) return;

    addButton.addEventListener("click", () => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td><input type="text" name="sender_regex_rule" placeholder="amazon|googleplay"></td>
        <td><input type="text" name="subject_regex_rule" placeholder="promo|soldes|recommande"></td>
      `;
      ruleBody.appendChild(row);
      query<HTMLInputElement>("input", row)?.focus();
    });
  }

  return { initRegexRules };
}
