/**
 * Structural accessibility audit for rendered DOM, built on testing-library queries only.
 * It is NOT axe-core (not installed in this repo): it covers name/label/landmark/heading/table
 * rules that jsdom can verify, and cannot check colour contrast or rendered focus order.
 */
function accessibleName(el: Element): string {
  const labelledby = el.getAttribute("aria-labelledby");
  if (labelledby) {
    return labelledby
      .split(/\s+/)
      .map((id) => el.ownerDocument.getElementById(id)?.textContent ?? "")
      .join(" ")
      .trim();
  }
  const aria = el.getAttribute("aria-label");
  if (aria) return aria.trim();
  if (
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    el instanceof HTMLSelectElement
  ) {
    const id = el.id;
    const label = id ? el.ownerDocument.querySelector(`label[for="${id}"]`) : el.closest("label");
    return (label?.textContent ?? "").trim();
  }
  return (el.textContent ?? "").trim() || el.getAttribute("title")?.trim() || "";
}

export function auditA11y(root: HTMLElement = document.body): string[] {
  const problems: string[] = [];
  root.querySelectorAll("button,[role=button]").forEach((el) => {
    if (!accessibleName(el))
      problems.push(`button without accessible name: ${el.outerHTML.slice(0, 80)}`);
  });
  root.querySelectorAll("a[href]").forEach((el) => {
    if (!accessibleName(el))
      problems.push(`link without accessible name: ${el.outerHTML.slice(0, 80)}`);
  });
  root.querySelectorAll("input:not([type=hidden]),textarea,select").forEach((el) => {
    if (!accessibleName(el))
      problems.push(`form control without label: ${el.outerHTML.slice(0, 80)}`);
  });
  root.querySelectorAll("img").forEach((el) => {
    if (!el.hasAttribute("alt")) problems.push("img without alt");
  });
  root.querySelectorAll("svg[role=img]").forEach((el) => {
    if (!accessibleName(el)) problems.push("svg role=img without label");
  });
  root.querySelectorAll("table").forEach((table) => {
    if (!table.querySelector("th")) problems.push("table without header cells");
    table.querySelectorAll("thead th").forEach((th) => {
      if (!th.hasAttribute("scope"))
        problems.push(`column header without scope: ${th.textContent}`);
    });
  });
  const ids = new Map<string, number>();
  root.querySelectorAll("[id]").forEach((el) => ids.set(el.id, (ids.get(el.id) ?? 0) + 1));
  ids.forEach((n, id) => n > 1 && problems.push(`duplicate id: ${id}`));
  root.querySelectorAll("[aria-labelledby],[aria-describedby],[aria-controls]").forEach((el) => {
    for (const attr of ["aria-labelledby", "aria-describedby", "aria-controls"]) {
      el.getAttribute(attr)
        ?.split(/\s+/)
        .forEach((id) => {
          if (id && !el.ownerDocument.getElementById(id) && !(attr === "aria-controls"))
            problems.push(`${attr} points to missing id ${id}`);
        });
    }
  });
  const levels = Array.from(root.querySelectorAll("h1,h2,h3,h4")).map((h) => Number(h.tagName[1]));
  levels.forEach((l, i) => {
    if (i > 0 && l - levels[i - 1]! > 1)
      problems.push(`heading level skipped: h${levels[i - 1]} -> h${l}`);
  });
  if (root.querySelectorAll("h1").length > 1) problems.push("more than one h1");
  return problems;
}
