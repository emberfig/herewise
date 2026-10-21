// Screen 10: Courses. Mockups: CoursesCards.png, CoursesTable.png, CoursesNocourses.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "10 Courses".
// Contract: GET /api/courses?with_figures=true.
//
// Kept from the mockup: the week strip whose filled squares are counted from the real figures, the
// cards and table views with a toggle, and the dash rather than a cross where nothing was measured.
//
// Fixed from the mockup: the two-column card grid, where every card's footer link row had escaped
// into the right-hand column leaving the right half of the screen dead. It is a plain CSS grid
// here, two columns above 1200px and one below, with the footer inside the card it belongs to.
// The mockup's student counts are also not copied: every course of a level holds all of that
// level's students plus its carry-over students, so the figures come from the contract.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import { announce, button, clear, dialog, emptyState, errorState, fill, h, loadingCards,
  page, plural, section, setBusy, table, toast } from "../ui.js";

const VIEW_KEY = "hw-courses-view";

export default {
  id: "courses",
  title: "Courses",
  permission: "register.read",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    // Deleting a course from this screen redraws it, which is simpler than teaching the table and
    // the cards to take a row out of themselves and keep their figures honest.
    const again = () => this.render(fill(view), ctx);
    window.removeEventListener("hw-courses-changed", this._again);
    this._again = again;
    window.addEventListener("hw-courses-changed", again, { once: true });
    host.append(page({ title: "Courses", children: [loadingCards(4)] }));

    let rows;
    try {
      rows = await api.get("/api/courses?with_figures=true");
    } catch (error) {
      if (error instanceof ApiError && error.signedOut) throw error;
      fill(host, page({
        title: "Courses",
        children: [errorState({ heading: "The courses did not load.",
          body: error instanceof ApiError ? error.message : undefined,
          onRetry: () => this.render(view, {}) })],
      }));
      return;
    }
    draw(host, rows);
  },
};

function draw(host, rows) {
  const state = { filter: "", view: localStorage.getItem(VIEW_KEY) === "table" ? "table" : "cards" };
  const body = h("div");

  const filter = h("input", { class: "hw-input", type: "search", id: "courses-filter",
    placeholder: "Find a course", autocomplete: "off", "aria-label": "Find a course" });
  filter.addEventListener("input", () => { state.filter = filter.value; paint(); });

  const count = h("span", { class: "hw-muted", role: "status" });
  const toggle = h("div", { class: "hw-toggle", role: "group", "aria-label": "How to show the courses" });
  for (const name of ["cards", "table"]) {
    const btn = h("button", { class: "hw-toggle__button", type: "button",
      dataset: { action: `view-${name}` }, "aria-pressed": String(state.view === name) },
      name === "cards" ? "Cards" : "Table");
    btn.addEventListener("click", () => {
      state.view = name;
      localStorage.setItem(VIEW_KEY, name);
      for (const other of toggle.children) other.setAttribute("aria-pressed", String(other === btn));
      paint();
    });
    toggle.append(btn);
  }

  function shown() {
    const q = state.filter.trim().toLowerCase();
    return !q ? rows : rows.filter((c) =>
      `${c.code} ${c.title || ""} ${c.level_name}`.toLowerCase().includes(q));
  }

  function paint() {
    const list = shown();
    count.textContent = state.filter.trim()
      ? `${list.length} of ${plural(rows.length, "course")}`
      : plural(rows.length, "course");
    fill(body, list.length ? (state.view === "cards" ? cards(list) : asTable(list))
      : emptyState({ icon: "⌕", heading: `No course matches "${state.filter.trim()}"`,
        body: "Check the spelling, or clear the box to see them all." }));
  }

  const academic = rows[0]?.academic_session || "";
  fill(host, page({
    title: "Courses",
    subtitle: rows.length
      ? [academic && `${academic} session`, plural(rows.length, "course")].filter(Boolean).join(" · ")
      : "",
    actions: rows.length ? button({ label: "New course", primary: true, permission: "courses.manage",
      href: href("courses/new"), align: "end" }) : null,
    children: rows.length
      ? [h("div", { class: "hw-row hw-row--between", style: { marginBlockEnd: "var(--hw-space-4)" } },
          h("div", { style: { flex: "0 1 380px" } }, filter),
          h("div", { class: "hw-row" }, count, toggle)),
        body]
      : [noCourses()],
  }));
  if (rows.length) paint();
}

function noCourses() {
  return h("div", { class: "hw-table-frame" }, emptyState({
    icon: "☰",
    heading: "No courses yet",
    // Importing a roster used to make a course named after the level, which nobody wanted: five
    // levels imported made five courses (2026-09-24). A course is made here, with its real code.
    body: "Make one for each course you teach, with its real code. Everybody on its level joins it, "
      + "and so does anybody imported into that level later.",
    action: button({ label: "New course", primary: true, permission: "courses.manage",
      href: href("courses/new") }),
  }));
}

// -- the cards ---------------------------------------------------------------------------------

function cards(rows) {
  return h("div", { class: "hw-cards" }, ...rows.map(card));
}

function card(course) {
  const f = course.figures || {};
  const students = course.level_students + course.carry_over_students;
  const never = !f.classes_held;

  const figures = never
    ? h("p", { class: "hw-muted", style: { margin: 0 } },
      f.planned_classes
        ? `No classes held yet. The sheet is set up for ${plural(f.planned_classes, "class", "classes")}.`
        : "No classes held yet, and the sheet has no start date. Set it up to start ticking.")
    : h("div", { class: "hw-figures" },
      figure("✓", "present", `${f.average_percent}%`, "average attendance"),
      figure("✓", "present", String(f.last_class ? f.last_class.present : 0), "present at the last class"),
      f.below_threshold
        ? figure("✕", "absent", String(f.below_threshold), "below the pass mark")
        : figure("✓", "present", "0", "below the pass mark"));

  return h("article", { class: "hw-card hw-stack hw-stack--tight" },
    h("h3", { style: { margin: 0, fontSize: "var(--hw-text-section)" } },
      h("a", { class: "hw-card__link", href: href(`courses/${course.id}/sheet`) },
        h("b", {}, course.code), " ", h("span", { class: "hw-muted" }, course.title || ""))),
    h("p", { class: "hw-muted", style: { margin: 0 } },
      `${course.level_name} · ${plural(students, "student")} · `
      + `${course.carry_over_students} carry-over`),
    f.unassigned_classes
      ? h("p", { style: { margin: 0 } },
        h("span", { class: "hw-pill", dataset: { tone: "review" } },
          h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "?"),
          plural(f.unassigned_classes, "class", "classes") + " unassigned"))
      : null,
    never ? null : weekStrip(f),
    never ? null : h("p", { class: "hw-muted", style: { margin: 0 } },
      `${f.classes_held} of ${f.planned_classes} classes held`
      + (f.cancelled_classes ? `, ${f.cancelled_classes} cancelled` : "")),
    figures,
    h("div", { class: "hw-card__foot hw-row hw-row--between" },
      h("span", { class: "hw-row", style: { gap: "var(--hw-space-3)" } },
        tabLink(course, "sheet", "Sheet"), tabLink(course, "classes", "Classes"),
        tabLink(course, "students", "Students"), tabLink(course, "eligibility", "Eligibility")),
      deleteButton(course)));
}

function tabLink(course, tab, label) {
  return h("a", { class: "hw-link", href: href(`courses/${course.id}/${tab}`) }, label);
}

function figure(glyph, tone, value, label) {
  return h("div", {},
    h("p", { class: "hw-figure", style: { margin: 0 } },
      h("span", { class: "hw-figure__glyph", dataset: { tone }, "aria-hidden": "true" }, glyph),
      h("span", { class: "hw-ids" }, value)),
    h("p", { class: "hw-muted", style: { margin: 0, fontSize: "var(--hw-text-body)" } }, label));
}

/** One square per planned class, filled for the ones held. The figures are counted, never drawn. */
function weekStrip(f) {
  const strip = h("p", { class: "hw-strip", "aria-hidden": "true" });
  for (let i = 0; i < f.planned_classes; i += 1) {
    strip.append(h("span", { class: "hw-strip__box", dataset: { state: i < f.classes_held ? "held" : "todo" } }));
  }
  return strip;
}

// -- the table ---------------------------------------------------------------------------------

function asTable(rows) {
  return table({
    caption: "Courses",
    columns: [
      { label: "Course", render: (c) => h("span", {},
        h("b", { class: "hw-table__code" }, c.code), " ", h("span", { class: "hw-muted" }, c.title || "")) },
      { label: "Level", render: (c) => c.level_name },
      { label: "Students", align: "end", render: (c) =>
        h("span", { class: "hw-ids" }, String(c.level_students + c.carry_over_students)) },
      { label: "Carry-over", align: "end", render: (c) => h("span", { class: "hw-ids" }, String(c.carry_over_students)) },
      { label: "Classes held", align: "end", render: (c) => h("span", { class: "hw-ids" },
        c.figures ? `${c.figures.classes_held} of ${c.figures.planned_classes}` : "–") },
      // A dash where nothing was measured, never a cross: a cross means absent.
      { label: "Average", align: "end", render: (c) => !c.figures || !c.figures.classes_held
        ? h("span", { class: "hw-muted" }, "–")
        : h("span", { class: "hw-ids" }, `${c.figures.average_percent}%`) },
      { label: "Below the pass mark", align: "end", render: (c) => {
        if (!c.figures || !c.figures.classes_held) return h("span", { class: "hw-muted" }, "–");
        if (!c.figures.below_threshold) return h("span", { class: "hw-muted hw-ids" }, "0");
        return h("span", { style: { color: "var(--hw-absent)" } },
          h("span", { "aria-hidden": "true" }, "✕ "), h("span", { class: "hw-ids" }, String(c.figures.below_threshold)));
      } },
      // Deleting a course was only at the foot of its Sheet setup, which is not where anybody
      // looked for it (asked for again on a second run, 2026-09-22). It is on the row the course
      // is on, disabled with what it holds when it cannot go.
      { label: "", align: "end", render: (c) => deleteButton(c) },
    ],
    rows,
    rowHref: (c) => href(`courses/${c.id}/sheet`),
  });
}

// -- getting rid of a course ---------------------------------------------------------------------

function deleteButton(course) {
  // Only a signed decision stops it, and only that is named: saying "9 scans against it,
  // attendance that has been recorded is never deleted" implied the scans would go, which they
  // never do, and left somebody unable to be rid of a course for a reason that was not true
  // (reported 2026-09-22).
  const stops = Object.entries(course.blocking || {})
    .map(([name, count]) => `${count} ${name}`).join(", ");
  return button({
    label: "Delete",
    variant: "destructive",
    permission: "courses.manage",
    reason: course.can_delete === false
      ? `${course.code} has ${stops} against it, which the register keeps for good. Its Sheet `
        + "setup says what to do instead."
      : "",
    onClick: () => deleteDialog(course),
  });
}

/** What happens to the scans, which is nothing: they are never deleted and never were. */
function scansNote(course) {
  const scans = (course.holds || {}).scans || (course.holds || {}).scan || 0;
  if (!scans) return null;
  return h("p", { style: { margin: 0 } },
    `${plural(scans, "scan")} fell inside its classes. Every one of them stays in the register: a `
    + "scan is never deleted, and it was never tied to this course. What goes is the classes that "
    + "counted them.");
}

function deleteDialog(course) {
  const go = button({ label: "Delete it", variant: "destructive", busyLabel: "Deleting" });
  const box = dialog({
    title: `Delete ${course.code}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        "The course, its attendance sheet, its plan, who is on it and its classes are removed. The "
        + "students themselves stay, with their device IDs and their fingerprints."),
      scansNote(course),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "If somebody records a correction against it between now and pressing this, Herewise will "
        + "refuse and say so.")),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      await api.del(`/api/courses/${course.id}`);
      box.close();
      toast(`${course.code} is deleted.`);
      announce("The course is deleted.");
      window.dispatchEvent(new CustomEvent("hw-courses-changed"));
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}
