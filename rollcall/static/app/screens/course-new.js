// New course. There was no screen here at all: the Courses screen's "New course" button pointed at
// #/courses/new, which matched the course pattern with an id of "new", asked the backend for a
// course called "new" and got a validation error back. The screen then said "Attendance sheet did
// not load. That did not work." A lecturer trying to add their second course met that and nothing
// else (found on a first run, 2026-09-21).
//
// A course belongs to a level and every student of that level joins it, which is the thing worth
// saying before the button rather than after it.

import { ApiError, api } from "../api.js";
import { go, href } from "../router.js";
import { invalid, announce, button, field, fill, h, page, plural, section, setBusy, toast } from "../ui.js";

export default {
  id: "course-new",
  nav: "courses",
  title: "New course",
  permission: "courses.manage",

  async render(view) {
    const host = h("div");
    view.append(host);
    const levels = await api.get("/api/levels");
    const withStudents = levels.filter((l) => l.students);
    draw(host, withStudents.length ? withStudents : levels);
  },
};

function draw(host, levels) {
  const level = field({
    label: "Level",
    options: levels.map((l) => ({ value: l.id,
      label: `${l.name} · ${plural(l.students || 0, "student")}` })),
    help: "Every student on this level joins the course. Carry-over students from other levels are "
      + "added afterwards, on the course's own Students tab.",
  });
  const code = field({
    label: "Course code",
    help: "As the department writes it, such as PCT 201. It heads the attendance sheet and the "
      + "eligibility list.",
    validate: (v) => (v.trim() ? "" : "Give the course its code."),
  });
  const title = field({
    label: "Title",
    help: "Optional. The name of the course, such as Pharmaceutics.",
  });

  const save = button({ label: "Make the course", primary: true, busyLabel: "Making the course" });
  save.addEventListener("click", async () => {
    if (invalid(code)) return;
    setBusy(save, true);
    try {
      const made = await api.post("/api/courses", { level_id: Number(level.value()),
        code: code.value().trim(), title: title.value().trim() || null });
      // No count here: the POST answers with the course, and the next screen shows the figures.
      toast(`${made.code} is made.`);
      announce(`${made.code} is made.`);
      // Straight to the sheet's setup, because a sheet with no week 1 date ticks nothing.
      go(`courses/${made.id}/setup`);
    } catch (error) {
      setBusy(save, false);
      code.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });

  fill(host, page({
    title: "New course",
    subtitle: "A course is what attendance is counted against",
    crumbs: [h("a", { class: "hw-link", href: href("courses") }, "Courses"),
      h("span", { "aria-hidden": "true" }, " › "), "New course"],
    children: [
      section("", h("div", { class: "hw-card hw-stack", style: { maxWidth: "560px" } },
        level, code, title,
        h("div", { class: "hw-cardfoot" },
          h("a", { class: "hw-link", href: href("courses") }, "Go back"),
          h("span", { class: "hw-cardfoot__end" }, save)))),
      h("p", { class: "hw-section__help" },
        "The course gets its own attendance sheet, set up on the next screen: how many weeks, how "
        + "many classes a week, and the date week 1 starts. Nothing is ticked until that date is "
        + "set."),
    ],
  }));
}
