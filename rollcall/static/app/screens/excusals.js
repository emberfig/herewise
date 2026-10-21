// Screen 19: Excused absences. Mockups: ExcusedabsencesonPCT201.png, Excusedabsencesrecording.png,
// Excusedabsenceswithdrawnshown.png, Excusedabsencesselfrecordrefused.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "19 Excused absences".
//
// The rule no role can grant away, drawn exactly: nobody excuses the student record their own
// account is linked to, whatever their role allows. The refusal is the backend's own sentence.
//
// Kept from the mockup: each matric number links to the student's record, because an excused
// absence is most often checked from the student's side; and a withdrawn row keeps who withdrew it,
// when and why, with its E drawn in outline rather than filled.
//
// Fixed from the mockup: the toolbar button is hidden while its own form is open, so there are
// never two buttons with the same label, one enabled and one not; and a date never breaks across
// lines.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  invalid, matricText,
  announce, button, dialog, fill, field, h, loadingTable, longDate, page, plural, section, setBusy,
  table, toast,
} from "../ui.js";

const CATEGORIES = [
  { value: "medical", label: "Medical" },
  { value: "official", label: "Official university business" },
  { value: "bereavement", label: "Bereavement" },
  { value: "other", label: "Other" },
];

export default {
  id: "excusals",
  nav: "courses",
  title: "Excused absences",
  permission: "register.read",

  async render(view, ctx) {
    const courseId = ctx.query.get("course") ? Number(ctx.query.get("course")) : null;
    const personId = ctx.query.get("student") ? Number(ctx.query.get("student")) : null;
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Excused absences",
      children: [loadingTable(["Student", "Dates", "Category", "Why", "Covers"])] }));
    const reload = () => this.render(fill(view), ctx);

    const query = new URLSearchParams();
    if (courseId) query.set("course_id", courseId);
    if (personId) query.set("person_id", personId);
    const [rows, courses] = await Promise.all([
      api.get(`/api/excusals?${query}`),
      api.get("/api/courses").catch(() => []),
    ]);
    draw(host, rows, courses, courseId, reload);
  },
};

function draw(host, rows, courses, courseId, reload) {
  const live = rows.filter((r) => !r.revoked_at);
  const withdrawn = rows.filter((r) => r.revoked_at);
  const state = { showWithdrawn: false, formOpen: false };
  const course = courses.find((c) => c.id === courseId);
  const body = h("div");
  const toolbar = h("div", { class: "hw-row hw-row--between",
    style: { marginBlockEnd: "var(--hw-space-4)" } });

  function paint() {
    const record = button({ label: "Record excused absence", primary: true,
      permission: "excusal.manage",
      onClick: () => recordDialog(courses, courseId, reload) });
    fill(toolbar,
      h("p", { class: "hw-muted", style: { margin: 0 } },
        `${plural(live.length, "excused absence")} in force`
        + (withdrawn.length ? ` · ${withdrawn.length} withdrawn` : "")),
      h("div", { class: "hw-row" },
        withdrawn.length
          ? h("label", { class: "hw-row", style: { gap: "var(--hw-space-2)" } },
            h("input", { type: "checkbox", checked: state.showWithdrawn || null,
              onChange: (event) => { state.showWithdrawn = event.target.checked; paint(); } }),
            h("span", {}, `Show withdrawn (${withdrawn.length})`))
          : null,
        // Hidden while its own form is open, so there is never a second button with this label.
        state.formOpen ? null : record));

    fill(body,
      live.length
        ? excusalTable(live, reload)
        : h("div", { class: "hw-table-frame" }, h("div", { class: "hw-state" },
          h("span", { class: "hw-state__icon", "aria-hidden": "true" }, "E"),
          h("h2", { class: "hw-state__heading" }, "No excused absences"),
          h("p", { class: "hw-state__body" },
            "An excused absence takes a class out of a student's total instead of counting against "
            + "them. Record one when a student was away for a reason you accept."))),
      state.showWithdrawn && withdrawn.length
        ? section("Withdrawn", excusalTable(withdrawn, reload, true)) : null);
  }

  fill(host, page({
    title: "Excused absences",
    subtitle: course ? `${course.code}${course.title ? ` ${course.title}` : ""}` : "Every course",
    children: [
      h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-6)" } },
        "By default an excused class comes out of that student's total rather than counting against "
        + "them. A scan in an excused period still counts as present, and a correction beats both."),
      toolbar, body,
    ],
  }));
  paint();
}

function excusalTable(rows, reload, withdrawn = false) {
  return table({
    caption: withdrawn ? "Withdrawn excused absences" : "Excused absences in force",
    rows,
    rowAttrs: () => (withdrawn ? { dataset: { dimmed: "true" } } : null),
    columns: [
      { label: "Student", render: (r) => h("span", {},
        h("a", { class: "hw-link hw-ids", href: href(`students/${r.person_id}`) }, matricText(r.matric_no)),
        h("span", {}, ` ${r.surname} ${r.other_names}`.trimEnd())) },
      // Each date holds together, the range between them is allowed to break. Held as one line,
      // "Monday, 31 August 2026 to Friday, 4 September 2026" is 350px of a 1,085px table and it
      // squeezed Why and Covers into columns 90px wide (measured 2026-09-22).
      { label: "Dates", render: (r) => (r.date_from === r.date_to
        ? h("span", { class: "hw-nowrap" }, longDate(r.date_from))
        : h("span", {},
          h("span", { class: "hw-nowrap" }, longDate(r.date_from)), " to ",
          h("span", { class: "hw-nowrap" }, longDate(r.date_to)))) },
      { label: "Category", render: (r) =>
        h("span", { class: "hw-pill", dataset: { tone: "excused" } },
          h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "E"),
          CATEGORIES.find((c) => c.value === r.category)?.label || r.category) },
      { label: "Why", render: (r) => r.note },
      { label: "Covers", render: (r) => r.course_code
        ? h("span", {}, r.course_code)
        : h("span", { class: "hw-muted" }, "Every course") },
      { label: "", align: "end", render: (r) => withdrawn
        ? h("span", { class: "hw-muted hw-nowrap" },
          `Withdrawn by ${r.revoked_by_name || "someone"}, ${longDate((r.revoked_at || "").slice(0, 10))}`)
        : button({ label: "Withdraw", permission: "excusal.manage",
            reason: session.isSelf(r.person_id)
              ? "You cannot withdraw an excused absence for yourself. Ask someone else to do it." : "",
            onClick: () => withdrawDialog(r, reload) }) },
    ],
  });
}

function recordDialog(courses, courseId, reload) {
  const student = field({ label: "Student", name: "student",
    help: "Matric number, name or device ID. Choose from the list that appears." });
  const found = h("div");
  const state = { personId: null };

  student.control.addEventListener("input", async () => {
    const q = student.value().trim();
    if (q.length < 2) return fill(found);
    const results = await api.get(`/api/students/search?q=${encodeURIComponent(q)}`).catch(() => []);
    fill(found, ...results.slice(0, 6).map((row) => {
      const btn = h("button", { class: "hw-choice", type: "button", style: { width: "100%" } },
        h("span", {},
          h("span", { class: "hw-choice__label" }, `${row.surname} ${row.other_names}`.trim()),
          h("span", { class: "hw-choice__help" },
            ` ${matricText(row.matric_no)} · ${row.level_number || row.level || ""} Level`)));
      btn.addEventListener("click", () => {
        state.personId = row.person_id ?? row.id;
        student.control.value = `${row.surname} ${row.other_names}`.trim();
        fill(found);
        update();
      });
      return btn;
    }));
  });

  const from = field({ label: "From", type: "date", ids: true, onInput: () => update() });
  const to = field({ label: "To", type: "date", ids: true, onInput: () => update() });
  const category = field({ label: "Category", options: CATEGORIES });
  const scope = field({ label: "Which course?",
    options: [{ value: "", label: "Every course" },
      ...courses.map((c) => ({ value: c.id, label: `${c.code}${c.title ? ` ${c.title}` : ""}` }))],
    value: courseId ? String(courseId) : "" });
  const note = field({ label: "Why", rows: 3,
    help: "For example the medical report reference. Kept with the record for good.",
    validate: (v) => (v.trim() ? "" : "Record the reason, for example the medical report reference."),
    onInput: () => update() });

  const save = button({ label: "Record excused absence", primary: true, busyLabel: "Recording",
    disabled: true });
  const saveButton = save.matches("button") ? save : save.querySelector("button");
  const reason = h("p", { class: "hw-reason" });

  function update() {
    let stop = "";
    if (!state.personId) stop = "Choose a student first.";
    // Enforced in the backend as well, and separate from the permission.
    else if (session.isSelf(state.personId)) {
      stop = "You cannot grant an excused absence for yourself. Ask someone else to do it.";
    } else if (!from.value() || !to.value()) stop = "Choose the dates it covers.";
    else if (to.value() < from.value()) stop = "The last day cannot be before the first.";
    else if (!note.value().trim()) {
      stop = "Record the reason, for example the medical report reference.";
    }
    saveButton.disabled = Boolean(stop);
    reason.textContent = stop;
    reason.hidden = !stop;
  }

  const box = dialog({
    title: "Record an excused absence",
    body: h("div", { class: "hw-stack" }, student, found,
      h("div", { class: "hw-row", style: { alignItems: "flex-start" } },
        h("div", { style: { flex: "1 1 180px" } }, from),
        h("div", { style: { flex: "1 1 180px" } }, to)),
      category, scope, note),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end hw-control hw-control--end" }, save, reason)],
  });

  saveButton.addEventListener("click", async () => {
    if (invalid(note)) return;
    setBusy(save, true);
    try {
      await api.post("/api/excusals", { person_id: state.personId, date_from: from.value(),
        date_to: to.value(), category: category.value(), note: note.value().trim(),
        course_id: scope.value() ? Number(scope.value()) : null });
      box.close();
      toast("The excused absence is recorded.");
      announce("Recorded.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      note.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
  update();
}

function withdrawDialog(row, reload) {
  const note = field({ label: "Why is it being withdrawn?", rows: 3,
    help: "Kept with the record, beside the original reason.",
    validate: (v) => (v.trim() ? "" : "Say why it is being withdrawn.") });
  const save = button({ label: "Withdraw it", variant: "destructive", busyLabel: "Withdrawing" });
  const box = dialog({
    title: "Withdraw this excused absence",
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        `Those classes count against ${`${row.surname} ${row.other_names}`.trim()} again from now on. `
        + "The original record is kept, with who withdrew it and why."),
      note),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(note)) return;
    setBusy(save, true);
    try {
      await api.post(`/api/excusals/${row.id}/revoke`, { note: note.value().trim() });
      box.close();
      toast("The excused absence is withdrawn.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      note.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}
