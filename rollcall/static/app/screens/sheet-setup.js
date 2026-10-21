// Screen 13: Sheet setup, with the Week strip. Mockups: Sheetsetup.png, Sheetsetupnotstarted.png,
// Sheetsetupoverlap.png. Fix list: docs/DESIGN-DEVIATIONS.md, "13 Sheet setup".
//
// The thing this screen exists for: a break week reads as a break, not as a week with no classes
// yet, because the second would print a blank column on the sheet.
//
// Fixed from the mockup: the week list is generated from the week 1 date and the total, so weeks
// cannot appear twice; glyphs mark a status or an outcome, not a neutral summary sentence; and the
// empty state says "No week dates yet", which does not read as a contradiction beside a week count.
//
// Weeks can be removed and added (asked for on 2026-09-23: "lecturers don't know the amount of weeks
// they have so make weeks deletable"). A week holding a class keeps its Remove button, disabled, with
// the reason under it; the backend refuses it too. Each week remembers the number it had, so the
// classes in the weeks after a removed one follow them to their new numbers.

import { ApiError, api } from "../api.js";
import { go as go_to, href } from "../router.js";
import {
  keepFocusOn, invalid, announce, button, dialog, fill, field, h, loadingCards, longDate, plural, section,
  setBusy, toast,
} from "../ui.js";
import { frame } from "./course.js";

export default {
  id: "sheet-setup",
  nav: "courses",
  title: "Sheet setup",
  permission: "plan.manage",

  async render(view, ctx) {
    const courseId = Number(ctx.params.id);
    const { course, body } = await frame(view, courseId, "sheet");
    fill(body, loadingCards(2));
    const template = await api.get(`/api/courses/${courseId}/template`);
    draw(body, courseId, template, () => this.render(fill(view), ctx));
  },
};

function draw(body, courseId, template, reload) {
  // A label that is only the default "WK 7" is not kept as typed: it renumbers with its week.
  const isDefault = (label) => /^WK\s*\d+$/i.test(label || "");
  const state = {
    weeks: template.weeks.map((w) => ({ ...w, from_week: w.week_number,
      label: isDefault(w.label) ? "" : w.label })),
    title: template.title || "",
    code: template.course_code || "",
    start: template.week1_start || "",
  };

  const title = field({ label: "Title on the sheet", value: state.title,
    help: "Printed across the top of the paper sheet, for example 200 LEVEL ATTENDANCE.",
    onInput: (e) => { state.title = e.target.value; dirty(); } });
  const code = field({ label: "Course code", value: state.code, ids: true,
    onInput: (e) => { state.code = e.target.value; dirty(); } });
  const start = field({ label: "Week 1 starts on", type: "date", value: state.start, ids: true,
    help: "Nothing is ticked until this is set: without it Herewise cannot tell which week a scan "
      + "belongs to.",
    validate: (v) => (v ? "" : "Set this first."),
    onInput: (e) => { state.start = e.target.value; dirty(); } });

  const strip = h("div");
  const summary = h("p", { class: "hw-muted" });
  const save = button({ label: "Save the sheet", primary: true, disabled: true,
    reason: "Nothing has changed yet.", busyLabel: "Saving" });
  const saveButton = save.matches("button") ? save : save.querySelector("button");
  const savedNote = h("span", { role: "status" });

  function dirty() {
    saveButton.disabled = !state.start;
    saveButton.title = state.start ? "" : "Set the week 1 start date first.";
    fill(savedNote);
    paint();
  }

  function paint() {
    const total = state.weeks.reduce((n, w) => n + w.classes, 0);
    const breaks = state.weeks.filter((w) => w.classes === 0).length;
    // A neutral summary sentence takes no glyph.
    summary.textContent = state.start
      ? `${plural(total, "class", "classes")} across ${plural(state.weeks.length, "week")}`
        + (breaks ? `, with ${plural(breaks, "break week")}` : "")
      : `${plural(state.weeks.length, "week")} set. No week dates yet.`;

    fill(strip, state.weeks.length
      ? h("div", { class: "hw-weeks" }, ...state.weeks.map((week, index) => weekRow(week, index)))
      : h("div", { class: "hw-table-frame" }, h("div", { class: "hw-state" },
        h("span", { class: "hw-state__icon", "aria-hidden": "true" }, "☰"),
        h("h2", { class: "hw-state__heading" }, "No week dates yet"),
        h("p", { class: "hw-state__body" },
          "Set the week 1 start date and generate the weeks, and each one gets its own dates."))));
  }

  function weekRow(week, index) {
    const isBreak = week.classes === 0;
    const number = index + 1;
    const label = h("input", { class: "hw-input", value: week.label || "",
      placeholder: `WK ${number}`, "aria-label": `Label for week ${number}` });
    label.addEventListener("input", () => { state.weeks[index].label = label.value; dirty(); });

    const count = h("span", { class: "hw-tnum", style: { minWidth: "2ch", textAlign: "center" } },
      String(week.classes));
    const stepper = h("div", { class: "hw-row", style: { gap: "var(--hw-space-2)" } },
      h("button", { class: "hw-button", type: "button",
        "aria-label": `One fewer class in week ${number}`,
        onClick: () => step(index, -1, count) }, "−"),
      count,
      h("button", { class: "hw-button", type: "button",
        "aria-label": `One more class in week ${number}`,
        onClick: () => step(index, 1, count) }, "+"));

    const held = week.held || 0;
    const remove = button({ label: "Remove", variant: "quiet", align: "end",
      // Short, because it sits on every week that holds a class; how to free one is said once, under
      // the list.
      reason: held ? `Holds ${plural(held, "class", "classes")}`
        : state.weeks.length === 1 ? "A sheet keeps at least one week." : "",
      onClick: () => {
        state.weeks.splice(index, 1);
        announce(`Week ${number} removed. Save the sheet to keep it.`);
        dirty();
      } });
    remove.querySelector?.("button")?.setAttribute("aria-label", `Remove week ${number}`);
    if (remove.matches?.("button")) remove.setAttribute("aria-label", `Remove week ${number}`);

    return h("div", { class: "hw-weeks__row", dataset: isBreak ? { break: "true" } : null },
      h("span", { class: "hw-weeks__number hw-tnum" }, `Week ${number}`),
      h("span", { class: "hw-weeks__dates hw-nowrap" },
        week.starts_on ? longDate(week.starts_on)
          : h("span", { class: "hw-muted" }, index ? `after week ${index}` : "no date yet")),
      label,
      stepper,
      // A break reads as a break, not as a week with no classes yet.
      isBreak
        ? h("span", { class: "hw-pill", dataset: { tone: "neutral" } },
          h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "–"), "Break week")
        : h("span", { class: "hw-muted" }, plural(week.classes, "class", "classes")),
      remove);
  }

  const addWeek = button({ label: "Add a week", glyph: "+ ",
    onClick: () => {
      if (state.weeks.length >= 52) return;
      state.weeks.push({ classes: 1, starts_on: null, label: "", from_week: null, held: 0 });
      announce(`Week ${state.weeks.length} added. Save the sheet to keep it.`);
      dirty();
    } });

  function step(index, delta, count) {
    state.weeks[index].classes = Math.max(0, Math.min(7, state.weeks[index].classes + delta));
    count.textContent = String(state.weeks[index].classes);
    dirty();
  }

  const generate = button({ label: "Generate the weeks", busyLabel: "Generating",
    onClick: async () => {
      const count = Number(window.prompt("How many weeks does this course run for?",
        String(state.weeks.length || 12)));
      if (!count || count < 1 || count > 52) return;
      setBusy(generate, true);
      try {
        const result = await api.post(`/api/templates/${template.id}/weeks/generate`,
          { weeks: count, classes_per_week: 1, week1_start: state.start || null });
        state.weeks = result.weeks.map((w) => ({ ...w }));
        toast(`${plural(count, "week")} generated.`);
        dirty();
      } catch (error) {
        toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
      } finally {
        setBusy(generate, false);
      }
    } });

  saveButton.addEventListener("click", async () => {
    if (invalid(start)) return;
    setBusy(save, true);
    try {
      await api.patch(`/api/templates/${template.id}`, {
        title: state.title || null, course_code: state.code || null, week1_start: state.start });
      await api.put(`/api/templates/${template.id}/weeks`, {
        weeks: state.weeks.map((w) => ({ classes: w.classes, starts_on: w.starts_on || null,
          label: w.label || null, from_week: w.from_week ?? null })) });
      // What was saved is the list from now on: every week has the number it was saved with.
      state.weeks = state.weeks.map((w, i) => ({ ...w, from_week: i + 1 }));
      saveButton.disabled = true;
      saveButton.title = "Nothing has changed since the last save.";
      fill(savedNote, h("span", { class: "hw-confirmation" },
        h("span", { class: "hw-confirmation__glyph", "aria-hidden": "true" }, "✓"),
        "Saved. The sheet uses these weeks now."));
      announce("The sheet is saved.");
      keepFocusOn(savedNote);
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "That did not save.", "failure");
    } finally {
      setBusy(save, false);
    }
  });

  fill(body,
    section("The sheet itself", h("div", { class: "hw-card hw-stack" },
      h("div", { class: "hw-row", style: { alignItems: "flex-start" } },
        h("div", { style: { flex: "1 1 280px" } }, title),
        h("div", { style: { flex: "1 1 180px" } }, code)),
      start)),
    section("The weeks",
      h("div", { class: "hw-row hw-row--between", style: { marginBlockEnd: "var(--hw-space-3)" } },
        summary, generate),
      strip,
      h("p", { style: { margin: "var(--hw-space-3) 0 0" } }, addWeek),
      h("p", { class: "hw-section__help" },
        "A week with no classes is a break: it prints as a gap with its dates, not as a blank column "
        + "waiting to be filled. A week that holds a class cannot be removed until its classes are "
        + "moved to another week, from the Classes tab. Not sure how many weeks the course runs? "
        + "Remove the ones you do not need at the end of term, or add one when the course runs "
        + "longer; a class can also be started in a new week.")),
    h("div", { class: "hw-cardfoot" },
      savedNote,
      h("span", { class: "hw-cardfoot__end" }, save)),
    deleteSection(courseId, template));
  paint();
}

// -- getting rid of a course -----------------------------------------------------------------------
//
// Asked for on a second run: a course made by mistake with no way to be rid of it. It lives at the
// foot of this screen, which is the course's own settings, and it asks the backend what the course
// holds before it offers anything, so the button is never a guess.

function deleteSection(courseId, template) {
  const host = h("div");
  const code = template.course_code || "this course";
  api.get(`/api/courses/${courseId}/holds`).then((held) => {
    // Only a signed decision stops it. Scans are counted and said out loud, because they are
    // never deleted by this and naming them as a reason was untrue (reported 2026-09-22).
    const stops = Object.entries(held.blocking || {})
      .map(([name, count]) => `${count} ${name}`).join(", ");
    const scans = (held.holds || {}).scans || (held.holds || {}).scan || 0;
    const go = button({
      label: "Delete this course",
      variant: "destructive",
      permission: "courses.manage",
      reason: held.can_delete ? ""
        : `${code} has ${stops} against it, which the register keeps for good.`,
      onClick: () => deleteDialog(courseId, code),
    });
    fill(host, section("Getting rid of this course",
      h("div", { class: "hw-card hw-stack hw-stack--tight" },
        h("p", { style: { margin: 0 } },
          held.can_delete
            ? "Its sheet, its plan, who is on it and its classes go with it. The students stay, "
              + "and so does every scan: a scan belongs to the terminal's log, not to a course."
            : "A correction, a correction request or an excused absence is somebody's signed "
              + "decision, and the register keeps those for good. Take the students off this "
              + "course instead and it stops collecting anything new, or start a fresh academic "
              + "session if this register was only being tried out."),
        held.can_delete && scans
          ? h("p", { class: "hw-muted", style: { margin: 0 } },
            `${plural(scans, "scan")} fell inside its classes and will still be in the register `
            + "afterwards, counting towards whatever class covers their time.")
          : null,
        h("div", {}, go))));
  }).catch(() => fill(host));
  return host;
}

function deleteDialog(courseId, code) {
  const go = button({ label: "Delete it", variant: "destructive", busyLabel: "Deleting" });
  const box = dialog({
    title: `Delete ${code}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        "The course, its attendance sheet, its plan, who is on it and any classes that recorded "
        + "nothing are removed. The students themselves stay, with their device IDs and their "
        + "fingerprints."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "If anything has been recorded against it since this screen loaded, Herewise will refuse "
        + "and say what it holds.")),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      await api.del(`/api/courses/${courseId}`);
      box.close();
      toast(`${code} is deleted.`);
      announce("The course is deleted.");
      go_to("courses");
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}
