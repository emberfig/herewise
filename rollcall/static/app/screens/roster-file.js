// What both roster imports share: Levels (screen 23) and the last step of first-run setup.
//
// Asked for on 2026-09-24, before Herewise went to a lecturer's laptop: "if a lecturer tries to
// import an excel file or csv and its invalid what should we do about that". A file that cannot say
// which column is which is asked about here rather than refused: its first rows are shown with a
// guess, and the same file goes back with the answer. An import that can go ahead but is probably
// the wrong list has a box to tick first. The backend refuses the commit until the same box is
// ticked, so the box is never the only thing standing in the way.

import { button, field, h, invalid, panel, saveFile, setReason, table } from "../ui.js";

// The portal's .xls, a department's .xlsx, a CSV, and the tab-separated text Excel also saves.
export const ACCEPT = ".csv,.txt,.xls,.xlsx,text/csv,text/plain,application/vnd.ms-excel,"
  + "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

// roster.MAX_UPLOAD_BYTES. Checked here as well, so a video picked by mistake is not sent anywhere.
const MAX_BYTES = 5 * 1024 * 1024;

/** Why a chosen file is too big to be a roster, or "" when it is not. */
export function tooBig(file) {
  if (!file || file.size <= MAX_BYTES) return "";
  return `${file.name} is ${(file.size / (1024 * 1024)).toFixed(1)} MB. A roster is a few kilobytes `
    + "(the department's longest list is 16 KB), so this is probably not the list. The most Herewise "
    + "reads is 5 MB.";
}

/** The file and whatever was chosen for it, as the preview takes them. */
export function previewForm(file, choice) {
  const form = new FormData();
  form.append("file", file);
  for (const [key, value] of Object.entries(choice || {})) {
    if (value !== null && value !== undefined && value !== "") form.append(key, String(value));
  }
  return form;
}

/** A blank roster named for the level, for a list typed in by hand. `levelOf()` is asked on the
 * press, because on first-run setup the level can change after the button is drawn. */
export function templateButton(levelOf) {
  const control = button({ label: "Download a blank template", variant: "quiet",
    busyLabel: "Saving the template",
    onClick: () => {
      const level = levelOf();
      if (level) saveFile(control, `/api/levels/${level.id}/roster/template`, `The ${level.name} template`);
    } });
  return control;
}

/** A refused file, kept on the page beside the file until another is chosen. */
export function refusal(text) {
  return panel({ tone: "failure", title: "This file cannot be imported", body: text, role: "alert" });
}

// -- which column is which -------------------------------------------------------------------------

function letter(index) {
  let name = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  return name;
}

/**
 * The question for a file whose columns could not be read (`{needs_columns: true}` from the
 * preview): the rows as they are, and a choice of column for each thing Herewise needs.
 * `onAnswer(choice, control)` sends the file back with it; a sheet on its own shows that sheet.
 */
export function columnQuestion(ask, onAnswer) {
  const guess = ask.guess || {};
  const columns = Array.from({ length: ask.columns }, (_, i) => i);
  // What a column holds, in the options, so "Column C" can be told from "Column D" without looking up.
  const example = (i) => {
    const below = ask.rows.find((r) => r.row >= (guess.first_row || 1) && r.cells[i]);
    const seen = below ? below.cells[i] : "";
    return seen ? `: ${seen.length > 24 ? `${seen.slice(0, 24)}…` : seen}` : "";
  };
  const pick = (label, key, none, help) => field({
    label, help, width: "medium",
    value: guess[key] === null || guess[key] === undefined ? "" : String(guess[key]),
    options: [
      ...(none ? [{ value: "", label: none }] : [{ value: "", label: "Choose a column" }]),
      ...columns.map((i) => ({ value: String(i), label: `Column ${letter(i)}${example(i)}` })),
    ],
    validate: none ? null : (v) => (v === "" ? `Choose the column that holds the ${label.toLowerCase()}.` : ""),
  });

  const matric = pick("Matric number", "matric_col", null,
    "A student with no matric number yet can have DE or nothing in it.");
  const name = pick("Name", "name_col", null,
    "The whole name, or the surname when the other names have a column of their own.");
  const other = pick("Other names", "other_col", "None",
    "Only when the surname has a column of its own.");
  const levelColumn = pick("Level", "level_col", "None",
    "Rows for another level are left out.");
  const firstRow = field({
    label: "The first student is on", width: "medium",
    help: "Rows above it, such as the headings, are not read.",
    value: String(guess.first_row || ask.rows[0]?.row || 1),
    options: ask.rows.map((r) => ({ value: String(r.row), label: `Row ${r.row}` })),
  });

  const sheet = ask.sheets && ask.sheets.length > 1
    ? field({ label: "Sheet", width: "medium", value: ask.sheet,
      options: ask.sheets.map((s) => ({ value: s, label: s })) })
    : null;
  const showSheet = sheet ? button({ label: "Show this sheet", busyLabel: "Reading the sheet",
    onClick: () => onAnswer({ sheet: sheet.value() }, showSheet) }) : null;

  const go = button({ label: "Preview with these columns", primary: true, busyLabel: "Reading the file",
    onClick: () => {
      const chosen = [matric, name, other].map((f) => f.value()).filter((v) => v !== "");
      if (invalid(matric, name)) return;
      if (new Set(chosen).size !== chosen.length) {
        other.showError("Each of these needs a different column.");
        other.control.focus();
        return;
      }
      onAnswer({
        sheet: sheet ? sheet.value() : ask.sheet,
        matric_col: matric.value(), name_col: name.value(), other_col: other.value(),
        level_col: levelColumn.value(), first_row: firstRow.value(),
      }, go);
    } });

  return h("div", { class: "hw-card hw-stack", dataset: { question: "" } },
    panel({ tone: "review", title: "Which column is which?", body: ask.reason }),
    sheet ? h("div", { class: "hw-row", style: { alignItems: "end" } }, sheet, showSheet) : null,
    table({
      caption: `The first rows of ${ask.sheet ? `the sheet ${ask.sheet}` : "the file"}`,
      density: "compact",
      rows: ask.rows,
      columns: [
        { label: "Row", align: "end", render: (r) => h("span", { class: "hw-tnum" }, String(r.row)) },
        ...columns.map((i) => ({ label: letter(i), render: (r) => r.cells[i] })),
      ],
    }),
    h("div", { class: "hw-row", style: { flexWrap: "wrap", alignItems: "start" } },
      matric, name, other, levelColumn, firstRow),
    h("div", { class: "hw-cardfoot" }, h("span", { class: "hw-cardfoot__end" }, go)));
}

// -- the wrong list ----------------------------------------------------------------------------------

const WARNING_TITLE = {
  moves: "This looks like another level's list",
  mostly_refused: "Most of this file is refused",
};

/**
 * The preview's warnings, each with its box. `onChange(ready, codes)` says whether every box is
 * ticked and which are. Null when there is nothing to tick.
 */
export function warningBoxes(plan, onChange) {
  const warnings = plan.warnings || [];
  if (!warnings.length) return null;
  const ticked = new Set();
  return h("div", { class: "hw-stack hw-stack--tight" }, ...warnings.map((warning) => {
    const box = h("input", { type: "checkbox" });
    box.addEventListener("change", () => {
      if (box.checked) ticked.add(warning.code);
      else ticked.delete(warning.code);
      onChange(ticked.size === warnings.length, [...ticked]);
    });
    return panel({ tone: "review", title: WARNING_TITLE[warning.code] || "Check this is the right list",
      body: warning.text,
      children: [h("label", { class: "hw-choice", style: { marginBlockStart: "var(--hw-space-3)" } },
        box, h("span", { class: "hw-choice__label" }, warning.confirm))] });
  }));
}

/** Hold an Import button until every box is ticked, with the reason written under it meanwhile. */
export const UNTICKED = "Tick the box above to go ahead.";

export function holdUntilTicked(control, ready) {
  const btn = control.matches?.("button") ? control : control.querySelector("button");
  if (btn) btn.disabled = !ready;
  setReason(control, ready ? "" : UNTICKED);
}
