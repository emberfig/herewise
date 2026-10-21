// Screen 23: Roster import. Mockups: Importrosterchangedrows.png, Importrostercapacityexceeded.png,
// Importrosternothingnew.png, Importrosterrefusedpreview.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "23 Roster import".
//
// The WHY column is what this screen is for: a refused row says why in the backend's own words,
// including "Already on 300 Level with device ID 3042", which is the one that stops someone
// re-importing and creating a duplicate.
//
// Fixed from the mockup:
//   a completed step carries a tick and a done state, so the indicator reads backwards as well as
//     forwards;
//   the selected segment is filled --hw-accent, as it is on Courses and Percentages;
//   a capacity problem does not hide the other refusals: every refused row is shown.

import { ApiError, api } from "../api.js";
import { go, href } from "../router.js";
import {
  matricText,
  announce, button, dateAndTime, dialog, fill, h, page, plural, section, setBusy, table, toast,
} from "../ui.js";
import {
  ACCEPT, UNTICKED, columnQuestion, holdUntilTicked, previewForm, refusal, templateButton, tooBig,
  warningBoxes,
} from "./roster-file.js";

const STEPS = ["Choose a file", "Check the preview", "Import"];

export default {
  id: "roster-import",
  nav: "levels",
  title: "Roster import",
  permission: "roster.manage",

  async render(view, ctx) {
    const levelId = Number(ctx.params.id);
    const levels = await api.get("/api/levels");
    const level = levels.find((l) => l.id === levelId);
    const past = await api.get(`/api/levels/${levelId}/imports`).catch(() => ({ imports: [] }));
    const host = h("div");
    view.append(host);
    const reload = () => this.render(fill(view), ctx);
    draw(host, level, { step: 0, file: null, plan: null, busy: false,
      past: past.imports || [], reload });
  },
};

function draw(host, level, state) {
  const redraw = () => draw(host, level, state);

  // The portal hands out .xls, so the file a lecturer already has is the file this takes
  // (2026-09-21). Excel's own "Save as CSV" is no longer a step anybody has to know about.
  const input = h("input", { type: "file", class: "hw-visually-hidden", id: "roster-file", accept: ACCEPT });
  input.addEventListener("change", () => {
    state.file = input.files[0] || null;
    const error = tooBig(state.file);
    Object.assign(state, { plan: null, ask: null, choice: null, error, next: error ? "error" : "file" });
    state.step = state.file && !state.error ? 1 : 0;
    redraw();
  });

  // One way to the preview, for the first try and for every answer to "which column is which".
  // A refusal stays on the page beside the file until another is chosen: it used to be a toast,
  // gone in six seconds (2026-09-24).
  const send = async (choice, control) => {
    setBusy(control, true);
    try {
      const answer = await api.upload(`/api/levels/${level.id}/roster/preview`, previewForm(state.file, choice));
      state.error = "";
      if (answer.needs_columns) {
        Object.assign(state, { ask: answer, plan: null, next: "ask" });
        announce("Herewise needs to know which column is which.");
      } else {
        // An answered question stays on screen, so a wrong answer can be changed.
        if (!choice) state.ask = null;
        Object.assign(state, { plan: answer, next: "plan" });
        announce(`The preview is ready: ${plural(answer.new, "new student")}.`);
      }
      state.choice = choice || null;
      state.step = 1;
    } catch (error) {
      Object.assign(state, { plan: null, next: "error",
        error: error instanceof ApiError ? error.message : "That file could not be read." });
    } finally {
      setBusy(control, false);
      redraw();
    }
  };

  const preview = button({ label: "Preview the import", primary: true, busyLabel: "Reading the file",
    reason: !state.file ? "Choose a file first." : state.error ? "Choose a different file." : "",
    align: "end", onClick: () => send(null, preview) });

  fill(host, page({
    title: `Import a roster for ${level.name}`,
    subtitle: `Device IDs ${level.id_block_start} to ${level.id_block_end} · `
      + `${plural(level.students, "student")} on it now`,
    children: [
      stepper(state),
      section("The file", h("div", { class: "hw-card hw-stack" },
        h("div", { class: "hw-well", style: { display: "grid", justifyItems: "center", gap: "var(--hw-space-2)", padding: "var(--hw-space-8)" } },
          input,
          h("label", { class: "hw-link", for: "roster-file", style: { cursor: "pointer", fontSize: "var(--hw-text-lead)" } },
            state.file ? "Choose a different file" : "Choose the roster file"),
          h("p", { class: "hw-muted", style: { margin: 0 } },
            "A spreadsheet from the portal (.xls or .xlsx) or a CSV. Columns needed: matric number "
            + "and full name, or surname and other names. A level column is read if it is there."),
          state.file
            ? h("p", { class: "hw-muted", style: { margin: 0 } },
              `${state.file.name}, ${Math.max(1, Math.round(state.file.size / 1024))} KB chosen.`)
            : null),
        state.error ? refusal(state.error) : null,
        h("div", { class: "hw-cardfoot" },
          h("span", { class: "hw-row", style: { alignItems: "center" } },
            h("a", { class: "hw-link", href: href("levels") }, "Back to Levels"),
            h("span", { class: "hw-muted" }, "No list yet?"), templateButton(() => level)),
          h("span", { class: "hw-cardfoot__end" }, preview)))),
      state.ask ? section("The columns", columnQuestion(state.ask, send)) : null,
      state.plan ? result(state, level, redraw) : null,
      pastImports(state, level),
    ],
  }));
  // Focus goes to what the press produced rather than to the top of the page: the first thing to
  // answer, the first box to tick or the Import button, or the file to change.
  const target = {
    ask: () => host.querySelector("[data-question] select"),
    plan: () => host.querySelector("[data-preview] input[type=checkbox]")
      || host.querySelector("[data-preview] .hw-cardfoot button:not([disabled])"),
    error: () => host.querySelector("#roster-file"),
    file: () => host.querySelector("button[data-action='Preview the import']"),
  }[state.next];
  state.next = "";
  target?.()?.focus();
}

function stepper(state) {
  const list = h("ol", { class: "hw-stepper" });
  STEPS.forEach((label, index) => {
    const at = index < state.step ? "done" : index === state.step ? "current" : "todo";
    // A completed step is marked, so the indicator can be read backwards.
    const glyph = at === "done" ? "✓" : at === "current" ? "●" : "○";
    list.append(h("li", { class: "hw-stepper__step", dataset: { state: at },
      "aria-current": at === "current" ? "step" : null },
      h("span", { class: "hw-stepper__glyph", "aria-hidden": "true" }, glyph),
      h("span", {}, label),
      h("span", { class: "hw-visually-hidden" },
        at === "done" ? " (done)" : at === "current" ? " (this step)" : " (not started)")));
  });
  return h("div", { style: { marginBlockEnd: "var(--hw-space-6)" } }, list);
}

function result(state, level, redraw) {
  const plan = state.plan;
  const ticks = plan.can_commit && (plan.warnings || []).length > 0;
  state.confirmed = [];
  const failed = h("div");
  const blocked = plan.errors && plan.errors.length ? plan.errors : [];
  const counts = [["new", plan.new], ["to update", plan.updated], ["unchanged", plan.unchanged],
    ["refused", plan.skipped]].filter(([, n]) => n);

  const commit = button({ label: `Import ${plural(plan.new + plan.updated, "student")}`, primary: true,
    busyLabel: "Importing", disabled: !plan.can_commit,
    reason: plan.can_commit ? (ticks ? UNTICKED : "") : (blocked[0] || "Nothing in this file is new."),
    align: "end",
    onClick: async () => {
      setBusy(commit, true);
      fill(failed);
      try {
        const done = await api.post(`/api/roster-imports/${plan.import_id}/commit`,
          { confirm: state.confirmed });
        state.step = 2;
        toast(`${plural(done.added ?? plan.new, "student")} imported into ${level.name}.`);
        announce("The roster is imported.");
        go("levels");
      } catch (error) {
        setBusy(commit, false);
        fill(failed, refusal(error instanceof ApiError ? error.message : "The import did not finish."));
      }
    } });
  const boxes = ticks ? warningBoxes(plan, (ready, codes) => {
    state.confirmed = codes;
    holdUntilTicked(commit, ready);
  }) : null;

  const refused = (plan.issues || []).filter((row) => row.action === "skip");

  return h("div", { class: "hw-stack", dataset: { preview: "" } },
    section("What this file would do", h("div", { class: "hw-card hw-stack" },
      boxes,
      h("p", { style: { margin: 0 } },
        `${plural(plan.rows, "row")} read: ${counts.map(([l, n]) => `${n} ${l}`).join(", ")}.`),
      plan.id_range
        ? h("p", { class: "hw-panel", dataset: { tone: "quiet" }, style: { margin: 0 } },
          h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "i"),
          h("span", {},
            plan.id_range[0] === plan.id_range[1] ? "The new student takes device ID " : "New students take device IDs ",
            h("b", { class: "hw-ids" }, plan.id_range[0] === plan.id_range[1] ? String(plan.id_range[0])
              : `${plan.id_range[0]} to ${plan.id_range[1]}`),
            ". A device ID is permanent and never reused, so last year's scans can never become this "
            + "year's student."))
        : null,
      capacity(plan),
      plan.shortened && plan.shortened.length ? shortened(plan) : null,
      failed,
      h("div", { class: "hw-cardfoot" },
        h("span", { class: "hw-cardfoot__end" }, commit)))),
    // Every refusal is shown: a capacity problem is no reason to hide two of them.
    refused.length ? section(`Refused rows (${refused.length})`, table({
      caption: "Rows this import will not take",
      rows: refused,
      columns: [
        { label: "Line", align: "end", render: (r) => h("span", { class: "hw-tnum" }, String(r.line)) },
        { label: "Matric no.", render: (r) => h("span", { class: "hw-ids" }, matricText(r.matric_no)) },
        { label: "Why", render: (r) => (r.issues || []).join("; ") },
      ],
    })) : null);
}

function capacity(plan) {
  const c = plan.capacity;
  if (!c) return null;
  const over = c.after_import > c.capacity;
  return h("div", { class: "hw-panel", dataset: { tone: over ? "failure" : "quiet" },
    role: over ? "alert" : null, style: { margin: 0 } },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, over ? "✕" : "i"),
    h("div", {},
      h("p", { class: "hw-panel__title" },
        over ? `${c.device} does not have room for this import` : `Room on ${c.device}`),
      h("p", { class: "hw-panel__body" },
        `It holds ${c.assigned_now.toLocaleString("en-GB")} of `
        + `${c.capacity.toLocaleString("en-GB")}. After this import it would hold `
        + `${c.after_import.toLocaleString("en-GB")}`
        + (over ? `, which is ${(c.after_import - c.capacity).toLocaleString("en-GB")} too many.`
          : "."))));
}

function shortened(plan) {
  return h("details", { class: "hw-well" },
    h("summary", {}, `${plural(plan.shortened.length, "name")} shortened for the device`),
    h("p", { class: "hw-muted" },
      "The terminal stores 24 bytes for a name. The full name is kept here and only the device's "
      + "copy is shortened."),
    table({
      caption: "Names shortened for the device",
      density: "compact",
      rows: plan.shortened,
      columns: [
        { label: "Line", align: "end", render: (r) => h("span", { class: "hw-tnum" }, String(r.line)) },
        { label: "In the file", render: (r) => r.before },
        { label: "On the device", render: (r) => r.after },
      ],
    }));
}


// -- imports already made ------------------------------------------------------------------------
//
// Asked for on a first run: a roster went into the wrong level and there was no way back short of
// editing the database (2026-09-21). An import is only taken back while the students it created are
// untouched, because a device ID that has been scanned against is never handed to anybody else.

function pastImports(state, level) {
  if (!state.past.length) return null;
  return section(`Imports already made for ${level.name}`,
    table({
      caption: "Imports already made",
      rows: state.past,
      columns: [
        { label: "When", render: (r) => dateAndTime(r.committed_at || r.created_at) },
        { label: "File", render: (r) => r.file_name || h("span", { class: "hw-muted" }, "no file name") },
        { label: "By", render: (r) => r.by_whom || h("span", { class: "hw-muted" }, "\u2013") },
        { label: "Students created", align: "end", render: (r) =>
          h("span", { class: "hw-tnum" }, String(r.people_created)) },
        { label: "", align: "end", render: (r) => undoButton(r, state) },
      ],
    }),
    h("p", { class: "hw-section__help" },
      "Taking an import back out removes only the students it created, and only while none of them "
      + "has scanned, been corrected, been excused, been enrolled or been sent to the terminal. "
      + "Students an import only updated stay where they are."));
}

function undoButton(record, state) {
  if (!record.people_created) {
    return button({ label: "Take it back", disabled: true,
      reason: record.before_tracking
        ? "Made before Herewise recorded which students an import created, so they cannot be told "
          + "apart. Remove them from their own records."
        : "This import created nobody: it only updated students already here." });
  }
  if (!record.can_undo) {
    const what = Object.entries(record.holding || {})
      .map(([name, count]) => `${count} ${name}`).join(", ");
    return button({ label: "Take it back", disabled: true,
      reason: `Its students have ${what}, which is never deleted.` });
  }
  return button({ label: "Take it back", variant: "destructive", permission: "roster.manage",
    onClick: () => undoDialog(record, state) });
}

function undoDialog(record, state) {
  const confirm = button({ label: "Take them back out", variant: "destructive",
    busyLabel: "Taking them out" });
  const box = dialog({
    title: `Take back ${record.file_name || "this import"}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        `${plural(record.people_created, "student")} created by this import will be removed. `
        + "Nothing else changes, and students it only updated stay where they are."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "Their device IDs go back into the level's block and can be given out again, because "
        + "nobody has scanned against them.")),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, confirm)],
  });
  confirm.addEventListener("click", async () => {
    setBusy(confirm, true);
    try {
      const done = await api.post(`/api/roster-imports/${record.id}/undo`, {});
      box.close();
      toast(`${plural(done.removed, "student")} taken back out.`);
      announce("The import is taken back out.");
      await state.reload();
    } catch (error) {
      setBusy(confirm, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}
