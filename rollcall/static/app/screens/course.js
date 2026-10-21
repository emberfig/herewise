// Screen 11: Course overview, the frame every course tab is drawn inside.
// Mockups: PCT201Pharmaceuticscoursesheet.png, PCT203Physiologycarry-over.png,
// PCT211Pharmacologynothingheldyet.png, PCT201coursereprestricted.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "11 Course overview".
//
// The tabs are routes, not panels: #/courses/3/sheet is screen 12, /classes is 14, /students is 15,
// /percentages is 17, /eligibility is 18. One header, one set of figures, and the tab decides the
// body, so the header can never disagree with what is under it.
//
// Fixed from the mockup: one dash character everywhere for an empty value, never an em dash and
// never a cross, because a cross means absent; the disabled tabs' reasons sit on one line beneath
// the rule so the tab row keeps its height whatever the role; and the level chip does not wrap.

import { ApiError, api } from "../api.js";
import { go, href } from "../router.js";
import { session } from "../session.js";
import { button, clear, dialog, field, fill, h, plural, setBusy, shortDate, toast } from "../ui.js";

const TABS = [
  { id: "sheet", label: "Sheet", permission: "register.read" },
  // Every class the tab lists as held, whoever it was for: on a course with groups, the number of
  // classes one student was expected at is a different figure, and it is the header's.
  { id: "classes", label: "Classes", permission: "register.read",
    count: (c) => c.figures?.classes_taken ?? c.figures?.classes_held },
  { id: "students", label: "Students", permission: "register.read",
    count: (c) => c.level_students + c.carry_over_students },
  // Groups (2026-09-29): no count until the course is split, so an unsplit course reads as it did.
  { id: "groups", label: "Groups", permission: "register.read", count: (c) => c.groups?.length || null },
  { id: "percentages", label: "Percentages", permission: "register.read" },
  { id: "eligibility", label: "Eligibility", permission: "eligibility.view" },
];

/** Draw the header and the tab row, and hand back the element the tab's own body goes in. */
export async function frame(view, courseId, current, { actions = null, reasons: extra = [] } = {}) {
  const [course, live] = await Promise.all([
    api.get(`/api/courses/${courseId}?with_figures=true`),
    api.get("/api/live").catch(() => ({ open: null })),
  ]);
  const f = course.figures || {};
  const students = course.level_students + course.carry_over_students;
  const held = f.classes_held || 0;

  const body = h("div");
  const reasons = [...extra];
  // Links that change the route, so navigation rather than a tablist: a tablist promises arrow keys
  // and panels, and axe-core failed it for holding links (2026-09-21).
  const tabs = h("nav", { class: "hw-tabs", "aria-label": "This course" });
  for (const tab of TABS) {
    const allowed = session.can(tab.permission);
    const count = tab.count ? tab.count(course) : null;
    const label = count === null || count === undefined ? tab.label : `${tab.label} ${count}`;
    if (allowed) {
      const link = h("a", { class: "hw-tab", href: href(`courses/${courseId}/${tab.id}`),
        dataset: { action: `tab-${tab.id}` } }, label);
      if (tab.id === current) link.setAttribute("aria-current", "page");
      tabs.append(link);
    } else {
      tabs.append(h("span", { class: "hw-tab", "aria-disabled": "true",
        dataset: { action: `tab-${tab.id}` } }, label));
      reasons.push(`${tab.label}: ${session.denial(tab.permission)}`);
    }
  }

  fill(view, h("div", { class: "hw-page hw-page--wide" },
    h("p", { style: { margin: "0 0 var(--hw-space-2)" } },
      h("a", { class: "hw-link", href: href("courses") },
        h("span", { "aria-hidden": "true" }, "← "), "Courses")),
    h("header", { class: "hw-page__head" },
      h("div", { class: "hw-page__titles" },
        h("h1", { class: "hw-page__title" },
          `${course.code}${course.title ? ` ${course.title}` : ""}`),
        h("p", { class: "hw-page__subtitle" },
          `${course.level_name} · ${course.academic_session} session`)),
      h("div", { class: "hw-page__actions" }, takeAttendance(course, live.open))),
    figures(course, f, students, held),
    h("div", { class: "hw-row hw-row--between", style: { alignItems: "flex-end", gap: "var(--hw-space-4)" } },
      tabs, actions ? h("div", { class: "hw-row" }, actions) : null),
    // Beneath the rule, on their own line, so the tab row is the same height for every role.
    reasons.length ? h("p", { class: "hw-reason", style: { maxWidth: "none", marginBlockEnd: "var(--hw-space-4)" } },
      reasons.join(" ")) : null,
    body));
  return { course, body };
}

// The main thing a lecturer does with a course in the room: start taking attendance, let the queue
// scan, end it. Asked for on 2026-09-22. One terminal, so one class at a time: while another course's
// class is open the button stays, disabled, with the reason under it.
function takeAttendance(course, open) {
  if (open && open.course_id === course.id) {
    return h("div", { class: "hw-live-cta" },
      button({ label: "Open the class taking attendance", primary: true, glyph: "◔ ", href: href("live") }),
      h("p", { class: "hw-live-cta__note" },
        `${open.group ? `${open.group} · ` : ""}${open.week ? `${open.week}, class ${open.position} · ` : ""}`
        + `since ${open.opened_at.slice(11, 16)} · ${open.present} of ${open.students} present`));
  }
  const start = button({
    label: "Start taking attendance", primary: true, busyLabel: "Starting", permission: "register.pull",
    align: "end",
    reason: open ? `${open.code}${open.group ? ` ${open.group}` : ""} is taking attendance, since `
      + `${open.opened_at.slice(11, 16)}. End it before starting another.` : "",
    onClick: async () => {
      setBusy(start, true);
      try {
        const choices = await api.get(`/api/courses/${course.id}/live/weeks`);
        setBusy(start, false);
        askWeek(course, choices);
      } catch (error) {
        setBusy(start, false);
        toast(error instanceof ApiError ? error.message : "Attendance did not start.", "failure");
      }
    },
  });
  return start;
}

const ORDINAL = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"];
const EVERYBODY = "everybody";

// Asked for on 2026-09-23: "the terminal should ask if the attendance is in the first week or the
// second week, and continually do that with the other weeks". Every class asks, with the likely week
// chosen already, and says where the class will land before it starts: a level can have more than one
// class in a week, and the sheet's weeks are the course's own, not the calendar's.
//
// A course split into groups (2026-09-29) also asks who the class is for, with nothing chosen: the
// wrong answer marks a whole group absent from a class that was never theirs, so there is no
// default to press through. The weeks follow the answer, because a group's week holds the classes
// that group has had, not the next group's practical.
function askWeek(course, firstChoices) {
  const grouped = (course.groups || []).length > 0;
  let choices = firstChoices;
  const describe = (w) => [
    w.label,
    w.starts_on ? `from ${shortDate(w.starts_on)}` : null,
    w.held ? `${plural(w.held, "class", "classes")} so far` : null,
    w.current ? "this week" : null,
  ].filter(Boolean).join(" · ");
  const options = () => [...choices.weeks.map((w) => ({ value: String(w.week_number), label: describe(w) })),
    // The course may run longer than the sheet was set up for: nobody knows its length up front.
    ...(choices.new_week ? [{ value: String(choices.new_week), label: `WK ${choices.new_week} · a new week` }] : [])];
  const pick = field({ label: "Week", name: "week", width: "full", value: String(choices.suggested),
    options: options() });
  const select = pick.querySelector("select");
  const lands = h("p", { class: "hw-muted", role: "status", style: { margin: 0 } });
  const who = { value: null, name: "" };
  const say = () => {
    const w = choices.weeks.find((x) => String(x.week_number) === select.value);
    if (!w && select.value === String(choices.new_week)) {
      lands.textContent = `This adds WK ${choices.new_week} to the sheet, and the class is its first.`;
      return;
    }
    lands.textContent = w
      ? `This will be ${w.label}'s ${ORDINAL[w.held] || `number ${w.held + 1}`} class`
        + `${who.value && who.value !== EVERYBODY ? ` for ${who.name}` : ""}`
        + (w.held >= w.boxes ? `, so ${w.label} gains a box on the sheet.` : ".")
      : "";
  };
  select.addEventListener("change", say);

  const audience = grouped ? whoChooser(course, async (value, name) => {
    Object.assign(who, { value, name });
    const kept = select.value;
    try {
      choices = await api.get(`/api/courses/${course.id}/live/weeks`
        + (value === EVERYBODY ? "" : `?group_id=${encodeURIComponent(value)}`));
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "The weeks did not load.", "failure");
      return;
    }
    // Arrowing through the choices asks once per step, and an earlier answer can arrive last.
    if (who.value !== value) return;
    // The week chosen stays chosen; the suggestion is only a starting point.
    const next = options();
    fill(select, ...next.map((o) => h("option", { value: o.value }, o.label)));
    select.value = next.some((o) => o.value === kept) ? kept : String(choices.suggested);
    say();
  }) : null;
  say();

  const go_ = button({ label: "Start taking attendance", primary: true, busyLabel: "Starting" });
  const box = dialog({
    // The fieldset's legend asks who; the title names the course, so the question is not read twice.
    title: grouped ? `Start taking attendance for ${course.code}` : "Which week is this class for?",
    body: h("div", { class: "hw-stack hw-stack--tight" },
      grouped ? audience : null,
      h("p", { style: { margin: 0 } },
        `Choose the week of ${course.code}'s sheet this class belongs to. A week can hold more than `
        + "one class; each goes in its own box."),
      pick, lands),
    actions: [button({ label: "Not now", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go_)],
  });
  go_.addEventListener("click", async () => {
    if (grouped && !who.value) {
      audience.showError("Choose who this class is for: one group, or everybody on the course.");
      return;
    }
    setBusy(go_, true);
    try {
      await api.post(`/api/courses/${course.id}/live`, { week_number: Number(select.value),
        ...(grouped ? { group_id: who.value === EVERYBODY ? EVERYBODY : Number(who.value) } : {}) });
      box.close();
      go("live");
    } catch (error) {
      setBusy(go_, false);
      toast(error instanceof ApiError ? error.message : "Attendance did not start.", "failure");
    }
  });
}

/**
 * "Who is this class for?": everybody on the course, or one group, and nothing chosen to begin with.
 * Radio buttons rather than a list, so every answer and how many students it covers is in view before
 * the choice is made. A group with nobody in it is shown and cannot be chosen.
 */
function whoChooser(course, onChoose) {
  const name = `who-${course.id}`;
  const everybody = course.level_students + course.carry_over_students;
  const error = h("p", { class: "hw-field__error", id: `${name}-error`, hidden: true },
    h("span", { "aria-hidden": "true", class: "hw-panel__glyph", text: "✕" }), h("span", {}));
  const row = (value, label, help, disabled = false) => {
    const input = h("input", { type: "radio", name, value, disabled: disabled || null,
      dataset: { action: `who-${value}` } });
    input.addEventListener("change", () => {
      error.hidden = true;
      set.removeAttribute("aria-describedby");
      onChoose(value, label);
    });
    return h("label", { class: "hw-choice" }, input,
      h("span", { class: "hw-stack hw-stack--tight", style: { gap: "2px" } },
        h("span", { class: "hw-choice__label" }, label),
        h("span", { class: "hw-choice__help" }, help)));
  };
  const set = h("fieldset", { class: "hw-fieldset" },
    h("legend", {}, "Who is this class for?"),
    row(EVERYBODY, `Everybody on ${course.code}`, `${plural(everybody, "student")}, a lecture for the whole course`),
    ...course.groups.map((g) => row(String(g.id), g.name,
      g.students ? `${plural(g.students, "student")}, nobody else is expected` : "Nobody is in this group yet",
      !g.students)),
    error);
  set.showError = (message) => {
    error.hidden = false;
    error.lastElementChild.textContent = message;
    set.setAttribute("aria-describedby", error.id);
    set.querySelector("input:not(:disabled)")?.focus();
  };
  return set;
}

function figures(course, f, students, held) {
  const dash = "–";
  const cells = [
    ["Students", String(students),
      `${course.level_students} from ${course.level_name}` +
      (course.carry_over_students ? ` · ${plural(course.carry_over_students, "carry-over student")}`
        : " · no carry-over")],
    ["Classes held", f.planned_classes ? `${held} of ${f.planned_classes}` : String(held),
      // On a course with groups the figure is one student's: the classes for everybody and their
      // own group's. The note says so, and how many were taken across every group.
      [(course.groups || []).length && f.classes_taken !== undefined
        ? `each student's · ${plural(f.classes_taken, "class", "classes")} across the groups` : "",
      // "cancelled" is not a noun: plural() made "2 cancelleds" on a real course header.
      f.cancelled_classes
        ? `${plural(f.cancelled_classes, "class", "classes")} cancelled, not counted` : ""]
        .filter(Boolean).join(" · ")],
    ["Average attendance", held ? `${f.average_percent}%` : dash,
      held ? `pass mark ${f.threshold_percent}%` : "no classes yet"],
    ["Below the pass mark", held ? String(f.below_threshold) : dash,
      held ? `${f.can_still_reach} can still reach it · ${f.cannot_reach} cannot` : "no classes yet"],
  ];
  return h("div", { class: "hw-headline" }, ...cells.map(([label, value, note]) =>
    h("div", {},
      h("p", { class: "hw-headline__label" }, label),
      h("p", { class: "hw-headline__value hw-ids" }, value),
      note ? h("p", { class: "hw-headline__note" }, note) : null)));
}

export const TAB_IDS = TABS.map((t) => t.id);
