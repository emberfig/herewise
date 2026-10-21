// Screen 7: Class register. Mockups: Classregisterpresentfilter.png, Classregistercancelledclass.png,
// Classregisternotonacourse.png, Classregisterrequestonly.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "7 Class register". Contract: GET /api/sessions/{id}/register.
//
// Kept from the mockup: a corrected mark says who corrected it and an excused one says its category
// and dates, beneath the pill, so neither can be mistaken for a plain scan while settling a dispute.
//
// Fixed from the mockup:
//   every pill carries its glyph, Present and Absent included, not only Excused;
//   the filter actually filters, so a "present" filter can never show an absent row (the standing
//     rule added after three screens showed the same fault: displayed state is derived, never written);
//   Cancel this class is gated on class.manage, not on the screen's read permission;
//   the footnote about the correction drawer is not shown on a cancelled class, where it is untrue.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import { openDrawer } from "../../components/hw-drawer.js";
import { invalid, matricText, announce, button, clear, dialog, field, fill, h, loadingTable, longDate, plural, setBusy, shortDate, table, toast } from "../ui.js";

const FILTERS = [
  { id: "present", label: "present", glyph: "✓", tone: "present",
    keep: (s) => s.status === "present" || s.status === "marked_present" },
  { id: "absent", label: "absent", glyph: "✕", tone: "absent",
    keep: (s) => s.status === "absent" || s.status === "marked_absent" },
  { id: "excused", label: "excused", glyph: "E", tone: "excused", keep: (s) => s.status === "excused" },
  // Only while a class is taking attendance: nobody is absent until it is ended, only not yet.
  { id: "waiting", label: "not yet", glyph: "○", tone: "neutral", onlyOpen: true,
    keep: (s) => s.status === "waiting" },
  { id: "all", label: "on the register", glyph: "", tone: "neutral", keep: () => true },
];

export default {
  id: "class-register",
  nav: "courses",
  title: "Class register",
  permission: "register.read",

  async render(view, ctx) {
    const sessionId = Number(ctx.params.id);
    const host = h("div", { class: "hw-page hw-page--wide" },
      loadingTable(["S/N", "Matric no.", "Full name", "Status", "Scanned at"]));
    view.append(host);
    const data = await api.get(`/api/sessions/${sessionId}/register`);
    // fill(view) first: this used to append a second copy of the page below the first, so after a
    // cancel the page on screen still showed the class as it was (reported 2026-09-23).
    const reload = () => {
      ctx.shell?.refresh?.();
      return this.render(fill(view), ctx);
    };
    const screen = draw(host, data, sessionId, reload);
    if (data.open) follow(view, host, sessionId, screen, reload);
  },
};

// -- a class still taking attendance -------------------------------------------------------------
//
// Asked for on 2026-09-23: the register "should also update here when students are using their
// fingerprints to check in". Somebody who can take attendance reads the terminal, exactly as the
// Taking attendance screen does; anybody else sees what has been read so far. Updated in place, so a
// search or a filter survives each look, and redrawn whole once the class ends.

const FOLLOW_MS = 2500;

function follow(view, host, sessionId, screen, reload) {
  let stopped = false;
  let timer = null;
  view.addEventListener("hw-screen-left", () => { stopped = true; clearTimeout(timer); }, { once: true });
  const reads = session.can("register.pull");
  const look = async () => {
    if (stopped || !host.isConnected) return;
    try {
      const fresh = reads
        ? (await api.post(`/api/live/${sessionId}/refresh`, {})).register
        : await api.get(`/api/sessions/${sessionId}/register`);
      if (stopped || !host.isConnected) return;
      if (!fresh.open) {
        stopped = true;
        await reload();
        return;
      }
      screen.update(fresh);
    } catch {
      // A missed look is not worth a message: the next one comes in a moment.
    }
    if (!stopped) timer = setTimeout(look, FOLLOW_MS);
  };
  timer = setTimeout(look, FOLLOW_MS);
}

function draw(host, data, sessionId, reload) {
  const s = data.session;
  const cancelled = Boolean(s.cancelled_at);
  const state = { filter: "all", query: "" };

  const rows = () => {
    const spec = FILTERS.find((f) => f.id === state.filter);
    const q = state.query.trim().toLowerCase();
    return data.students.filter((student) => {
      if (!spec.keep(student)) return false;
      if (!q) return true;
      return `${student.surname} ${student.other_names} ${matricText(student.matric_no)} ${student.device_user_id}`
        .toLowerCase().includes(q);
    });
  };

  // S/N is the student's place on the whole register, worked out once: rendering it with
  // indexOf inside every row walked the list 258 times over.
  const serial = new Map(data.students.map((student, index) => [student.person_id, index + 1]));

  const tableHost = h("div");
  const others = h("div");
  fill(others, othersSection(data));
  const shown = h("span", { class: "hw-muted", role: "status" });
  const clearFilter = h("button", { class: "hw-button hw-button--quiet", type: "button",
    dataset: { action: "show-all" }, hidden: true }, "Show all");
  clearFilter.addEventListener("click", () => { state.filter = "all"; paint(); });

  const search = h("input", { class: "hw-input", type: "search", placeholder: "Find a student in this register",
    autocomplete: "off", "aria-label": "Find a student in this register" });
  search.addEventListener("input", () => { state.query = search.value; paint(); });

  const tabs = h("div", { class: "hw-counts", role: "group", "aria-label": "Show only" });
  const countButtons = new Map();
  for (const spec of FILTERS) {
    if (spec.onlyOpen && !data.open) continue;
    const count = data.students.filter(spec.keep).length;
    const btn = h("button", { class: "hw-counts__item", type: "button",
      dataset: { action: `filter-${spec.id}`, tone: spec.tone }, "aria-pressed": "false" },
      spec.glyph ? h("span", { class: "hw-counts__glyph", "aria-hidden": "true" }, spec.glyph) : null,
      h("span", { class: "hw-counts__value hw-ids" }, String(count)),
      h("span", { class: "hw-counts__label" }, spec.label));
    btn.addEventListener("click", () => {
      state.filter = state.filter === spec.id ? "all" : spec.id;
      paint();
    });
    countButtons.set(spec.id, btn);
    tabs.append(btn);
  }

  // The table is built once and filtered by hiding rows. Rebuilding all 258 of them on every filter
  // press took 488 ms at a 4x slowdown on 2026-09-21, over the 200 ms budget, and only 89 ms of that
  // was this screen's own code: the rest was the browser laying out 1,500 new cells.
  const frame = registerTable(data.students, data, cancelled, sessionId, reload, serial);
  const rowFor = new Map();
  for (const tr of frame.querySelectorAll("tbody tr")) rowFor.set(Number(tr.dataset.person), tr);
  const noMatch = h("div", { class: "hw-table-frame", hidden: true }, h("div", { class: "hw-state" },
    h("span", { class: "hw-state__icon", "aria-hidden": "true" }, "⌕"),
    h("h2", { class: "hw-state__heading" }, "No student matches"),
    h("p", { class: "hw-state__body" },
      "Clear the filter or the search box to see the whole register.")));
  fill(tableHost, frame, noMatch);
  let flatEdge = null;

  function paint() {
    const list = rows();
    for (const [id, btn] of countButtons) btn.setAttribute("aria-pressed", String(state.filter === id));
    clearFilter.hidden = state.filter === "all" && !state.query.trim();
    shown.textContent = list.length === data.students.length
      ? `Showing all ${plural(data.students.length, "student")}`
      : `Showing ${list.length} of ${data.students.length}`;
    const keep = new Set(list.map((student) => student.person_id));
    let last = null;
    for (const [personId, tr] of rowFor) {
      const show = keep.has(personId);
      tr.hidden = !show;
      if (show) last = tr;
    }
    // The flat bottom edge belongs to the last row anyone can see, not to whichever row is last in
    // the markup, which :last-child would give to a hidden one.
    if (flatEdge) delete flatEdge.dataset.last;
    if (last) last.dataset.last = "true";
    flatEdge = last;
    frame.hidden = !list.length;
    noMatch.hidden = Boolean(list.length);
  }

  const cancel = cancelled
    ? button({ label: "Restore this class", permission: "class.manage",
        busyLabel: "Restoring", onClick: () => restore(sessionId, reload) })
    : button({ label: "Cancel this class", variant: "destructive", permission: "class.manage",
        onClick: () => askToCancel(sessionId, reload) });

  // Scans arriving while the class is open: the counts, each row's status and time, then the filter
  // again, so a row that has just become present leaves a "not yet" filter.
  function update(fresh) {
    data.students = fresh.students;
    // Somebody from another group can scan while the class is open, so their list follows too.
    if ((fresh.others || []).length !== (data.others || []).length) {
      data.others = fresh.others;
      fill(others, othersSection(data));
    }
    for (const student of fresh.students) {
      const tr = rowFor.get(student.person_id);
      if (!tr) continue;
      fill(tr.children[3], statusCell(student));
      fill(tr.children[4], student.first_scan
        ? h("span", { class: "hw-ids" }, student.first_scan.slice(11, 16))
        : h("span", { class: "hw-muted" }, "–"));
    }
    for (const spec of FILTERS) {
      const btn = countButtons.get(spec.id);
      if (btn) btn.querySelector(".hw-counts__value").textContent = String(fresh.students.filter(spec.keep).length);
    }
    paint();
  }

  fill(host, 
    h("p", { class: "hw-crumbs" },
      h("a", { class: "hw-link", href: href("courses") }, "Courses"),
      s.course_id ? h("span", { "aria-hidden": "true" }, " › ") : null,
      s.course_id ? h("a", { class: "hw-link", href: href(`courses/${s.course_id}/classes`) },
        `${s.course_code || "Course"}`) : null,
      h("span", { "aria-hidden": "true" }, " › "), "Class register"),
    h("div", { class: "hw-card hw-row hw-row--between", dataset: cancelled ? { dimmed: "true" } : null },
      h("div", {},
        h("h1", { class: "hw-page__title", style: { fontSize: "var(--hw-text-title)" } },
          longDate(s.date)),
        h("p", { class: "hw-page__subtitle" },
          (data.open ? `from ${s.start_time}, still taking attendance`
            : `${s.start_time} to ${s.end_time}`)
          + ` · ${s.course_code ? `${s.course_code} ` : ""}`
          // Who it was for, on a course with groups: its register is that group's alone.
          + (data.group ? `${data.group.name} · ` : "")
          + (s.opened_at ? "taken live" : s.kind === "device" ? "found from scans" : "recorded by hand"))),
      cancel),
    data.unassigned ? notice("warn", "This class is not on a course yet.",
      "Until it is, nobody is on its register and it counts towards nothing.",
      session.can("class.manage") ? { label: "Assign it to a course", path: "unassigned" } : null) : null,
    data.open ? notice("quiet", "This class is still taking attendance.",
      "Nobody is absent until it is ended, and it counts towards nothing until then.",
      session.can("register.pull") ? { label: "Open the class taking attendance", path: "live" } : null) : null,
    cancelled ? notice("quiet", "This class was cancelled, so it counts towards nothing.",
      s.cancel_note || "No reason was recorded.") : null,
    h("div", { class: "hw-section" },
      tabs,
      h("div", { class: "hw-row hw-row--between", style: { marginBlock: "var(--hw-space-4)" } },
        h("div", { style: { flex: "0 1 380px" } }, search),
        h("div", { class: "hw-row" }, shown, clearFilter)),
      tableHost,
      h("p", { class: "hw-section__help" },
        cancelled
          ? "A cancelled class cannot be corrected. Restore it first if it was cancelled by mistake."
          : "Select a row to open the correction drawer. A scan is never changed: a correction is "
            + "recorded beside it with a note.")),
    others);
  paint();
  return { update };
}

/**
 * A class for one group: the course's students from other groups who scanned in it anyway. Listed,
 * never counted, because this class is not on their register; without the list the scan was simply
 * invisible (groups.py). What to do about it is said here, where the question comes up.
 */
function othersSection(data) {
  if (!data.group || !(data.others || []).length) return null;
  const list = data.others;
  return h("section", { class: "hw-section" },
    // A count run on after "group" read as a group's number, "another group 1".
    h("h2", { class: "hw-section__title" }, `${plural(list.length, "student")} from another group scanned here`),
    h("p", { class: "hw-muted", style: { marginBlockEnd: "var(--hw-space-3)" } },
      `They were not in ${data.group.name} on this day, so this class counts neither way for them. `
      + "If one came instead of their own group's class, correct that class for them, with a note "
      + "that they came to this one."),
    table({
      caption: "Scanned here from another group",
      rows: list,
      columns: [
        { label: "Matric no.", render: (s) => h("a", { class: "hw-link hw-ids", href: href(`students/${s.person_id}`) },
          matricText(s.matric_no)) },
        { label: "Full name", render: (s) => `${s.surname} ${s.other_names}`.trim() },
        { label: "Their group", render: (s) => s.group || h("span", { class: "hw-muted" }, "No group") },
        { label: "Scanned at", align: "end", render: (s) => h("span", { class: "hw-ids" }, s.first_scan.slice(11, 16)) },
      ],
    }));
}

function notice(tone, title, body, action = null) {
  return h("div", { class: "hw-panel", dataset: { tone }, role: "status",
    style: { marginBlockEnd: "var(--hw-space-6)" } },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, tone === "warn" ? "⚠" : "i"),
    h("div", {}, h("p", { class: "hw-panel__title" }, title), h("p", { class: "hw-panel__body" }, body),
      action ? h("p", { style: { margin: "var(--hw-space-2) 0 0" } },
        h("a", { class: "hw-link", href: href(action.path) }, action.label)) : null));
}

function registerTable(list, data, cancelled, sessionId, reload, serial) {
  const open = (student) => {
    if (cancelled) return;
    openDrawer({ person_id: student.person_id, session_id: sessionId,
      courseId: data.session.course_id, onSaved: reload });
  };
  return table({
    caption: "Everyone on this register",
    rows: list,
    empty: h("div", { class: "hw-table-frame" }, h("div", { class: "hw-state" },
      h("span", { class: "hw-state__icon", "aria-hidden": "true" }, "⌕"),
      h("h2", { class: "hw-state__heading" }, "No student matches"),
      h("p", { class: "hw-state__body" }, "Clear the filter or the search box to see the whole register."))),
    rowAttrs: (student) => ({ dataset: { person: student.person_id } }),
    columns: [
      { label: "S/N", align: "end", render: (s) => h("span", { class: "hw-ids" },
        String(serial.get(s.person_id))) },
      { label: "Matric no.", render: (s) => h("span", { class: "hw-ids" }, matricText(s.matric_no)) },
      { label: "Full name", render: (s) => h("span", {},
        `${s.surname} ${s.other_names}`.trim(),
        s.kind === "carry_over"
          ? h("span", { class: "hw-tag" }, "carry-over") : null) },
      { label: "Status", render: (s) => statusCell(s) },
      { label: "Scanned at", align: "end", render: (s) => s.first_scan
        ? h("span", { class: "hw-ids" }, s.first_scan.slice(11, 16))
        : h("span", { class: "hw-muted" }, "–") },
      { label: "", align: "end", render: (s) => cancelled ? null : correctLink(s, open) },
    ],
  });
}

function correctLink(student, open) {
  const canCorrect = session.can("register.correct");
  const canRequest = session.can("register.request");
  if (session.isSelf(student.person_id)) {
    return h("span", { class: "hw-muted" }, "Not yours to correct");
  }
  if (!canCorrect && !canRequest) return null;
  const link = h("button", { class: "hw-button hw-button--quiet", type: "button",
    dataset: { action: "correct" } }, canCorrect ? "Correct" : "Ask for a correction");
  link.addEventListener("click", (event) => { event.stopPropagation(); open(student); });
  return link;
}

function statusCell(student) {
  const spec = {
    present: ["✓", "Present", "present"],
    marked_present: ["✓", "Present", "present"],
    absent: ["✕", "Absent", "absent"],
    marked_absent: ["✕", "Absent", "absent"],
    excused: ["E", "Excused", "excused"],
    waiting: ["○", "Not yet", "neutral"],
  }[student.status] || ["○", student.status, "neutral"];
  const note = student.mark
    ? `corrected by ${student.mark.by}`
    : student.excusal
      ? `${student.excusal.category}${student.excusal.note ? `, ${student.excusal.note}` : ""}`
      : "";
  return h("div", {},
    h("span", { class: "hw-pill", dataset: { tone: spec[2] } },
      h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, spec[0]), spec[1]),
    note ? h("p", { class: "hw-muted", style: { margin: "var(--hw-space-1) 0 0", fontSize: "var(--hw-text-body)" } },
      note) : null);
}

// -- cancelling and restoring --------------------------------------------------------------------

function askToCancel(sessionId, reload) {
  const note = field({ label: "Why is the class cancelled?", name: "note", rows: 3,
    help: "Kept with the class for good, and shown wherever it appears.",
    validate: (v) => (v.trim() ? "" : "Say why the class is cancelled.") });
  const save = button({ label: "Cancel this class", variant: "destructive", busyLabel: "Cancelling" });
  const box = dialog({
    title: "Cancel this class",
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        "A cancelled class counts towards nothing: not the classes held, not anyone's percentage, "
        + "and not the eligibility list. Every scan and correction on it is kept. A class still "
        + "taking attendance stops taking it."),
      note),
    actions: [button({ label: "Keep the class", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(note)) return;
    setBusy(save, true);
    try {
      await api.post(`/api/sessions/${sessionId}/cancel`, { note: note.value().trim() });
      box.close();
      toast("The class is cancelled.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      note.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}

async function restore(sessionId, reload) {
  try {
    await api.post(`/api/sessions/${sessionId}/restore`, {});
    toast("The class is restored and counts again.");
    announce("The class is restored.");
    await reload();
  } catch (error) {
    toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
  }
}
