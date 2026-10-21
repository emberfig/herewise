// The two lists that were not among the 42 designed, added on 2026-09-20 and built here:
// "Attendance so far", the notice to post, and "Students below the pass mark", the at-risk list.
// Contract: GET /api/courses/{id}/progress, exports at /progress/export?variant=notice|at_risk.
//
// Why they exist, from the competitor research (vault, Herewise competitors 2026-09-19): the
// University of Uyo publishes its 75% lists two weeks before examinations and refuses appeals. A
// student who cannot appeal must at least be able to check in time, and the owner decided on
// 2026-09-20 that students may see their percentages during the semester.
//
// There is no mockup for either, so they follow the screens they sit beside: the Decision ledger's
// rules strip first, then the counts, then the list, with the export beside the list it exports.
//
// The two lists are deliberately different, and the difference is the point:
//   the notice carries matric numbers and percentages and no names, because it goes on a board
//     where anyone walking past can read it;
//   the at-risk list carries names, because it is the lecturer's own copy and its use is to talk
//     to the people on it while there is still time.

import { api, download } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  matricText,
  announce, button, fill, h, loadingTable, longDate, page, plural, saveFile, section, table,
} from "../ui.js";
import { frame } from "./course.js";

const TONE = {
  met: ["✓", "present"],
  on_track: ["✓", "present"],
  at_risk: ["?", "review"],
  below: ["✕", "absent"],
  cannot_reach: ["✕", "absent"],
  all_excused: ["E", "excused"],
  no_classes_yet: ["○", "neutral"],
};

export default {
  id: "course-progress",
  nav: "courses",
  title: "Attendance so far",
  permission: "eligibility.view",

  async render(view, ctx) {
    const courseId = Number(ctx.params.id);
    const { body } = await frame(view, courseId, "eligibility");
    fill(body, loadingTable(["Matric no.", "Present", "Percentage", "What they still need"]));
    const data = await api.get(`/api/courses/${courseId}/progress`);
    draw(body, courseId, data);
  },
};

function draw(body, courseId, data) {
  const r = data.rules;
  const atRisk = data.students.filter((s) =>
    ["at_risk", "below", "cannot_reach"].includes(s.status));

  fill(body,
    h("p", { style: { marginBlockEnd: "var(--hw-space-4)" } },
      h("a", { class: "hw-link", href: href(`courses/${courseId}/eligibility`) },
        h("span", { "aria-hidden": "true" }, "← "), "Back to the eligibility decision")),

    h("div", { class: "hw-card hw-stack hw-stack--tight",
      style: { marginBlockEnd: "var(--hw-space-6)" } },
      h("p", { style: { margin: 0 } },
        h("span", { class: "hw-pill", dataset: { tone: "review" } },
          h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "?"), "PART WAY THROUGH"),
        h("span", { class: "hw-muted" },
          ` ${r.classes_held} of ${r.planned_classes} classes held, `
          + `${plural(r.classes_remaining, "still to come", "still to come")}. `
          + "Nobody is barred by this list: it is what the figures say today.")),
      h("dl", { class: "hw-facts" },
        h("dt", {}, "Pass mark"), h("dd", { class: "hw-tnum" }, `${r.threshold_percent}%`),
        h("dt", {}, "Excused absences"),
        h("dd", {}, r.excused_excluded
          ? "left out of the student's total" : "counted as attended"),
        h("dt", {}, "Class average"),
        h("dd", { class: "hw-tnum" }, `${data.class_average_percent}%`))),

    section("Attendance so far, the notice to post",
      h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-3)" } },
        "Matric numbers and percentages, no names, so it can go on a board where anyone walking "
        + "past can read it. Every student can find their own line and nobody else's name."),
      table({
        caption: "Attendance so far, by matric number",
        density: "compact",
        rows: data.students,
        limit: 25,
        what: "student",
        columns: [
          { label: "S/N", align: "end", render: (s) => h("span", { class: "hw-tnum" }, String(s.sn)) },
          { label: "Matric no.", render: (s) => h("span", { class: "hw-ids" }, matricText(s.matric_no)) },
          { label: "Present", align: "end", render: (s) =>
            h("span", { class: "hw-tnum" }, `${s.attended} of ${s.counted}`) },
          { label: "Percentage", align: "end", render: (s) =>
            h("span", { class: "hw-tnum" }, `${s.percent}%`) },
          { label: "Where they stand", align: "end", render: (s) => statusPill(s) },
        ],
      }),
      exportRow(courseId, "notice", "the notice to post")),

    section(`Students below the pass mark (${atRisk.length})`,
      h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-3)" } },
        "The lecturer's own copy, with names, because its use is to talk to the people on it while "
        + "there is still time. Anyone who can no longer reach the pass mark is marked, and the "
        + "best percentage they can still finish on is beside them."),
      atRisk.length
        ? table({
          caption: "Students below the pass mark",
          rows: atRisk,
          columns: [
            { label: "Matric no.", render: (s) =>
              h("a", { class: "hw-link hw-ids", href: href(`students/${s.person_id}`) }, matricText(s.matric_no)) },
            { label: "Name", render: (s) => h("span", {}, s.full_name,
              s.carry_over ? h("span", { class: "hw-tag" }, "carry-over") : null) },
            { label: "Present", align: "end", render: (s) =>
              h("span", { class: "hw-tnum" }, `${s.attended} of ${s.counted}`) },
            { label: "Percentage", align: "end", render: (s) =>
              h("span", { class: "hw-tnum" }, `${s.percent}%`) },
            { label: "What they still need", render: (s) => needs(s, r) },
            { label: "Best they can finish on", align: "end", render: (s) =>
              s.best_possible_percent === null || s.best_possible_percent === undefined
                ? h("span", { class: "hw-muted" }, "–")
                : h("span", { class: "hw-tnum" }, `${s.best_possible_percent}%`) },
            { label: "", align: "end", render: (s) => statusPill(s) },
          ],
        })
        : h("div", { class: "hw-table-frame" }, h("div", { class: "hw-state" },
          h("span", { class: "hw-state__icon", "aria-hidden": "true" }, "✓"),
          h("h2", { class: "hw-state__heading" }, "Nobody is below the pass mark"),
          h("p", { class: "hw-state__body" },
            `Every student is at or above ${r.threshold_percent}% on the classes held so far.`))),
      exportRow(courseId, "at_risk", "the at-risk list")));
}

function statusPill(student) {
  const [glyph, tone] = TONE[student.status] || TONE.at_risk;
  return h("span", { class: "hw-pill", dataset: { tone } },
    h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, glyph), student.status_text);
}

function needs(student, rules) {
  if (student.status === "cannot_reach") {
    return h("span", {},
      `${student.more_needed} more, and only `
      + `${plural(rules.classes_remaining, "class", "classes")} left`);
  }
  if (student.more_needed === null || student.more_needed === undefined) {
    return h("span", { class: "hw-muted" }, "No plan to measure against");
  }
  return h("span", {},
    `${student.more_needed} more of the ${rules.classes_remaining} left`
    + (student.can_still_miss ? `, and can miss ${student.can_still_miss}` : ", and can miss none"));
}

function exportRow(courseId, variant, what) {
  const go = (format, control) => saveFile(control,
    `/api/courses/${courseId}/progress/export?format=${format}&variant=${variant}`, `The ${what}`);
  const pdf = button({ label: "Download PDF", glyph: "↓", permission: "eligibility.export",
    busyLabel: "Drawing the PDF", onClick: () => go("pdf", pdf) });
  const excel = button({ label: "Download Excel", glyph: "↓", permission: "eligibility.export",
    busyLabel: "Writing the spreadsheet", onClick: () => go("xlsx", excel) });
  return h("p", { class: "hw-row", style: { marginBlockStart: "var(--hw-space-3)" } }, pdf, excel);
}
