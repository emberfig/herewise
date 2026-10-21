// Screen 15 Course students and screen 16 Add carry-over students.
// Mockups: PCT203Students.png, PCT203Physiologycarry-over.png, PCT203Removedshown.png,
// PCT203Removingstudent.png, Addcarry-overstudents*.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "15 Course students" and "16 Add carry-over students".
//
// Kept from the mockup: the removed student struck through under a "Removed" toggle while every
// count stays where it was, and the remove panel stating what is kept.
//
// Fixed from the mockups:
//   a removed student's "on the device" cell shows their real terminal state, because removing
//     someone from a course does not touch the terminal;
//   one link style for the way back, the same on every tab;
//   after adding, the pasted list goes and "Add more" starts a new one: re-running a preview against
//     a course that has just changed would be answering a stale question;
//   one dash character for an empty value, never an em dash.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  invalid, matricText,
  announce, button, dialog, field, fill, h, longDate, plural, section, setBusy, setReason,
  table, toast,
} from "../ui.js";
import { frame } from "./course.js";

export default {
  id: "course-students",
  nav: "courses",
  title: "Course students",
  permission: "register.read",

  async render(view, ctx) {
    const courseId = Number(ctx.params.id);
    const reload = () => this.render(fill(view), ctx);
    // "Add students", not "Add carry-over students": the backend has always created a student it
    // has never seen, and the name hid that from somebody wanting to add one person by hand
    // (reported on a second run, 2026-09-22).
    const add = button({ label: "Add students", primary: true, permission: "courses.manage",
      onClick: () => addDialog(courseId, reload) });
    const { course, body } = await frame(view, courseId, "students", { actions: [add] });
    const students = await api.get(`/api/courses/${courseId}/students?include_removed=true`);
    draw(body, course, students, reload);
  },
};

function draw(body, course, students, reload) {
  const live = students.filter((s) => !s.removed_at);
  const removed = students.filter((s) => s.removed_at);
  const home = live.filter((s) => s.kind !== "carry_over");
  const carry = live.filter((s) => s.kind === "carry_over");
  const state = { showRemoved: false };
  const list = h("div");

  // The label is the target, a full control's height and padded before the box: the box alone is
  // 13px, under the 24px floor (check_layout.mjs, courses/1/students at every width, 2026-09-27).
  const toggle = h("label", { class: "hw-row", style: { gap: "var(--hw-space-2)",
    minHeight: "var(--hw-target-min)", paddingInlineStart: "var(--hw-space-2)", cursor: "pointer" } },
    h("input", { type: "checkbox" }),
    h("span", {}, `Show removed (${removed.length})`));
  toggle.firstElementChild.addEventListener("change", (event) => {
    state.showRemoved = event.target.checked;
    paint();
  });

  function paint() {
    fill(list,
      group("From the level", home, course, reload),
      carry.length
        ? group("Carry-over students", carry, course, reload,
          "Students from another level taking this course. They keep their own level and their own "
          + "device ID.")
        : null,
      state.showRemoved && removed.length
        ? group("Removed", removed, course, reload,
          "Removed from this course only. They are left out of every class on it, earlier ones too, "
          + "and nothing was taken off the device.")
        : null);
  }

  fill(body,
    h("div", { class: "hw-row hw-row--between", style: { marginBlockEnd: "var(--hw-space-4)" } },
      h("p", { class: "hw-muted", style: { margin: 0 } },
        `${plural(live.length, "student")} on this course`
        + (removed.length ? ` · ${removed.length} removed` : "")),
      removed.length ? toggle : null),
    list);
  paint();
}

function group(title, rows, course, reload, note = "") {
  return section(title,
    note ? h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-3)" } }, note) : null,
    table({
      caption: title,
      rows,
      limit: 25,
      what: "student",
      rowAttrs: (s) => (s.removed_at ? { dataset: { struck: "true", dimmed: "true" } } : null),
      columns: [
        { label: "Matric no.", className: "hw-table__struck", render: (s) =>
          h("a", { class: "hw-link hw-ids", href: href(`students/${s.person_id}`) }, matricText(s.matric_no)) },
        { label: "Name", className: "hw-table__struck", render: (s) =>
          `${s.surname} ${s.other_names}`.trim() },
        { label: "Level", render: (s) => h("span", {}, `${s.level} Level`,
          s.kind === "carry_over" ? h("span", { class: "hw-tag" }, "carry-over") : null) },
        { label: "Device ID", align: "end", render: (s) =>
          h("span", { class: "hw-ids" }, String(s.device_user_id)) },
        // Removing someone from a course does not touch the terminal, so this is their real state.
        { label: "On the device", align: "end", render: (s) => s.on_device
          ? h("span", { style: { color: "var(--hw-present)" } },
            h("span", { "aria-hidden": "true" }, "✓ "), "Yes")
          : h("span", { class: "hw-muted" },
            h("span", { "aria-hidden": "true" }, "○ "), "Not yet") },
        { label: "", align: "end", render: (s) => s.removed_at
          ? h("span", { class: "hw-muted" }, `Removed ${longDate(s.removed_at.slice(0, 10))}`)
          : button({ label: "Remove", permission: "courses.manage",
              onClick: () => removeDialog(course, s, reload) }) },
      ],
    }));
}

export function removeDialog(course, student, reload) {
  const note = field({ label: "Why are they being removed?", rows: 3,
    help: "Kept with the course for good.",
    validate: (v) => (v.trim() ? "" : "Say why they are being removed.") });
  const save = button({ label: "Remove from this course", variant: "destructive", busyLabel: "Removing" });
  const box = dialog({
    title: `Remove ${`${student.surname} ${student.other_names}`.trim()} from ${course.code}?`,
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        "They come off this course's register, sheet and eligibility list, for the classes "
        + "already held as well as the ones to come. Their scans are kept."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        `Nothing is removed from the device, and they stay on ${student.level ? `${student.level} Level` : "their level"}. `
        + "Add students puts them back."),
      note),
    actions: [button({ label: "Keep them", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(note)) return;
    setBusy(save, true);
    try {
      await api.post(`/api/courses/${course.id}/students/${student.person_id}/remove`,
        { note: note.value().trim() });
      box.close();
      toast("They are off this course from today.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      note.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}

// -- screen 16 ----------------------------------------------------------------------------------

function addDialog(courseId, reload) {
  // Two ways in, because two things were being asked for with one box: a whole list pasted from a
  // spreadsheet, and one student typed in by hand. The paste box did both and looked like neither.
  const state = { how: "one", plan: null };

  const matric = field({ label: "Matric number", width: "medium",
    validate: (v) => (v.trim() ? "" : "A matric number is how a student is recognised."),
    onInput: () => forget() });
  const name = field({ label: "Full name", width: "medium",
    help: "Surname first, the way the roster writes it: OKAFOR Emeka Chidi.",
    onInput: () => forget() });
  const level = field({ label: "Level", type: "number", width: "short",
    help: "Only used when this student is new to Herewise. They keep their own level and their "
      + "own device ID.",
    onInput: () => forget() });
  const paste = field({ label: "Matric numbers", rows: 6, width: "full",
    help: "One per line. A name and a level after a comma are used when the student is new: "
      + "PCT/23/0041, OKAFOR Emeka, 300",
    onInput: () => forget() });

  const ways = h("div", { class: "hw-toggle", role: "group", "aria-label": "How to add students" });
  for (const [value, label] of [["one", "One student"], ["list", "A list"]]) {
    const tab = h("button", { class: "hw-toggle__button", type: "button",
      dataset: { action: `how-${value}` }, "aria-pressed": String(state.how === value) }, label);
    tab.addEventListener("click", () => {
      state.how = value;
      for (const other of ways.children) {
        other.setAttribute("aria-pressed", String(other.dataset.action === `how-${value}`));
      }
      one.hidden = value !== "one";
      many.hidden = value !== "list";
      forget();
    });
    ways.append(tab);
  }
  const one = h("div", { class: "hw-stack" }, matric, name, level);
  const many = h("div", { hidden: true }, paste);

  const result = h("div");
  const preview = button({ label: "Preview", busyLabel: "Reading" });
  const commit = button({ label: "Add students", primary: true, disabled: true,
    reason: "Preview first, so you can see what it would do." });
  const commitButton = commit.matches("button") ? commit : commit.querySelector("button");

  function forget() {
    state.plan = null;
    fill(result);
    commitButton.disabled = true;
    setReason(commit, "Preview first, so you can see what it would do.");
  }

  const box = dialog({
    title: "Add students to this course",
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        "Anybody can be added: a student from another level taking this course, or one Herewise "
        + "has never seen, who is created in their own level's block of device IDs."),
      ways, one, many, h("p", { style: { margin: 0 } }, preview), result),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, commit)],
  });

  function entries() {
    if (state.how === "one") {
      return [{ matric_no: matric.value().trim(), name: name.value().trim() || null,
                level: level.value().trim() || null }];
    }
    return paste.value().split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
      const [matric_no, person, year] = line.split(",").map((part) => part.trim());
      return { matric_no, name: person || null, level: year || null };
    });
  }

  preview.addEventListener("click", async () => {
    if (state.how === "one" && invalid(matric)) return;
    setBusy(preview, true);
    try {
      state.plan = await api.post(`/api/courses/${courseId}/students/preview`, { entries: entries() });
      fill(result, planPanel(state.plan));
      const joining = state.plan.enrol + state.plan.create;
      commitButton.disabled = !state.plan.can_commit;
      commitButton.textContent = joining ? `Add ${plural(joining, "student")}` : "Add students";
      setReason(commit, state.plan.can_commit ? "" : (state.plan.errors[0] || "Nothing to add."));
    } catch (error) {
      fill(result, h("p", { class: "hw-field__error" },
        h("span", { "aria-hidden": "true" }, "\u2715"),
        h("span", {}, error instanceof ApiError ? error.message : "That could not be read.")));
    } finally {
      setBusy(preview, false);
    }
  });

  commitButton.addEventListener("click", async () => {
    setBusy(commit, true);
    try {
      await api.post(`/api/courses/${courseId}/students`, { entries: entries() });
      box.close();
      toast("They are on the course, and on its register from today.");
      announce("Students added.");
      await reload();
    } catch (error) {
      setBusy(commit, false);
      fill(result, h("p", { class: "hw-field__error" },
        h("span", { "aria-hidden": "true" }, "\u2715"),
        h("span", {}, error instanceof ApiError ? error.message : "That did not save.")));
    }
  });
}

function planPanel(plan) {
  const rows = plan.entries || [];
  const counts = {};
  for (const row of rows) counts[row.action] = (counts[row.action] || 0) + 1;
  const words = Object.entries(counts).map(([action, n]) => `${n} ${WORDS[action] || action}`);
  return h("div", { class: "hw-stack hw-stack--tight" },
    h("p", { class: "hw-panel", dataset: { tone: rows.length ? "quiet" : "failure" },
      style: { margin: 0 } },
      h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, rows.length ? "i" : "✕"),
      h("span", {}, rows.length ? words.join(", ") : "Nothing to add.")),
    table({
      caption: "What this list would do",
      density: "compact",
      rows,
      columns: [
        { label: "Matric no.", render: (r) => h("span", { class: "hw-ids" }, matricText(r.matric_no)) },
        { label: "Name", render: (r) => r.name || h("span", { class: "hw-muted" }, "–") },
        { label: "Device ID", align: "end", render: (r) => r.device_user_id
          ? h("span", { class: "hw-ids" }, String(r.device_user_id))
          : h("span", { class: "hw-muted" }, "–") },
        { label: "What happens", render: (r) => (r.issues && r.issues.length)
          ? (r.issues || []).join(" ")
          : WORDS[r.action] || r.action },
      ],
    }));
}

// The backend's own action names (courses.carry_over_plan), in the words a lecturer reads.
const WORDS = {
  create: "new to Herewise",
  enrol: "joining this course",
  restore: "put back on this course",
  already_on_course: "already on it",
  skip: "refused",
};
