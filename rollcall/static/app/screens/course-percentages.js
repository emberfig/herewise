// Screen 17: Percentages, the Percentages tab of a course, with the Threshold dial.
// Mockups: Percentagessavedplan.png, Percentagestryinganotherfigure.png, Percentagesnoplanyet.png,
// Percentagesmoreheldthanplanned.png. Fix list: docs/DESIGN-DEVIATIONS.md, "17 Percentages".
//
// Kept from the mockup: the NEEDS column beside the verdict, so the reason for barring a student is
// never a figure to be worked out elsewhere.
//
// Fixed from the mockup, and it is the most important fix in the app: **every figure below the pass
// mark recomputes from the same numbers as the panel above it, before anything is saved.** In the
// mockup the hero said "1 can no longer reach it" over a table still listing three from the old
// figure. This screen is what bars a student from an examination.
//
// Recomputing means asking the backend, not the page: GET /api/courses/{id}/summary takes the
// what-if numbers as query parameters and works them out itself, so a what-if and a saved plan can
// never be two different sums.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  keepFocusOn, matricText,
  announce, button, fill, h, loadingTable, plural, section, setBusy, table, toast, uid,
} from "../ui.js";
import { frame } from "./course.js";

const FILTERS = [
  { id: "all", label: "Everyone", keep: () => true },
  { id: "below", label: "Below the pass mark", keep: (s) => s.below_threshold },
  { id: "cannot_reach", label: "Cannot reach it", keep: (s) => s.status === "cannot_reach" },
];

export default {
  id: "course-percentages",
  nav: "courses",
  title: "Percentages",
  permission: "register.read",

  async render(view, ctx) {
    const courseId = Number(ctx.params.id);
    const { course, body } = await frame(view, courseId, "percentages");
    fill(body, loadingTable(["Matric no.", "Name", "Present", "Percentage", "Needs", "Verdict"]));
    const [summary, plan] = await Promise.all([
      api.get(`/api/courses/${courseId}/summary`),
      api.get(`/api/courses/${courseId}/attendance-plan`).catch(() => null),
    ]);
    draw(body, courseId, summary, plan);
  },
};

function draw(body, courseId, saved, plan) {
  const state = {
    weeks: saved.plan.weeks ?? "",
    classesPerWeek: saved.plan.classes_per_week ?? "",
    threshold: saved.plan.threshold_percent,
    summary: saved,
    dirty: false,
  };

  const figures = h("div");
  const list = h("div");
  const filters = h("div", { class: "hw-counts", role: "group", "aria-label": "Show only" });
  let filter = "all";

  const threshold = numberField("Pass mark", state.threshold, "%", 0, 100, (value) => {
    state.threshold = value;
    recompute();
  });
  const weeks = numberField("Weeks", state.weeks, "", 1, 52, (value) => {
    state.weeks = value;
    recompute();
  });
  const perWeek = numberField("Classes a week", state.classesPerWeek, "", 0, 7, (value) => {
    state.classesPerWeek = value;
    recompute();
  });

  const save = button({ label: "Save these figures", primary: true, permission: "plan.manage",
    disabled: true, reason: "", busyLabel: "Saving" });
  const saveButton = save.matches("button") ? save : save.querySelector("button");
  const savedNote = h("span", { role: "status" });

  let pending = null;
  async function recompute() {
    state.dirty = true;
    saveButton.disabled = !session.can("plan.manage");
    saveButton.title = "";
    fill(savedNote,
      h("span", { class: "hw-reason" }, "Not saved yet. The figures below are what these numbers give."));
    clearTimeout(pending);
    pending = setTimeout(async () => {
      const query = new URLSearchParams();
      if (state.threshold !== "") query.set("threshold_percent", state.threshold);
      if (state.weeks !== "" && state.classesPerWeek !== "") {
        query.set("weeks", state.weeks);
        query.set("classes_per_week", state.classesPerWeek);
      }
      try {
        state.summary = await api.get(`/api/courses/${courseId}/summary?${query}`);
        paint();
      } catch (error) {
        toast(error instanceof ApiError ? error.message : "Those figures did not work.", "failure");
      }
    }, 250);
  }

  saveButton.addEventListener("click", async () => {
    setBusy(save, true);
    try {
      await api.put(`/api/courses/${courseId}/attendance-plan`, {
        weeks: state.weeks === "" ? null : Number(state.weeks),
        classes_per_week: state.classesPerWeek === "" ? null : Number(state.classesPerWeek),
        threshold_percent: state.threshold === "" ? null : Number(state.threshold),
      });
      state.dirty = false;
      saveButton.disabled = true;
      saveButton.title = "Nothing has changed since the last save.";
      fill(savedNote, h("span", { class: "hw-confirmation" },
        h("span", { class: "hw-confirmation__glyph", "aria-hidden": "true" }, "✓"),
        "Saved. The eligibility list uses these figures now."));
      announce("The figures are saved.");
      keepFocusOn(savedNote);
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "That did not save.", "failure");
    } finally {
      setBusy(save, false);
    }
  });

  function paint() {
    const s = state.summary;
    const counts = s.status_counts || {};
    fill(figures, h("div", { class: "hw-headline" },
      hero("✓", "present", String(counts.met ?? 0), "have met the pass mark",
        `${s.sessions_held} of ${s.planned_classes} classes held${s.grouped ? " for each student, at most" : ""}`),
      hero("✓", "present", String(counts.on_track ?? 0), "still on track",
        `they can reach ${s.threshold_percent}%`),
      hero("✕", "absent", String(s.below_threshold), "below the pass mark",
        `${counts.cannot_reach ?? 0} can no longer reach it`),
      hero("i", "", `${s.classes_needed_to_pass ?? "–"}`, "classes needed to pass",
        `${s.classes_remaining} still to come`)));

    fill(filters, ...FILTERS.map((spec) => {
      const count = s.students.filter(spec.keep).length;
      const btn = h("button", { class: "hw-counts__item", type: "button",
        dataset: { action: `filter-${spec.id}` }, "aria-pressed": String(filter === spec.id) },
        h("span", { class: "hw-counts__value hw-tnum" }, String(count)),
        h("span", { class: "hw-counts__label" }, spec.label));
      btn.addEventListener("click", () => { filter = spec.id; paint(); });
      return btn;
    }));

    const spec = FILTERS.find((f) => f.id === filter);
    const rows = s.students.filter(spec.keep);
    fill(list,
      h("p", { class: "hw-muted", role: "status", style: { marginBlock: "var(--hw-space-3)" } },
        // The denominator is the filtered set, not the register.
        filter === "all" ? `Showing all ${plural(rows.length, "student")}`
          : `Showing ${plural(rows.length, "student")} of ${s.students.length}`),
      table({
        caption: "Every student's percentage",
        rows,
        limit: 25,
        what: "student",
        columns: [
          { label: "Matric no.", render: (r) =>
            h("a", { class: "hw-link hw-ids", href: href(`students/${r.person_id}`) }, matricText(r.matric_no)) },
          { label: "Name", render: (r) => `${r.surname} ${r.other_names}`.trim() },
          // On a course with groups each student is counted against their own group's classes, so
          // the group is what explains two students with different figures for the same weeks.
          ...(s.grouped ? [{ label: "Group", render: (r) => r.group || h("span", { class: "hw-muted" }, "No group") }] : []),
          // No HELD column: PRESENT already says "6 of 18".
          { label: "Present", align: "end", render: (r) =>
            h("span", { class: "hw-tnum" }, `${r.attended} of ${r.counted}`) },
          { label: "Percentage", align: "end", render: (r) =>
            h("span", { class: "hw-tnum" }, `${r.percent}%`) },
          { label: "Needs", render: (r) => needsWords(r, s) },
          { label: "Verdict", align: "end", render: (r) => verdict(r) },
        ],
      }));
  }

  fill(body,
    section("The figures this course is marked against",
      h("div", { class: "hw-card hw-stack" },
        h("div", { class: "hw-row", style: { alignItems: "flex-start" } },
          h("div", { style: { flex: "1 1 160px" } }, threshold),
          h("div", { style: { flex: "1 1 160px" } }, weeks),
          h("div", { style: { flex: "1 1 160px" } }, perWeek)),
        h("p", { class: "hw-muted", style: { margin: 0 } },
          "Change any of these and everything below recomputes straight away. Nothing is saved until "
          + "you press Save, and the eligibility list keeps using the saved figures until then."),
        h("div", { class: "hw-cardfoot" },
          savedNote,
          h("span", { class: "hw-cardfoot__end" }, save)))),
    figures,
    (state.summary.warnings || []).map((warning) =>
      h("div", { class: "hw-panel", dataset: { tone: "failure" }, role: "alert",
        style: { marginBlockEnd: "var(--hw-space-4)" } },
        h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✕"),
        h("p", { class: "hw-panel__body" }, warning))),
    filters,
    list);
  paint();
  saveButton.title = "Nothing has changed since the last save.";
}

function numberField(label, value, suffix, min, max, onChange) {
  // The label is tied to its input by id: shown on screen but unattached, a screen reader announced
  // three bare number fields (axe-core "label", 2026-09-21).
  const id = uid("figure");
  const input = h("input", { class: "hw-input hw-tnum", type: "number", value: String(value ?? ""),
    min, max, inputmode: "numeric", id });
  input.addEventListener("input", () => onChange(input.value));
  return h("div", { class: "hw-field" },
    h("label", { class: "hw-field__label", for: id }, suffix ? `${label} (${suffix})` : label), input);
}

function hero(glyph, tone, value, label, note) {
  return h("div", {},
    h("p", { class: "hw-headline__label" }, label),
    h("p", { class: "hw-headline__value hw-tnum" },
      tone ? h("span", { class: "hw-figure__glyph", dataset: { tone }, "aria-hidden": "true",
        style: { marginInlineEnd: "var(--hw-space-2)" } }, glyph) : null,
      value),
    h("p", { class: "hw-headline__note" }, note));
}

function needsWords(row, summary) {
  // The student's own classes still to come: on a course with groups, a group that has had fewer
  // practicals so far has more of them left than the course's figure says.
  const left = row.classes_remaining ?? summary.classes_remaining;
  if (row.status === "met") return h("span", { class: "hw-muted" }, "Nothing more");
  if (row.status === "cannot_reach") {
    return h("span", {}, `needs ${row.more_needed ?? 0} more, only ${left} left`);
  }
  if (!left) return h("span", { class: "hw-muted" }, "No classes left");
  return h("span", {}, `${row.more_needed ?? 0} more of the ${left} left`);
}

function verdict(row) {
  const spec = {
    met: ["✓", "Met", "present"],
    on_track: ["✓", "On track", "present"],
    at_risk: ["?", "At risk", "review"],
    below: ["✕", "Below", "absent"],
    cannot_reach: ["✕", "Cannot reach", "absent"],
    all_excused: ["E", "All excused", "excused"],
    no_classes_yet: ["○", "No classes yet", "neutral"],
  }[row.status] || ["?", row.status, "review"];
  return h("span", { class: "hw-pill", dataset: { tone: spec[2] } },
    h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, spec[0]), spec[1]);
}
