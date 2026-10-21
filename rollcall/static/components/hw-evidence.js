// <hw-evidence>: the Evidence timeline. Hero signature 2 of 3.
// Spec: docs/COMPONENT-GUIDE.md, "Evidence timeline". Contract: GET /api/students/{id}/evidence.
// Screen 21, fix list: docs/DESIGN-DEVIATIONS.md, "21 Student evidence".
//
// One row per class, newest first: the date, the class window drawn as a bar, the first scan as a
// mark inside or outside it, the status, and the written reason from the contract. Everything the
// student could dispute is visible without expanding anything.
//
// The off-by-one the mockup hid: **a cancelled class belongs in the timeline and in no other
// total.** In the mockup 18 classes were listed, one of them cancelled, and present plus absent
// plus excused also came to 18. That is the kind of error that survives every surface check,
// because each figure looks right on its own.

import { fill, h, longDate, plural } from "../app/ui.js";

const CSS = `
hw-evidence { display: block; }
.hw-ev__course {
  margin-block-end: var(--hw-space-8);
}
.hw-ev__head {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--hw-space-3);
  margin-block-end: var(--hw-space-3);
}
.hw-ev__code { font-size: var(--hw-text-section); font-weight: var(--hw-weight-emphasis); }
.hw-ev__figures { display: flex; flex-wrap: wrap; gap: var(--hw-space-6); margin-block-end: var(--hw-space-4); }
.hw-ev__row {
  display: grid;
  grid-template-columns: 15rem minmax(140px, 1fr) auto minmax(180px, 1.4fr);
  gap: var(--hw-space-3);
  align-items: center;
  padding: var(--hw-space-3);
  border-inline-start: 4px solid transparent;
  border-block-end: var(--hw-rule-width) solid var(--hw-rule);
  background: var(--hw-surface);
}
.hw-ev__row[data-kind="corrected"] { border-inline-start-color: var(--hw-accent); background: var(--hw-accent-soft); }
.hw-ev__row[data-kind="review"] { border-inline-start-color: var(--hw-review); background: var(--hw-review-soft); }
.hw-ev__row[data-kind="cancelled"] { background: var(--hw-sunken); color: var(--hw-ink-muted); }
.hw-ev__when { font-variant-numeric: tabular-nums; white-space: nowrap; }
.hw-ev__when b { display: block; font-weight: var(--hw-weight-label); }
.hw-ev__when span { color: var(--hw-ink-muted); font-size: var(--hw-text-body); }
/* The class window as a bar, with the scan as a mark inside it or outside it. */
.hw-ev__bar {
  position: relative; height: 20px;
  background: var(--hw-sunken); border-radius: var(--hw-radius-pill);
}
.hw-ev__window { position: absolute; inset-block: 0; background: var(--hw-rule); border-radius: var(--hw-radius-pill); }
/* 18px holding a 12px glyph, not 16 holding 11: the tick and the query mark carry the meaning of
   the whole row, and 11px is below anything readable across a desk. */
.hw-ev__scan {
  position: absolute; inset-block-start: 1px;
  width: 18px; height: 18px; margin-inline-start: -9px;
  display: grid; place-items: center;
  border-radius: 50%; background: var(--hw-present); color: var(--hw-on-accent);
  font-size: var(--hw-text-caption); font-weight: var(--hw-weight-emphasis);
}
.hw-ev__scan[data-outside] { background: var(--hw-review); }
.hw-ev__reason { color: var(--hw-ink-muted); font-size: var(--hw-text-body); }
.hw-ev__reason b { color: var(--hw-ink); font-weight: var(--hw-weight-label); }
.hw-ev__empty { padding: var(--hw-space-8); color: var(--hw-ink-muted); }
@media (max-width: 900px) {
  .hw-ev__row { grid-template-columns: 1fr 1fr; }
  .hw-ev__bar { display: none; }
}
`;

let styled = false;
function adoptStyles() {
  if (styled) return;
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(CSS);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  styled = true;
}

const PILL = {
  present: ["✓", "Present", "present"],
  marked_present: ["✓", "Present, corrected", "present"],
  absent: ["✕", "Absent", "absent"],
  marked_absent: ["✕", "Absent, corrected", "absent"],
  excused: ["E", "Excused", "excused"],
  cancelled: ["✕", "Class cancelled", "neutral"],
  not_on_course: ["?", "Not on the course then", "review"],
  // A class for a group they were not in that day (2026-09-29): not theirs, counted neither way.
  other_group: ["–", "Another group's class", "neutral"],
};

export class HwEvidence extends HTMLElement {
  connectedCallback() { adoptStyles(); }

  set data(evidence) {
    this._data = evidence;
    this.render();
  }

  get data() { return this._data; }

  render() {
    adoptStyles();
    const d = this._data;
    if (!d) return;
    fill(this, ...d.courses.map((course) => this.course(course)));
  }

  course(course) {
    const removed = Boolean(course.removed_at);
    const s = course.summary;
    // A cancelled class is in the timeline and in no other total. So is another group's class they
    // scanned in, on a course split into groups: it was held, but not for them. Other groups' classes
    // they did not come to are not in the timeline at all.
    const cancelled = course.classes.filter((c) => c.cancelled).length;
    const elsewhere = course.classes.filter((c) => !c.cancelled && c.status === "other_group").length;
    const held = course.classes.length - cancelled - elsewhere;

    return h("section", { class: "hw-ev__course" },
      h("div", { class: "hw-ev__head" },
        h("span", { class: "hw-ev__code" },
          course.code, course.title ? h("span", { class: "hw-muted" }, ` ${course.title}`) : null),
        course.kind === "carry_over" ? h("span", { class: "hw-tag" }, "carry-over") : null,
        removed
          ? h("span", { class: "hw-pill", dataset: { tone: "neutral" } },
            h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "○"),
            `Removed ${longDate((course.removed_at || "").slice(0, 10))}`)
          : null),
      removed
        ? h("p", { class: "hw-muted", style: { marginBlockEnd: "var(--hw-space-3)" } },
          `${course.removed_note || "No reason recorded."} Classes after that day are not counted.`)
        : null,
      s ? h("div", { class: "hw-ev__figures" },
        figure(String(s.attended), "present at " + plural(s.counted, "counted class", "counted classes")),
        figure(`${s.percent}%`, `against a ${s.threshold_percent}% pass mark`),
        figure(String(s.excused), s.excused === 1 ? "excused absence" : "excused absences"),
        figure(String(cancelled), cancelled === 1 ? "cancelled class, counting towards nobody"
          : "cancelled classes, counting towards nobody"))
        : h("p", { class: "hw-muted" }, "No verdict: this course has no figures for them."),
      h("p", { class: "hw-muted", style: { margin: "0 0 var(--hw-space-2)" } },
        `${plural(course.classes.length, "class", "classes")} in the timeline, ${held} held for them`
        + (elsewhere ? `, ${plural(elsewhere, "class", "classes")} of another group's they scanned in` : "")
        + (cancelled ? `, ${cancelled} cancelled` : "")),
      h("div", { class: "hw-table-frame" },
        course.classes.length
          ? h("div", {}, ...course.classes.slice().reverse().map((entry) => this.row(entry)))
          : h("p", { class: "hw-ev__empty" },
            "No class has been held on this course yet, so there is nothing to show.")));
  }

  row(entry) {
    const cancelled = Boolean(entry.cancelled);
    const status = cancelled ? "cancelled" : (entry.status || "absent");
    const spec = PILL[status] || PILL.review;
    const kind = cancelled ? "cancelled"
      : status.startsWith("marked_") ? "corrected"
        : status === "excused" || status === "not_on_course" ? "review" : "";

    return h("div", { class: "hw-ev__row", dataset: kind ? { kind } : null },
      h("div", { class: "hw-ev__when" },
        h("b", {}, longDate(entry.date)),
        h("span", {}, `${entry.start_time} to ${entry.end_time}`)),
      this.bar(entry),
      h("span", { class: "hw-pill", dataset: { tone: spec[2] } },
        h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, spec[0]), spec[1]),
      h("p", { class: "hw-ev__reason" },
        cancelled
          ? h("span", {}, h("b", {}, "Counts towards nobody. "), entry.cancel_note || "")
          : entry.reason || ""));
  }

  /**
   * The class window, and the first scan placed inside it or outside it by its real time.
   * "Inside" means inside the window the register actually counts, grace included, not the class
   * times: a scan at 08:56 for a 09:00 class is inside, and marking it as outside would contradict
   * the Present pill beside it.
   */
  bar(entry) {
    const mins = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
    const window = entry.window || {};
    const opens = window.from ? mins(window.from.slice(11, 16)) : mins(entry.start_time);
    const closes = window.to ? mins(window.to.slice(11, 16)) : mins(entry.end_time);

    const bar = h("div", { class: "hw-ev__bar", role: "img",
      "aria-label": entry.first_scan
        ? `Scanned at ${entry.first_scan.slice(11, 16)}, class ${entry.start_time} to ${entry.end_time}`
        : `No scan. Class ${entry.start_time} to ${entry.end_time}` });
    // An hour either side of the counted window, so a scan just outside is visible, not clipped.
    const from = Math.max(0, opens - 60);
    const to = Math.min(24 * 60, closes + 60);
    const span = Math.max(1, to - from);
    const at = (m) => `${Math.max(0, Math.min(100, ((m - from) / span) * 100))}%`;

    bar.append(h("span", { class: "hw-ev__window",
      style: { insetInlineStart: at(mins(entry.start_time)),
        width: `${((mins(entry.end_time) - mins(entry.start_time)) / span) * 100}%` } }));
    if (entry.first_scan) {
      const scanned = mins(entry.first_scan.slice(11, 16));
      const outside = scanned < opens || scanned > closes;
      bar.append(h("span", { class: "hw-ev__scan", dataset: outside ? { outside: "true" } : null,
        style: { insetInlineStart: at(scanned) }, title: entry.first_scan.slice(11, 16) },
        outside ? "?" : "✓"));
    }
    return bar;
  }
}

function figure(value, label) {
  return h("div", {},
    h("p", { class: "hw-headline__value hw-tnum", style: { margin: 0 } }, value),
    h("p", { class: "hw-headline__note", style: { margin: 0 } }, label));
}

customElements.define("hw-evidence", HwEvidence);
