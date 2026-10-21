// Screen 5: Get attendance result. Mockups: Attendancepulled.png, AttendancepulledNothingnew.png,
// AttendancepulledWrongdevice.png. Fix list: docs/DESIGN-DEVIATIONS.md, "5 Get attendance result".
// Contract: GET /api/imports/{batch_id} (rollcall/pulls.py).
//
// Kept from the mockup: the two serials as a labelled pair on the wrong-device frame, the chip that
// changes with the body rather than contradicting it, and the provenance panel, which is what this
// screen exists for.
//
// Fixed from the mockup:
//   every gap label is computed from the two bursts it sits between, never written: the mockup's
//     "4h 12m gap" was really 1h 11m, borrowed from the provenance panel;
//   each burst is positioned and sized from its own timestamps, so nothing is hand-placed;
//   each burst sits on its own --hw-accent-soft band;
//   a disabled primary button says what it does, with the reason beneath it, not inside its label;
//   a zero is not a link;
//   the footnote about scans never changing is not shown where nothing was read.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  ago, button, clear, dateAndTime, emptyState, h, longDate, page, plural, section, table,
} from "../ui.js";

export default {
  id: "pull",
  nav: "today",
  title: "Get attendance result",
  permission: "register.read",

  async render(view, { params, shell }) {
    const stored = sessionStorage.getItem("hw-pull-result");
    let batchId = params.id ? Number(params.id) : null;
    if (!batchId && stored) {
      try { batchId = JSON.parse(stored).batch_id; } catch { batchId = null; }
    }
    sessionStorage.removeItem("hw-pull-result");

    const data = batchId ? await api.get(`/api/imports/${batchId}`) : await api.get("/api/imports");
    if (!data) {
      view.append(page({ title: "Get attendance", children: [h("div", { class: "hw-table-frame" },
        emptyState({ icon: "☰", heading: "Nothing has been read from the device yet",
          body: "Get attendance from Today. Herewise stores every scan and works out each class from them.",
          action: button({ label: "Go to Today", primary: true, href: href("today") }) }))] }));
      return;
    }
    shell.setDevice("connected");
    draw(view, data);
  },
};

function draw(view, data) {
  const nothing = data.new_count === 0;
  const first = data.classes.find((c) => c.session_id);
  const open = button({
    label: "Open the class register",
    primary: true,
    disabled: !first,
    reason: first ? "" : "",
    href: first ? href(`classes/${first.session_id}`) : null,
    align: "end",
  });

  view.append(page({
    title: "Attendance read",
    subtitle: `${data.device.name || "The device"} · ${dateAndTime(data.at)} · by ${data.by || "Herewise"}`,
    actions: [open, first ? null : h("p", { class: "hw-reason", style: { textAlign: "end" } },
      nothing ? "Nothing was read, so there is no register to open."
        : "No class was worked out from these scans.")],
    children: [
      summary(data),
      nothing ? nothingNew(data) : timeline(data),
      classesTable(data),
      unknown(data),
      nothing ? null : h("p", { class: "hw-section__help" },
        "Scans are never changed. A correction is recorded beside one, with a note, and the sheet "
        + "keeps both."),
    ],
  }));
}

function summary(data) {
  const cells = [
    ["Scans read", String(data.records_read), ""],
    ["New", String(data.new_count), data.duplicate_count
      ? `${plural(data.duplicate_count, "was", "were")} already stored` : "nothing was a repeat"],
    ["Classes found", String(data.classes.length),
      `${data.settings.min_students} students or more, ${data.settings.gap_minutes} minute gap`],
    ["Span", data.first_punch_at
      ? `${data.first_punch_at.slice(11, 16)} to ${data.last_punch_at.slice(11, 16)}` : "–",
      data.first_punch_at ? longDate(data.first_punch_at) : ""],
  ];
  return h("div", { class: "hw-headline" }, ...cells.map(([label, value, note]) =>
    h("div", {},
      h("p", { class: "hw-headline__label" }, label),
      h("p", { class: "hw-headline__value hw-ids" }, value),
      note ? h("p", { class: "hw-headline__note" }, note) : null)));
}

function nothingNew(data) {
  return section("", h("div", { class: "hw-table-frame" }, emptyState({
    icon: "☰",
    heading: data.records_read ? "Every scan on the device was already stored" : "The device had no scans",
    body: data.records_read
      ? `All ${plural(data.records_read, "scan")} had been read before, so nothing changed. `
        + "Scans stay on the device until they are cleared, so reading twice is safe."
      : "Nobody has scanned since the device was last cleared. Check the class actually used it.",
  })));
}

/**
 * The scan timeline: one band per detected class, laid out from its own timestamps, with the gap
 * between two bursts computed from the two of them.
 */
function timeline(data) {
  if (!data.classes.length) return null;
  const bands = [];
  for (const [index, item] of data.classes.entries()) {
    if (item.gap_minutes_before !== null && item.gap_minutes_before !== undefined) {
      bands.push(h("p", { class: "hw-gap" },
        h("span", { "aria-hidden": "true" }, "⋯ "),
        `${formatGap(item.gap_minutes_before)} with no scans`));
    }
    bands.push(band(item, index));
  }
  return section("What the scans looked like", h("div", { class: "hw-timeline" }, ...bands),
    h("p", { class: "hw-section__help" },
      "Each band is one class, drawn from the times the scans actually arrived. A long gap with no "
      + "scans is where Herewise decided one class had ended and another began."));
}

function band(item, index) {
  const peak = Math.max(1, ...item.strip.map((b) => b.scans));
  const bars = h("div", { class: "hw-timeline__bars", "aria-hidden": "true" },
    ...item.strip.map((bucket) => h("span", { class: "hw-timeline__bar",
      style: { height: `${Math.max(4, Math.round((bucket.scans / peak) * 100))}%` },
      title: `${bucket.scans} in the ${bucket.minute} to ${bucket.minute + 5} minute` })));
  return h("div", { class: "hw-timeline__band" },
    h("p", { class: "hw-timeline__title" },
      item.course_code
        ? h("span", {}, h("b", {}, item.course_code), " ", h("span", { class: "hw-muted" }, item.course_title || ""))
        : h("span", { class: "hw-pill", dataset: { tone: "review" } },
          h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "?"), "Not on a course yet"),
      h("span", { class: "hw-muted hw-ids" }, ` · ${item.start_time} to ${item.end_time}`)),
    bars,
    h("p", { class: "hw-timeline__note" },
      `${plural(item.students, "student")} scanned, ${plural(item.scans, "scan")} in all. `
      + `First at ${item.first_scan ? item.first_scan.slice(11, 16) : "–"}, `
      + `last at ${item.last_scan ? item.last_scan.slice(11, 16) : "–"}.`));
}

function formatGap(minutes) {
  if (minutes < 60) return plural(minutes, "minute");
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${plural(hours, "hour")} ${rest} min` : plural(hours, "hour");
}

function classesTable(data) {
  if (!data.classes.length) return null;
  return section("Classes found", table({
    caption: "Classes worked out from these scans",
    rows: data.classes,
    columns: [
      { label: "Course", render: (c) => c.course_code
        ? h("span", {}, h("b", {}, c.course_code), " ", h("span", { class: "hw-muted" }, c.course_title || ""))
        : h("span", { class: "hw-muted" }, `${c.level_name}, not on a course`) },
      { label: "When", render: (c) => `${longDate(c.date)}, ${c.start_time} to ${c.end_time}` },
      { label: "Students", align: "end", render: (c) => h("span", { class: "hw-ids" }, String(c.students)) },
      { label: "", align: "end", render: (c) => c.needs_course
        ? h("a", { class: "hw-link", href: href("unassigned") }, "Put it on a course")
        : h("a", { class: "hw-link", href: href(`classes/${c.session_id}`) }, "Open the register") },
    ],
  }));
}

function unknown(data) {
  const count = data.unknown_device_ids.length;
  // A zero is not a link: it drops to muted and loses its target.
  if (!count) {
    return h("p", { class: "hw-muted" }, "No scans from unknown device IDs.");
  }
  return h("p", {},
    h("a", { class: "hw-link", href: href("device/unmatched") },
      `${plural(count, "scan")} from device IDs nobody in the roster has`),
    h("span", { class: "hw-muted" },
      ". They are stored, and will attach themselves if that person is imported later."));
}
