// Screen 21: Student evidence. Mockups: Studentattendancerecord.png, Recordnoscansatall.png,
// Recordremovedfromacourse.png, Recordinactivestudent.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "21 Student evidence". The timeline itself is
// components/hw-evidence.js, hero signature 2 of 3.
//
// This is the screen a dispute is settled on, so everything behind a status is on it: every scan
// with its source, every class with the reason for its status, every correction and every excused
// absence, including withdrawn ones.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  matricText,
  announce, button, dateAndTime, dialog, fill, h, loadingCards, longDate, page, plural, section,
  setBusy, table, toast,
} from "../ui.js";
import "../../components/hw-evidence.js";

export default {
  id: "student",
  nav: "students",
  title: "Student record",
  permission: "students.read",

  async render(view, { params }) {
    const personId = Number(params.id);
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Student record", children: [loadingCards(2)] }));
    const data = await api.get(`/api/students/${personId}/evidence`);
    draw(host, data, () => this.render(fill(view), { params }));
  },
};

function draw(host, data, reload) {
  const s = data.student;
  const name = `${s.surname} ${s.other_names}`.trim();
  const live = data.excusals.filter((e) => !e.revoked_at);
  const withdrawn = data.excusals.filter((e) => e.revoked_at);

  const timeline = document.createElement("hw-evidence");
  timeline.data = data;

  fill(host, page({
    title: name,
    subtitle: `${matricText(s.matric_no)} · device ID ${s.device_user_id}`
      + (data.levels && data.levels.length ? ` · ${data.levels[0].level}` : ""),
    actions: [button({ label: "Record an excused absence", primary: true,
      permission: "excusal.manage",
      reason: session.isSelf(s.person_id)
        ? "You cannot grant an excused absence for yourself. Ask someone else to do it." : "",
      href: href(`excusals?student=${s.person_id}`) })],
    wide: true,
    // This record is reached from four places: the search, a class register, a course's student
    // list and an account's linked record. A crumb back to the students, as screen 7 has
    // (Checklist Design, Single item detail: breadcrumb or back navigation).
    crumbs: [h("a", { class: "hw-link", href: href("students") }, "Students"),
      h("span", { "aria-hidden": "true" }, " › "), name],
    children: [
      s.active ? null : h("div", { class: "hw-panel", dataset: { tone: "quiet" },
        style: { marginBlockEnd: "var(--hw-space-6)" } },
        h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "i"),
        h("p", { class: "hw-panel__body" },
          "This student is no longer active. Their record is kept, and their scans still count "
          + "towards the classes they were on.")),
      identity(s, reload),
      section("Every class, newest first", timeline),
      section("Excused absences", live.length || withdrawn.length
        ? excusalTable([...live, ...withdrawn])
        : h("p", { class: "hw-muted" }, "None recorded.")),
      section("Every scan the device sent", scans(data)),
      h("p", { class: "hw-section__help" },
        "A scan is never changed. A correction is recorded beside it with a note, and both stay "
        + "here for good."),
    ],
  }));
}

// fingers_enrolled is the list of finger indexes the device holds, not a count.
function fingerCount(s) {
  return Array.isArray(s.fingers_enrolled) ? s.fingers_enrolled.length : (s.fingers_enrolled || 0);
}

function identity(s, reload) {
  return h("dl", { class: "hw-facts", style: { marginBlockEnd: "var(--hw-space-8)" } },
    h("dt", {}, "On the terminal"),
    h("dd", {}, s.on_device
      ? h("span", { class: "hw-row", style: { gap: "var(--hw-space-3)" } },
        h("span", {}, h("span", { "aria-hidden": "true", style: { color: "var(--hw-present)" } }, "\u2713 "),
          `Yes, as device ID ${s.device_user_id}`),
        button({ label: "Take off the terminal", variant: "destructive", permission: "device.manage",
          onClick: () => takeOffDialog(s, reload) }))
      : h("span", { class: "hw-muted" },
        h("span", { "aria-hidden": "true" }, "\u25cb "),
        `Not on it. They cannot scan until they are sent, as device ID ${s.device_user_id}.`)),
    h("dt", {}, "Fingerprints"),
    h("dd", {}, fingerCount(s) >= 2
      ? h("span", { style: { color: "var(--hw-present)" } },
        h("span", { "aria-hidden": "true" }, "✓ "), `${plural(fingerCount(s), "finger")} enrolled`)
      : h("span", {},
        h("span", { "aria-hidden": "true", style: { color: "var(--hw-ink-muted)" } }, "○ "),
        `${plural(fingerCount(s), "finger")} enrolled, two are needed`)),
    h("dt", {}, "Keypad password"),
    h("dd", {}, s.has_keypad_password
      ? h("span", {}, "Set. ", h("span", { class: "hw-muted" }, s.keypad_password_reason || ""))
      : h("span", { class: "hw-muted" }, "Not set")));
}

function excusalTable(rows) {
  return table({
    caption: "Excused absences",
    rows,
    rowAttrs: (r) => (r.revoked_at ? { dataset: { dimmed: "true" } } : null),
    columns: [
      { label: "Dates", className: "hw-nowrap", render: (r) =>
        h("span", { class: "hw-nowrap" },
          r.date_from === r.date_to ? longDate(r.date_from)
            : `${longDate(r.date_from)} to ${longDate(r.date_to)}`) },
      { label: "Category", render: (r) =>
        h("span", { class: "hw-pill", dataset: { tone: "excused" } },
          h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "E"), r.category) },
      { label: "Why", render: (r) => r.note },
      { label: "Covers", render: (r) => r.course_code || h("span", { class: "hw-muted" }, "Every course") },
      { label: "", align: "end", render: (r) => r.revoked_at
        ? h("span", { class: "hw-muted hw-nowrap" },
          `Withdrawn by ${r.revoked_by_name || "someone"}, `
          + `${longDate((r.revoked_at || "").slice(0, 10))}`)
        : null },
    ],
  });
}

function scans(data) {
  if (!data.scans.length) {
    return h("p", { class: "hw-muted" },
      "The device has never sent a scan for this student. If they have been attending, check they "
      + "are enrolled and that their device ID is the one on the terminal.");
  }
  return table({
    caption: "Every scan from the device",
    density: "compact",
    rows: data.scans,
    columns: [
      { label: "When", render: (r) => h("span", { class: "hw-tnum" }, dateAndTime(r.timestamp)) },
      { label: "Where it came from", render: (r) =>
        r.source === "usb" ? `A USB file, ${r.file_name || "name not recorded"}` : "The cable" },
      { label: "Which terminal", render: (r) =>
        h("span", { class: "hw-ids" }, `${r.device}${r.device_serial ? `, ${r.device_serial}` : ""}`) },
      { label: "Stored", align: "end", render: (r) =>
        h("span", { class: "hw-tnum" }, dateAndTime(r.imported_at)) },
    ],
  });
}


/**
 * Take one student off the terminal, keeping their record and their scans here. Asked for on a
 * first run: somebody sent by mistake, or who has left, could only be removed by emptying the whole
 * terminal (2026-09-21).
 */
function takeOffDialog(student, reload) {
  const name = `${student.surname} ${student.other_names}`.trim();
  const go = button({ label: "Take them off", variant: "destructive", busyLabel: "Taking them off" });
  const box = dialog({
    title: `Take ${name} off the terminal?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        "Their fingerprints go with them, so they cannot scan until they are sent to the terminal "
        + "again and enrolled again."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "Nothing here is deleted: this record, every scan they have already made and every "
        + `correction stay exactly as they are, and device ID ${student.device_user_id} is still `
        + "theirs and is never given to anybody else.")),
    actions: [button({ label: "Leave them on it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      const devices = await api.get("/api/devices");
      const device = devices.find((d) => d.is_default) || devices[0];
      await api.post(`/api/devices/${device.id}/people/${student.person_id}/remove`, {});
      box.close();
      toast(`${name} is off the terminal.`);
      announce(`${name} is off the terminal.`);
      await reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}
