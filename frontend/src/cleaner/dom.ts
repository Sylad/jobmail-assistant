export function text(element: Element | null, value: string): void {
  if (element) element.textContent = value;
}

export function query<T extends Element = Element>(selector: string, root: ParentNode = document): T | null {
  return root.querySelector<T>(selector);
}

export function queryAll<T extends Element = Element>(selector: string, root: ParentNode = document): T[] {
  return Array.from(root.querySelectorAll<T>(selector));
}

export function getSubmitter(event: SubmitEvent): HTMLElement | null {
  return event.submitter instanceof HTMLElement ? event.submitter : null;
}
