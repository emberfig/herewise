// Screen 12: Attendance sheet, the Sheet tab of a course. Mockup: AttendancesheetPCT201.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "12 Attendance sheet". Spec: design/components/living-sheet.md.
//
// The sheet itself is <hw-sheet>, hero signature 1 of 3, already built and measured. This screen is
// the frame around it: the course header and tabs, Export PDF, Sheet setup, the density toggle, and
// the correction drawer the sheet opens through its hw-sheet-open event.

import { ApiError, api, download } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import { openDrawer } from "../../components/hw-drawer.js";
import {
  announce, button, dialog, field, fill, h, plural, saveFile, setBusy, toast,
} from "../ui.js";
import { frame } from "./course.js";
import { removeDialog } from "./course-students.js";
import "../../components/hw-sheet.js";

const DENSITY_KEY = "hw-sheet-density";

export default {
  id: "course-sheet",
  nav: "courses",
  title: "Attendance sheet",
  permission: "register.read",

  async render(view, { params, query }) {
    const courseId = Number(params.id);
    // Which group's sheet, on a course split into groups: a group's id, "none" for the students in
    // no group, or nothing for the backend's choice, the first group. Kept in the address, so going
    // back to the sheet from a register lands on the same group's.
    let group = query?.get("group") || "";
    const withGroup = (path, value = group) => (value ? `${path}${path.includes("?") ? "&" : "?"}group=${encodeURIComponent(value)}` : path);
    const sheetUrl = () => withGroup(`/api/templates/${templateId}/sheet`);
    const whose = () => (sheet.data?.group ? `${sheet.data.group.name}'s attendance sheet`
      : sheet.data?.groups ? "The sheet of the students in no group" : "The attendance sheet");
    // Not primary: the one primary action on a course is Start taking attendance, in its header.
    // Two blue buttons on one screen competed, and the export is the less frequent of the two.
    const exportButton = button({ label: "Export PDF", glyph: "↓",
      busyLabel: "Drawing the PDF",
      onClick: () => saveFile(exportButton, withGroup(`/api/templates/${templateId}/export?format=pdf`), whose()) });
    // The sheet has always exported as a spreadsheet as well, and only the PDF was on the screen, so
    // a lecturer who wanted to work on the figures had to be told the address (Checklist Design,
    // Data table: export). The eligibility list already offers both.
    const exportExcel = button({ label: "Export Excel", glyph: "↓",
      busyLabel: "Writing the spreadsheet",
      onClick: () => saveFile(exportExcel, withGroup(`/api/templates/${templateId}/export?format=xlsx`), whose()) });
    // A refused action's reason joins the tab row's one line beneath the rule, rather than growing
    // the toolbar (docs/DESIGN-DEVIATIONS.md, screen 11).
    const allowed = session.can("plan.manage");
    const setup = allowed
      ? h("a", { class: "hw-button hw-button--quiet", href: href(`courses/${courseId}/setup`),
        dataset: { action: "sheet-setup" } }, "Sheet setup")
      : h("span", { class: "hw-button hw-button--quiet", "aria-disabled": "true" }, "Sheet setup");

    const { course, body } = await frame(view, courseId, "sheet", {
      reasons: allowed ? [] : [`Sheet setup: ${session.denial("plan.manage")}`],
    });
    const templateId = course.template_id;

    const sheet = document.createElement("hw-sheet");
    sheet.setAttribute("setup-href", href(`courses/${courseId}/setup`));
    sheet.setAttribute("add-students-href", href(`courses/${courseId}/students`));
    sheet.setAttribute("groups-href", href(`courses/${courseId}/groups`));
    let compact = false;
    try { compact = localStorage.getItem(DENSITY_KEY) === "compact"; } catch { /* private window */ }
    if (compact) sheet.setAttribute("density", "compact");

    // Row height as a two-way toggle in the sheet's own toolbar, with the exports, rather than a
    // lone "Compact rows" link on a line of its own above the sheet (reported 2026-09-23).
    const density = h("div", { class: "hw-toggle", role: "group", "aria-label": "Row height" });
    const setDensity = (next) => {
      sheet.toggleAttribute("density", next);
      if (next) sheet.setAttribute("density", "compact");
      try { localStorage.setItem(DENSITY_KEY, next ? "compact" : "comfortable"); } catch { /* private window */ }
      for (const b of density.children) b.setAttribute("aria-pressed", String((b.dataset.value === "compact") === next));
    };
    for (const [value, label] of [["comfortable", "Comfortable"], ["compact", "Compact"]]) {
      const b = h("button", { class: "hw-toggle__button", type: "button", dataset: { value, action: `density-${value}` },
        "aria-pressed": String((value === "compact") === compact) }, label);
      b.addEventListener("click", () => setDensity(value === "compact"));
      density.append(b);
    }
    sheet.tools = [density, setup, exportExcel, exportButton];

    // A course with groups: which group's sheet, above the sheet because it decides what the sheet
    // is. Drawn from the sheet's own answer (grid.groups and grid.group) once it has loaded, so the
    // list can never offer a group the sheet does not have.
    const switcher = h("div", { class: "hw-row", hidden: true,
      style: { alignItems: "flex-end", marginBlockEnd: "var(--hw-space-4)" } });
    let select = null;
    const syncSwitcher = () => {
      const d = sheet.data;
      if (!d || !d.groups) { switcher.hidden = true; return; }
      const value = d.group ? String(d.group.id) : "none";
      group = value;
      if (!select) {
        const options = [...d.groups.map((g) => ({ value: String(g.id), label: `${g.name} · ${plural(g.students, "student")}` })),
          ...(d.ungrouped || !d.group ? [{ value: "none", label: `In no group · ${plural(d.ungrouped, "student")}` }] : [])];
        const pick = field({ label: "Sheet for", name: "group", width: "medium", value, options });
        select = pick.querySelector("select");
        select.addEventListener("change", async () => {
          group = select.value;
          // The address follows without drawing the screen again, so the switch keeps focus.
          history.replaceState(null, "", href(`courses/${courseId}/sheet?group=${encodeURIComponent(group)}`));
          await sheet.load(sheetUrl());
          syncSwitcher();
          announce(`${select.selectedOptions[0]?.textContent.split(" · ")[0] || "The"} sheet is showing.`);
        });
        const every = button({ label: "Export every group", glyph: "↓", onClick: () => exportEvery(templateId) });
        fill(switcher, pick, every);
      }
      select.value = value;
      switcher.hidden = false;
    };

    body.append(switcher, sheet);

    // Opening a box is the sheet's job; which drawer opens is not, so it only says that one opened.
    sheet.addEventListener("hw-sheet-open", (event) => {
      openDrawer({ ...event.detail, courseId, onSaved: async (sessionId) => {
        const register = await api.get(`/api/sessions/${sessionId}/register`);
        sheet.replaceClass(sessionId, register);
        toast("The correction is saved and the sheet is updated.");
      } });
    });

    // A student's name or matric number opens their details (asked for on 2026-09-23): names get
    // corrected, and direct-entry students are given the matric number they did not have.
    sheet.addEventListener("hw-sheet-edit-student", (event) => {
      editStudent(event.detail, () => sheet.load(sheetUrl()), course);
    });

    await sheet.load(sheetUrl());
    syncSwitcher();
  },
};

/**
 * Every group's sheet in one file: a section of pages per group in the PDF, a worksheet per group in
 * the spreadsheet, and the students in no group last when there are any. Asked as a choice of the
 * two files, because a format choice is the only thing left to decide.
 */
function exportEvery(templateId) {
  const path = (format) => `/api/templates/${templateId}/export?format=${format}&group=all`;
  // Closed once the file is saved; a refusal stays in its toast with the dialog still open.
  const save = async (control, format) => {
    if (await saveFile(control, path(format), "Every group's attendance sheet")) box.close();
  };
  const pdf = button({ label: "PDF", glyph: "↓", primary: true, busyLabel: "Drawing the PDF",
    onClick: () => save(pdf, "pdf") });
  const xlsx = button({ label: "Excel", glyph: "↓", busyLabel: "Writing the spreadsheet",
    onClick: () => save(xlsx, "xlsx") });
  const box = dialog({
    title: "Export every group's sheet",
    body: h("p", { style: { margin: 0 } },
      "One file holding each group's sheet in turn, each with its group under the course line and its "
      + "own page numbers. The PDF has a section of pages per group; the spreadsheet has a worksheet "
      + "per group."),
    actions: [button({ label: "Not now", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end hw-row" }, xlsx, pdf)],
  });
}

function editStudent(student, reload, course) {
  const surname = field({ label: "Surname", value: student.surname || "", required: true,
    validate: (v) => (v.trim() ? "" : "A student needs a surname.") });
  const others = field({ label: "Other names", value: student.other_names || "" });
  const matric = field({ label: "Matric number", value: student.matric_no || "", ids: true, width: "medium",
    help: "Leave it empty, or type DE, for a direct-entry student who has not been given one yet, and "
      + "add it here when it comes. Their device ID, fingerprints and attendance stay with them either way." });
  const save = button({ label: "Save", primary: true, busyLabel: "Saving", permission: "roster.manage" });
  // Taking a student off the course from the sheet, as well as from the Students tab (asked for on
  // 2026-09-24: "can i delete students on the sheets too just like we can add"). It hands over to the
  // Students tab's own removal, so there is one set of rules and one explanation. It sits in the body,
  // apart from Save, because a destructive control never shares a group with a primary one.
  const remove = button({ label: "Remove from this course", variant: "destructive",
    permission: "courses.manage",
    onClick: () => {
      box.close();
      removeDialog(course, student, reload);
    } });
  const box = dialog({
    title: student.matric_no ? `Edit ${student.full_name}` : `Edit ${student.full_name}, direct entry (DE)`,
    body: h("div", { class: "hw-stack hw-stack--tight" }, surname, others, matric,
      h("div", { class: "hw-stack hw-stack--tight", style: { marginBlockStart: "var(--hw-space-4)",
        paddingBlockStart: "var(--hw-space-4)", borderBlockStart: "var(--hw-rule-width) solid var(--hw-rule)" } },
        h("p", { class: "hw-muted", style: { margin: 0 } },
          `Not taking ${course.code}? Remove them from this course. Their attendance so far is kept, `
          + "and they stay on their level and on the terminal."),
        h("div", {}, remove))),
    actions: [button({ label: "Cancel", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  const control = save.matches?.("button") ? save : save.querySelector("button");
  control.addEventListener("click", async () => {
    if (surname.check?.()) return;
    const value = (f) => f.querySelector("input").value;
    setBusy(control, true);
    try {
      const done = await api.put(`/api/people/${student.person_id}`, {
        surname: value(surname), other_names: value(others), matric_no: value(matric).trim() || null });
      box.close();
      if (!done.changed) {
        toast("Nothing was changed.");
        return;
      }
      toast(done.terminal && done.terminal !== "sent"
        ? `Saved. The terminal still shows the old name: ${done.terminal.replace(/^not sent: /, "")}`
        : done.terminal === "sent" ? "Saved, and the terminal shows the new name." : "Saved.",
      done.terminal && done.terminal !== "sent" ? "failure" : "success");
      announce("The student's details are saved.");
      await reload();
    } catch (error) {
      setBusy(control, false);
      toast(error instanceof ApiError ? error.message : "That did not save.", "failure");
    }
  });
}
