// Screen 18: Eligibility, and the Decision ledger, hero signature 3 of 3.
// Mockups: Eligibilityfinal.png, Eligibilityprovisional.png, Eligibilitynopassmark.png,
// Eligibilityallexcused.png. Fix list: docs/DESIGN-DEVIATIONS.md, "18 Eligibility".
// Spec: docs/COMPONENT-GUIDE.md, "Decision ledger". Contract: GET /api/courses/{id}/eligibility.
//
// The rules strip comes first, then the counts, then the list, because this is the decision the
// lecturer is accountable for and it has to state what it was made under. The WHY column is what the
// screen is for: nobody approves the list without seeing why each name is on it.
//
// Fixed from the mockup: "Showing 6 of 258" under a "Needs review" filter now reads against the
// filtered set; every verdict carries its shape, because the exported list is photocopied in black
// and white and colour will not survive.

import { api, download } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  matricText,
  announce, button, fill, h, loadingTable, longDate, plural, saveFile, section, table,
} from "../ui.js";
import { frame } from "./course.js";

const DECISIONS = {
  eligible: { glyph: "✓", word: "ELIGIBLE", tone: "present" },
  not_eligible: { glyph: "✕", word: "NOT ELIGIBLE", tone: "absent" },
  review: { glyph: "?", word: "REVIEW", tone: "review" },
};

const FILTERS = [
  { id: "all", label: "Everyone" },
  { id: "not_eligible", label: "Not eligible" },
  { id: "review", label: "Needs review" },
  { id: "eligible", label: "May sit" },
];

export default {
  id: "course-eligibility",
  nav: "courses",
  title: "Eligibility",
  permission: "eligibility.view",

  async render(view, ctx) {
    const courseId = Number(ctx.params.id);
    const exportFull = button({ label: "Export the full list", primary: true, glyph: "↓",
      permission: "eligibility.export", busyLabel: "Drawing the PDF",
      onClick: () => saveFile(exportFull,
        `/api/courses/${courseId}/eligibility/export?format=pdf&variant=full`,
        "The full eligibility list") });
    const { body } = await frame(view, courseId, "eligibility", { actions: [exportFull] });
    fill(body, loadingTable(["S/N", "Matric no.", "Name", "Present", "Percentage", "Decision"]));
    const data = await api.get(`/api/courses/${courseId}/eligibility`);
    draw(body, courseId, data);
  },
};

function draw(body, courseId, data) {
  let filter = "all";
  const list = h("div");
  const filters = h("div", { class: "hw-counts", role: "group", "aria-label": "Show only" });

  function paint() {
    fill(filters, ...FILTERS.map((spec) => {
      const count = spec.id === "all" ? data.students.length
        : data.students.filter((s) => s.decision === spec.id).length;
      const tone = spec.id === "all" ? "" : DECISIONS[spec.id].tone;
      const btn = h("button", { class: "hw-counts__item", type: "button",
        dataset: { action: `filter-${spec.id}`, tone }, "aria-pressed": String(filter === spec.id) },
        spec.id === "all" ? null
          : h("span", { class: "hw-counts__glyph", "aria-hidden": "true" }, DECISIONS[spec.id].glyph),
        h("span", { class: "hw-counts__value hw-tnum" }, String(count)),
        h("span", { class: "hw-counts__label" }, spec.label));
      btn.addEventListener("click", () => { filter = spec.id; paint(); });
      return btn;
    }));

    // Not eligible and review first, as the guide says: the names that need a decision.
    const order = { not_eligible: 0, review: 1, eligible: 2 };
    const rows = data.students
      .filter((s) => filter === "all" || s.decision === filter)
      .sort((a, b) => order[a.decision] - order[b.decision] || a.sn - b.sn);

    fill(list,
      h("p", { class: "hw-muted", role: "status", style: { marginBlock: "var(--hw-space-3)" } },
        filter === "all"
          ? `Showing all ${plural(rows.length, "student")}`
          // The denominator is the filtered set, not the whole register.
          : `Showing ${plural(rows.length, "student")} of ${data.students.length} on the register`),
      table({
        caption: "The examination eligibility decision",
        rows,
        limit: 25,
        what: "student",
        columns: [
          { label: "S/N", align: "end", render: (r) => h("span", { class: "hw-tnum" }, String(r.sn)) },
          { label: "Matric no.", render: (r) =>
            h("a", { class: "hw-link hw-ids", href: href(`students/${r.person_id}`) }, matricText(r.matric_no)) },
          { label: "Name", render: (r) => h("span", {}, r.full_name,
            r.carry_over ? h("span", { class: "hw-tag" }, "carry-over") : null,
            // On a course with groups, whose classes the student was counted against.
            r.group ? h("span", { class: "hw-tag" }, r.group) : null) },
          { label: "Present", align: "end", render: (r) =>
            h("span", { class: "hw-tnum" }, `${r.attended} of ${r.counted}`) },
          { label: "Percentage", align: "end", render: (r) =>
            h("span", { class: "hw-tnum" }, `${r.percent}%`) },
          { label: "Why", render: (r) => why(r, data.rules) },
          { label: "Decision", align: "end", render: (r) => {
            const spec = DECISIONS[r.decision];
            return h("span", { class: "hw-pill", dataset: { tone: spec.tone } },
              h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, spec.glyph), spec.word);
          } },
        ],
      }));
  }

  fill(body,
    rulesStrip(data),
    filters,
    list,
    exports(courseId),
    h("p", { class: "hw-section__help" },
      "The full list has names, counts, percentages and signature lines for the course lecturer and "
      + "the head of department. The notice has matric numbers and the decision only, for posting."),
    h("p", {},
      h("a", { class: "hw-link", href: href(`courses/${courseId}/progress`) },
        "Attendance so far, and who is below the pass mark"),
      h("span", { class: "hw-muted" },
        ". Part way through the term, before anybody is barred.")));
  paint();
}

/** The rules strip: what this decision was made under, stated before the decision itself. */
function rulesStrip(data) {
  const r = data.rules;
  return h("div", { class: "hw-card hw-stack hw-stack--tight", style: { marginBlockEnd: "var(--hw-space-6)" } },
    r.provisional
      ? h("p", { style: { margin: 0 } },
        h("span", { class: "hw-pill", dataset: { tone: "review" } },
          h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "?"), "PROVISIONAL"),
        h("span", { class: "hw-muted" },
          ` ${plural(r.classes_remaining, "class", "classes")} of the ${r.planned_classes} planned `
          + "have still to be held, so this list can change."))
      : h("p", { style: { margin: 0 } },
        h("span", { class: "hw-pill", dataset: { tone: "present" } },
          h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "✓"), "FINAL"),
        h("span", { class: "hw-muted" }, " Every planned class has been held.")),
    h("dl", { class: "hw-facts" },
      h("dt", {}, "Pass mark"), h("dd", { class: "hw-tnum" }, `${r.threshold_percent}%`),
      h("dt", {}, "Classes held"), h("dd", { class: "hw-tnum" },
        `${r.classes_held} of ${r.planned_classes} planned`
        + (r.grouped ? ", for each student at most: the classes for everybody and their own group's" : "")),
      h("dt", {}, "Excused absences"), h("dd", {}, r.excused_text),
      h("dt", {}, "Dates"), h("dd", { class: "hw-nowrap" },
        r.date_from || r.date_to
          ? `${r.date_from ? longDate(r.date_from) : "the start"} to `
            + `${r.date_to ? longDate(r.date_to) : "today"}`
          : "the whole session so far")));
}

function why(row, rules) {
  if (row.decision === "eligible") {
    return h("span", { class: "hw-muted" }, `at or above ${rules.threshold_percent}%`);
  }
  if (row.decision === "not_eligible") {
    return h("span", {}, `${row.percent}% is below ${rules.threshold_percent}%`);
  }
  if (row.counted === 0) {
    return h("span", {}, `excused from all ${plural(row.excused, "class", "classes")} counted`);
  }
  if (!rules.classes_held) return h("span", {}, "no classes have been held yet");
  return h("span", {}, `${plural(row.excused, "excused absence")}, so the total is different`);
}

function exports(courseId) {
  const items = [
    ["Full list, PDF", "pdf", "full", "Names, counts, percentages and signature lines."],
    ["Full list, Excel", "xlsx", "full", "The same, as a spreadsheet."],
    ["Notice to post, PDF", "pdf", "notice", "Matric numbers and the decision only, no names."],
    ["Notice to post, Excel", "xlsx", "notice", "The same, as a spreadsheet."],
  ];
  return section("Export it", h("div", { class: "hw-grid" }, ...items.map(([label, format, variant, note]) =>
    h("div", { class: "hw-card hw-stack hw-stack--tight" },
      h("p", { class: "hw-card__title" }, label),
      h("p", { class: "hw-card__body" }, note),
      h("p", { class: "hw-card__foot" },
        downloadButton(courseId, label, format, variant))))));
}


function downloadButton(courseId, label, format, variant) {
  const go = button({ label: "Download", permission: "eligibility.export", glyph: "↓",
    busyLabel: format === "pdf" ? "Drawing the PDF" : "Writing the spreadsheet",
    onClick: () => saveFile(go,
      `/api/courses/${courseId}/eligibility/export?format=${format}&variant=${variant}`, label) });
  return go;
}
