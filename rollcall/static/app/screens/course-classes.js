// Screen 14: Classes, the Classes tab of a course. Mockups: PCT201Classesmain.png,
// PCT201Classescancelledonly.png, PCT201Classescancelling.png, PCT201Classesviewerrole.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "14 Classes".
//
// Kept from the mockup: the classes grouped by week with a note per week counted from its own rows,
// a cancelled class struck through with who cancelled it, when and why, and "Counts towards nobody".
//
// Fixed from the mockup: one header component on every tab (screens/course.js), so the figure sits
// above its note rather than being crammed into the figure; marks are drawn, never typed as
// characters, so an encoding fault cannot turn a status into noise; and a week with no class says so
// rather than inventing one.
//
// Changed on 2026-09-23: there is no Create a class. A class is made by Start taking attendance on the
// course, or found in the scans read later ("no need for a create class section since we can start
// attendance for a class"). Classes are grouped by the week of the sheet they sit in, the same rule the
// sheet uses, and each can be moved to another week.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  invalid, actionRow, announce, button, dialog, field, fill, h, longDate, plural, section, setBusy, table,
  toast,
} from "../ui.js";
import { frame } from "./course.js";

const FILTERS = [["all", "All"], ["held", "Held"], ["cancelled", "Cancelled"]];

export default {
  id: "course-classes",
  nav: "courses",
  title: "Classes",
  permission: "register.read",

  async render(view, ctx) {
    const courseId = Number(ctx.params.id);
    const reload = () => this.render(fill(view), ctx);
    const { course, body } = await frame(view, courseId, "classes");
    const sessions = await api.get(`/api/sessions?course_id=${courseId}`);
    draw(body, course, sessions, reload);
  },
};

function draw(body, course, sessions, reload) {
  const state = { filter: "all" };
  const list = h("div");
  const shown = h("p", { class: "hw-muted", role: "status", style: { margin: 0 } });

  const segments = h("div", { class: "hw-toggle", role: "group", "aria-label": "Which classes to show" });
  for (const [value, label] of FILTERS) {
    const count = value === "all" ? sessions.length
      : sessions.filter((s) => (value === "cancelled") === Boolean(s.cancelled_at)).length;
    const btn = h("button", { class: "hw-toggle__button", type: "button",
      dataset: { action: `filter-${value}` }, "aria-pressed": String(state.filter === value) },
      `${label} ${count}`);
    btn.addEventListener("click", () => {
      state.filter = value;
      for (const other of segments.children) other.setAttribute("aria-pressed", String(other === btn));
      paint();
    });
    segments.append(btn);
  }

  function paint() {
    const rows = sessions.filter((s) => state.filter === "all"
      || (state.filter === "cancelled") === Boolean(s.cancelled_at));
    shown.textContent = state.filter === "all"
      ? `Showing all ${plural(sessions.length, "class", "classes")}`
      : `Showing ${rows.length} of ${plural(sessions.length, "class", "classes")}`;
    fill(list, rows.length
      ? weeks(rows, course, reload)
      : h("div", { class: "hw-table-frame" }, h("div", { class: "hw-state" },
        h("span", { class: "hw-state__icon", "aria-hidden": "true" }, "☰"),
        h("h2", { class: "hw-state__heading" },
          state.filter === "cancelled" ? "No class has been cancelled" : "No classes yet"),
        h("p", { class: "hw-state__body" },
          state.filter === "cancelled"
            ? "Cancelled classes appear here with who cancelled them and why."
            : "Classes appear here after you get attendance from the device, or when you create "
              + "one by hand."))));
  }

  fill(body,
    h("div", { class: "hw-row hw-row--between", style: { marginBlockEnd: "var(--hw-space-4)" } },
      segments, shown),
    list);
  paint();
}

/**
 * Grouped by the week of the sheet each class sits in, newest week first, each week's note counted
 * from its own rows. A class outside every week of the sheet is grouped by its calendar week and
 * says so. Grouping by the calendar alone put a class the lecturer took for week 3 under the week of
 * its date, while the sheet showed it in week 3.
 */
function weeks(rows, course, reload) {
  const byWeek = new Map();
  for (const row of rows) {
    const w = row.sheet_week;
    const key = w ? `a${String(w.week_number).padStart(3, "0")}` : `b${weekStart(row.date)}`;
    if (!byWeek.has(key)) {
      byWeek.set(key, { list: [], title: w
        ? `${w.label}${w.starts_on ? `, week of ${longDate(w.starts_on)}` : ""}`
        : `Week of ${longDate(weekStart(row.date))}, not on the sheet` });
    }
    byWeek.get(key).list.push(row);
  }
  const weeksInOrder = [...byWeek.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1));
  // A course with groups (2026-09-29) says who each class was for, and lets it be changed: a class
  // started for the wrong group, or found in the scans and given the wrong one.
  const names = new Map((course.groups || []).map((g) => [g.id, g.name]));
  const grouped = names.size > 0;
  // Plain words on one line: a tag in a narrow column broke "Group B" over two lines at 1366.
  const forColumn = grouped ? [{ label: "For", render: (s) => (s.group_id
    ? h("span", { class: "hw-nowrap" }, names.get(s.group_id) || "A group")
    : h("span", { class: "hw-muted hw-nowrap" }, "Everybody")) }] : [];
  return h("div", { class: "hw-stack" }, ...weeksInOrder.map(([, { list, title }]) => {
    const held = list.filter((s) => !s.cancelled_at).length;
    const cancelled = list.length - held;
    return section(title,
      table({
        caption: `Classes in ${title}`,
        rows: list,
        rowAttrs: (s) => (s.cancelled_at ? { dataset: { struck: "true", dimmed: "true" } } : null),
        columns: [
          { label: "Day", className: "hw-table__struck", render: (s) => longDate(s.date) },
          { label: "Time", className: "hw-table__struck", render: (s) =>
            h("span", { class: "hw-ids" }, s.open ? `from ${s.start_time}, still taking attendance`
              : `${s.start_time} to ${s.end_time}`) },
          ...forColumn,
          { label: "How it was recorded", render: (s) =>
            s.opened_at ? "Taken live" : s.kind === "device" ? "Found from scans" : "Recorded by hand" },
          { label: "", render: (s) => s.cancelled_at
            ? h("div", {},
              h("span", { class: "hw-pill", dataset: { tone: "neutral" } },
                h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "✕"), "Cancelled"),
              h("p", { class: "hw-muted", style: { margin: "var(--hw-space-1) 0 0", fontSize: "var(--hw-text-body)" } },
                // The note is whatever somebody typed, so it is quoted rather than run into the
                // sentence after it: "no reason Counts towards nobody" was on a real screen.
                s.cancel_note
                  ? `"${s.cancel_note}" Counts towards nobody.`
                  : "No reason recorded. Counts towards nobody."))
            : null },
          { label: "", align: "end", render: (s) => actionRow(
            h("a", { class: "hw-link", href: href(`classes/${s.id}`) }, "Open register"),
            button({ label: "Move", permission: "class.manage",
              onClick: () => askToMove(s, course, reload) }),
            grouped && !s.cancelled_at
              ? button({ label: "Change group", permission: "class.manage",
                  onClick: () => askGroup(s, course, reload) })
              : null,
            s.cancelled_at
              ? button({ label: "Restore", permission: "class.manage",
                  onClick: () => restore(s, reload) })
              : button({ label: "Cancel", permission: "class.manage",
                  onClick: () => askToCancel(s, reload) }),
            // On every row, cancelled or not: a class started by mistake this morning holds
            // nothing either, and asking for it only on cancelled ones meant cancelling first for
            // no reason. Disabled with what it holds when it cannot go, which is the backend's
            // own answer carried on the row.
            button({ label: "Delete", variant: "destructive", permission: "class.manage",
              reason: s.can_delete === false ? holdsSentence(s.blocking) : "",
              onClick: () => askToDelete(s, reload) })) },
        ],
      }),
      h("p", { class: "hw-section__help" },
        `${held} of ${plural(list.length, "class", "classes")} held this week`
        + (cancelled ? `, ${cancelled} cancelled` : "")));
  }));
}

const ORDINAL = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"];

// The way back from putting a class in the wrong week when it was started.
async function askToMove(row, course, reload) {
  let choices;
  try {
    // A group's class counts the weeks of that group's sheet, which is where it would land.
    choices = await api.get(`/api/courses/${course.id}/live/weeks`
      + (row.group_id ? `?group_id=${row.group_id}` : ""));
  } catch (error) {
    toast(error instanceof ApiError ? error.message : "The weeks did not load.", "failure");
    return;
  }
  const now = row.sheet_week?.week_number;
  const pick = field({ label: "Week", name: "week", width: "full",
    value: String(now || choices.suggested),
    options: choices.weeks.map((w) => ({ value: String(w.week_number),
      label: `${w.label}${w.starts_on ? ` · from ${longDate(w.starts_on)}` : ""}`
        + `${w.held ? ` · ${plural(w.held, "class", "classes")}` : ""}`
        + `${w.week_number === now ? " · where it is now" : ""}` })) });
  const select = pick.querySelector("select");
  const go = button({ label: "Move it", primary: true, busyLabel: "Moving" });
  const box = dialog({
    title: `Move the class on ${longDate(row.date)}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        "Choose the week of the sheet this class belongs to. Its scans and any corrections stay "
        + "exactly as they are; only the week it is shown in changes."),
      pick),
    actions: [button({ label: "Keep it where it is", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      const placed = await api.put(`/api/sessions/${row.id}/week`, { week_number: Number(select.value) });
      box.close();
      toast(`The class is ${placed.week}'s ${ORDINAL[(placed.position || 1) - 1] || ""} class now.`
        .replace("  ", " "));
      announce(`Moved to ${placed.week}.`);
      reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "The class did not move.", "failure");
    }
  });
}

// Who a class was for. The backend refuses a change that would leave a corrected student off the
// register (a correction is a signed decision), and that refusal is shown as it is.
function askGroup(row, course, reload) {
  const everybody = course.level_students + course.carry_over_students;
  const pick = field({ label: "This class was for", name: "group", width: "medium",
    value: row.group_id ? String(row.group_id) : "",
    options: [{ value: "", label: `Everybody on ${course.code} · ${plural(everybody, "student")}` },
      ...course.groups.map((g) => ({ value: String(g.id), label: `${g.name} · ${plural(g.students, "student")}` }))] });
  const select = pick.querySelector("select");
  const go = button({ label: "Change it", primary: true, busyLabel: "Changing" });
  const box = dialog({
    title: `Who was the class on ${longDate(row.date)} for?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        "Its register becomes that group's, or everybody's on the course. The scans stay exactly as "
        + "they are: only who is expected at it changes, and so who is absent."),
      pick),
    actions: [button({ label: "Keep it as it is", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      const done = await api.put(`/api/sessions/${row.id}/group`,
        { group_id: select.value ? Number(select.value) : null });
      box.close();
      toast(done.group ? `The class is ${done.group}'s now.` : "The class is for everybody on the course now.");
      announce("The class's group is changed.");
      await reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "The class's group did not change.", "failure");
    }
  });
}

function weekStart(iso) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}

function askToCancel(row, reload) {
  const note = field({ label: "Why is the class cancelled?", rows: 3,
    help: "Kept with the class for good, and shown wherever it appears.",
    validate: (v) => (v.trim() ? "" : "Say why the class is cancelled.") });
  const save = button({ label: "Cancel this class", variant: "destructive", busyLabel: "Cancelling" });
  const box = dialog({
    title: `Cancel ${longDate(row.date)}, ${row.start_time} to ${row.end_time}?`,
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        "Its present marks stop counting towards anyone's percentage, and it stops counting towards "
        + "the classes held. The scans themselves are kept, and it can be restored."),
      note),
    actions: [button({ label: "Keep the class", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(note)) return;
    setBusy(save, true);
    try {
      await api.post(`/api/sessions/${row.id}/cancel`, { note: note.value().trim() });
      box.close();
      toast("The class is cancelled.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      note.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}

function holdsSentence(blocking) {
  const what = Object.entries(blocking || {}).map(([name, count]) => `${count} ${name}`).join(", ");
  return `This class has ${what} against it, which the register keeps for good. Cancel it instead: `
    + "that takes it out of every total and leaves that record where it is.";
}

/** The scans in this class's window are not deleted with it, and never were. */
function scansNote(row) {
  const scans = (row.holds || {}).scans || (row.holds || {}).scan || 0;
  if (!scans) return null;
  return h("p", { style: { margin: 0 } },
    `${plural(scans, "scan")} fell inside its window. Every one stays in the register: a scan is `
    + "never deleted, and it belongs to the terminal's log rather than to this class. Another "
    + "class at that time would count them again.");
}

function askToDelete(row, reload) {
  const when = `${longDate(row.date)}, ${row.start_time} to ${row.end_time}`;
  const go = button({ label: "Delete it", variant: "destructive", busyLabel: "Deleting" });
  const box = dialog({
    title: `Delete ${when}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        "The class goes off this list and out of every total, as though it had never been made."),
      scansNote(row),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "A class somebody corrected stays: a correction is a signed decision and the register "
        + "keeps it. Cancelling is what takes a class that was held out of the totals.")),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      await api.del(`/api/sessions/${row.id}`);
      box.close();
      toast("The class is deleted.");
      announce("The class is deleted.");
      await reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}

async function restore(row, reload) {
  try {
    await api.post(`/api/sessions/${row.id}/restore`, {});
    toast("The class is restored and counts again.");
    announce("The class is restored.");
    await reload();
  } catch (error) {
    toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
  }
}
