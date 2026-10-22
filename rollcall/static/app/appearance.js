// System, Light or Dark, chosen on this computer (asked for on 2026-10-22).
//
// The choice is applied before the first paint by /api/appearance.js in the page's head, which sets
// data-theme on the root for Light or Dark and nothing for System, so the tokens' own
// prefers-color-scheme rule follows Windows as it always did (css/tokens.css). This module is the
// one control that changes it, used by the account menu, Settings and first-run setup, so the three
// can never offer different words or disagree about what is chosen.

import { ApiError, api } from "./api.js";
import { h, toast } from "./ui.js";

const OPTIONS = [
  ["system", "System", "Follows Windows: light or dark, whichever Windows is set to."],
  ["light", "Light", "Dark ink on warm paper, whatever Windows is set to."],
  ["dark", "Dark", "Light ink on a dark page, whatever Windows is set to."],
];

/** What is chosen now, as the head script left it or the last change set it. */
export function currentAppearance() {
  return document.documentElement.dataset.appearance || "system";
}

function apply(theme) {
  const root = document.documentElement;
  root.dataset.appearance = theme;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

/**
 * Three choices that take effect as soon as one is picked, and are saved for this computer. Not
 * part of any form's Save: how the screen looks is not a change to the register, and seeing it is
 * how somebody decides.
 */
export function appearanceChoice({ legend = "Appearance", name = "appearance", quiet = false } = {}) {
  const status = h("p", { class: "hw-visually-hidden", role: "status" });
  const rows = OPTIONS.map(([value, label, help]) => {
    const input = h("input", { type: "radio", name, value, checked: currentAppearance() === value || null,
      dataset: { action: `appearance-${value}` } });
    input.addEventListener("change", () => choose(value, label));
    return h("label", { class: "hw-choice" }, input,
      h("span", { class: "hw-stack hw-stack--tight", style: { gap: "2px" } },
        h("span", { class: "hw-choice__label" }, label),
        quiet ? null : h("span", { class: "hw-choice__help" }, help)));
  });

  async function choose(value, label) {
    const before = currentAppearance();
    apply(value);
    try {
      await api.put("/api/appearance", { theme: value });
      status.textContent = `${label} is chosen on this computer.`;
    } catch (error) {
      apply(before);
      for (const input of set.querySelectorAll("input")) input.checked = input.value === before;
      toast(error instanceof ApiError ? error.message : "That was not saved. The appearance is as it was.",
        "failure");
    }
  }

  const set = h("fieldset", { class: "hw-fieldset", dataset: { appearance: "" } },
    h("legend", {}, legend), h("div", { class: `hw-appearance${quiet ? " hw-appearance--quiet" : ""}` }, ...rows), status);
  return set;
}
