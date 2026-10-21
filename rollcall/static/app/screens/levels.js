// Screen 22: Levels. Mockups: Levelsmain.png, Levelsfirstrun.png, Levelsrenaming300Level.png,
// Levelsterminalnotanswering.png. Fix list: docs/DESIGN-DEVIATIONS.md, "22 Levels".
//
// Kept from the mockup: when the terminal does not answer the figures stay, because they come from
// this computer, and only what came from the device goes muted with its reason.
//
// Fixed from the mockup:
//   editing one row does not move the others: the table has fixed column widths;
//   one alignment per column, and every number right-aligned in a numeric column;
//   the slashed zero goes on device IDs only, and every count is tabular Inter, not monospace.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  panel, invalid, actionRow, announce, button, dialog, field, fill, h, loadingTable, page, plural, section,
  setBusy, table, toast,
} from "../ui.js";

export default {
  id: "levels",
  title: "Levels",
  permission: "roster.manage",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Levels",
      children: [loadingTable(["Level", "Device IDs", "Students", "On the device", "Enrolment"])] }));
    const reload = () => this.render(fill(view), ctx);

    const levels = await api.get("/api/levels");
    const progress = await Promise.all(levels.map((level) =>
      level.students ? api.get(`/api/levels/${level.id}/students`).catch(() => null)
        : Promise.resolve(null)));
    const devices = await api.get("/api/devices").catch(() => []);
    const device = devices.find((d) => d.is_default) || devices[0] || null;
    draw(host, levels, progress, device, reload);
  },
};

function draw(host, levels, progress, device, reload) {
  const rows = levels.map((level, index) => ({ ...level, progress: progress[index] }));
  const students = rows.reduce((n, r) => n + r.students, 0);
  const onDevice = rows.reduce((n, r) =>
    n + (r.progress ? r.progress.students.filter((s) => s.on_device).length : 0), 0);
  const done = rows.reduce((n, r) => n + (r.progress ? r.progress.complete : 0), 0);

  fill(host, page({
    title: "Levels",
    subtitle: students
      ? `${plural(students, "student")} this session · ${done} enrolled, ${students - done} to go`
      : "No roster has been imported yet",
    actions: [button({ label: "Add a level", primary: true, permission: "roster.manage",
      onClick: () => addDialog(levels, reload) })],
    children: [
      device ? capacityCard(device, students) : null,
      section("", table({
        caption: "Levels this session",
        rows,
        columns: [
          { label: "Level", render: (r) => r.name },
          { label: "Device IDs", align: "end", render: (r) =>
            h("span", { class: "hw-ids" }, `${r.id_block_start} to ${r.id_block_end}`) },
          { label: "Students", align: "end", render: (r) =>
            r.students ? h("span", { class: "hw-tnum" }, String(r.students))
              : h("span", { class: "hw-muted" }, "–") },
          { label: "On the device", align: "end", render: (r) => {
            if (!r.progress) return h("span", { class: "hw-muted" }, "–");
            const count = r.progress.students.filter((s) => s.on_device).length;
            return h("span", {},
              h("span", { "aria-hidden": "true",
                style: { color: count === r.students ? "var(--hw-present)" : "var(--hw-ink-muted)" } },
                count === r.students ? "✓ " : "○ "),
              h("span", { class: "hw-tnum" }, `${count} of ${r.students}`));
          } },
          { label: "Enrolment", align: "end", render: (r) => {
            if (!r.progress) return h("span", { class: "hw-muted" }, "–");
            const left = r.progress.total - r.progress.complete;
            if (!left) {
              return h("span", { style: { color: "var(--hw-present)" } },
                h("span", { "aria-hidden": "true" }, "✓ "), "All done");
            }
            return session.can("enrollment.run")
              ? h("a", { class: "hw-link", href: href("enrolment") }, `Enrol ${left}`)
              : h("span", { class: "hw-muted" }, `${left} to go`);
          } },
          // Parted, because Remove and Import roster share this cell and one of them cannot be
          // undone. Remove stays first: the last thing read is the one meant to be pressed.
          // actionRow, so the two buttons stay on one line and the reason gathers underneath
          // them: as a plain row, a reason beside the buttons pushed Import again onto its own
          // line and made the row 142px tall (measured 2026-09-22).
          { label: "", align: "end", render: (r) => actionRow({ parted: true },
            // Always offered, disabled with the backend's own sentence when the level has
            // anything on it. Leaving it out is what this app tells every other screen not to do,
            // and somebody looking for it on a second run could not find it (2026-09-22).
            // A level with anything on it offers Delete roster instead, which takes the lot, the
            // terminal included (asked for on 2026-09-23). Remove was disabled here with "On it: 1
            // course, 120 students and 1 roster import" and nothing on the screen led anywhere.
            r.can_remove
              ? button({ label: "Remove", variant: "destructive", permission: "roster.manage",
                  onClick: () => removeLevel(r, reload) })
              : button({ label: "Delete roster", variant: "destructive", permission: "roster.manage",
                  onClick: () => clearLevel(r, reload) }),
            r.students
              ? button({ label: "Import again", href: href(`levels/${r.id}/import`),
                  permission: "roster.manage" })
              : button({ label: "Import roster", primary: true, href: href(`levels/${r.id}/import`),
                  permission: "roster.manage" })) },
        ],
      })),
      h("p", { class: "hw-section__help" },
        "Delete roster takes a level's students, courses, classes and attendance, and takes the "
        + "students and their fingerprints off the terminal, so the terminal has to be connected. "
        + "The level stays, empty, ready for a new roster. Remove takes an empty level away."),
      h("p", { class: "hw-section__help" },
        "A level's device IDs are fixed and never reused, so a scan from last year can never become "
        + "this year's student. Importing again adds the new names and leaves the rest alone. Add "
        + "the years your department runs and remove the ones it does not: a level goes up in "
        + "hundreds, and its name is yours to change."),
    ],
  }));
}

function capacityCard(device, students) {
  const capacity = device.user_capacity || 1000;
  const used = device.user_count ?? students;
  const percent = Math.round((used / capacity) * 100);
  // A band across the page, the same shape as a course header's figures, rather than one card
  // sitting in the left half with the right half empty (reported on a second run, 2026-09-22).
  return h("div", { class: "hw-headline", style: { marginBlockEnd: "var(--hw-space-6)" } },
    h("div", {},
      h("p", { class: "hw-headline__label" }, `Places on ${device.name}`),
      h("p", { class: "hw-headline__value hw-tnum" },
        `${used.toLocaleString("en-GB")} of ${capacity.toLocaleString("en-GB")}`),
      h("div", { class: "hw-gauge", role: "img",
                 "aria-label": `${percent} per cent of places used`,
                 style: { maxWidth: "20rem", marginBlockStart: "var(--hw-space-2)" } },
        h("span", { class: "hw-gauge__fill", style: { width: `${percent}%` } }))),
    h("div", {},
      h("p", { class: "hw-headline__label" }, "Free"),
      h("p", { class: "hw-headline__value hw-tnum" }, (capacity - used).toLocaleString("en-GB")),
      h("p", { class: "hw-headline__note" }, "checked before any import, never after")));
}


// -- adding and removing a year the department runs ----------------------------------------------
//
// Herewise seeded 100 to 500 and had no way to change it, so a department that stops at 400 and a
// course of study that runs to 700 were both stuck (found on a first run, 2026-09-21).

function addDialog(existing, reload) {
  const taken = new Set(existing.map((l) => l.level_number));
  const next = [100, 200, 300, 400, 500, 600, 700, 800, 900].find((n) => !taken.has(n)) || 600;
  const number = field({ label: "Level", type: "number", value: String(next), min: 100, max: 900,
    help: "In hundreds, 100 to 900. This decides the block of device IDs the level owns, which is "
      + "permanent.",
    validate: (v) => {
      const n = Number(v);
      if (!v || !Number.isInteger(n) || n < 100 || n > 900) return "A level runs from 100 to 900.";
      if (n % 100) return "A level goes up in hundreds: 100, 200, 300 and so on.";
      if (taken.has(n)) return `There is already a ${n} Level.`;
      return "";
    } });
  const name = field({ label: "Name", help: "Optional. What the department calls this year, such "
    + "as \"Final Year\". Leave it blank for \"600 Level\"." });

  const save = button({ label: "Add the level", primary: true, busyLabel: "Adding" });
  const box = dialog({
    title: "Add a level",
    body: h("div", { class: "hw-stack" }, number, name),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(number)) return;
    setBusy(save, true);
    try {
      const made = await api.post("/api/levels", { level_number: Number(number.value()),
        name: name.value().trim() });
      box.close();
      toast(`${made.name} is added, owning device IDs ${made.id_block_start} to ${made.id_block_end}.`);
      await reload();
    } catch (error) {
      setBusy(save, false);
      number.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}

/** "258 students, 4 courses and 23 classes", from the counts the backend put on the row. */
function holdsLine(holds) {
  const parts = Object.entries(holds || {}).map(([name, count]) => `${count} ${name}`);
  if (parts.length <= 1) return parts[0] || "something";
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

function removeLevel(level, reload) {
  const go = button({ label: "Remove the level", variant: "destructive", busyLabel: "Removing" });
  const box = dialog({
    title: `Remove ${level.name}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        `Nothing is on ${level.name}: no students, no courses and no classes. Removing it takes it `
        + "off this screen and out of the import list."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        `Its device IDs, ${level.id_block_start} to ${level.id_block_end}, are not given to anybody `
        + "else. Add the level again later and it owns the same block."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "The terminal has to be connected: anybody still on it with these IDs is taken off it.")),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      await api.del(`/api/levels/${level.id}`);
      box.close();
      announce(`${level.name} is removed.`);
      toast(`${level.name} is removed.`);
      await reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError
        ? [error.message, error.hint].filter(Boolean).join(" ") : "That did not work.", "failure");
    }
  });
}

/** "120 students, 1 course and 4 classes", leaving out what there is none of. */
function countsLine(pairs) {
  const parts = pairs.filter(([n]) => n).map(([n, one, many]) => `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`);
  if (!parts.length) return "";
  return parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

// Delete roster: everything on a level, the terminal first. Asked for on 2026-09-23, with "do not
// allow deleting of rosters if not connected to the terminal", which the backend enforces: it
// empties the terminal of the level's IDs and reads it back before the register is touched.
async function clearLevel(level, reload) {
  let preview;
  try {
    preview = await api.get(`/api/levels/${level.id}/clear`);
  } catch (error) {
    toast(error instanceof ApiError ? error.message : "That did not load.", "failure");
    return;
  }
  const what = countsLine([
    [preview.students, "student", "students"], [preview.courses, "course", "courses"],
    [preview.classes, "class", "classes"], [preview.scans, "scan", "scans"],
    [preview.corrections, "correction", "corrections"],
    [preview.excusals, "excused absence", "excused absences"],
  ]) || "its roster import";
  const confirm = field({ label: `Type ${preview.name} to confirm`, autocomplete: "off",
    validate: (v) => (v.trim().toLowerCase() === preview.name.toLowerCase()
      ? "" : `Type ${preview.name} exactly.`) });
  const go = button({ label: "Delete everything", variant: "destructive",
    busyLabel: "Taking the students off the terminal" });
  const failure = h("div");
  const box = dialog({
    title: `Delete ${preview.name}'s roster and everything on it?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } }, `This deletes ${what}.`),
      h("p", { style: { margin: 0 } },
        "The students and their fingerprints are taken off the terminal first, so it has to be "
        + "switched on and connected. If it does not answer, nothing is deleted."),
      preview.open_class
        ? h("p", { class: "hw-field__error", style: { margin: 0 } },
          "A class of this level is taking attendance. End it first.")
        : null,
      h("p", { class: "hw-muted", style: { margin: 0 } },
        `${preview.name} stays, empty, so a new roster can be imported. Its old device IDs are not `
        + "given out again, so scans left in the terminal's log cannot come back as somebody else's. "
        + "A copy of the register is saved in Backups before anything is deleted."),
      confirm, failure),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    if (invalid(confirm)) return;
    setBusy(go, true);
    fill(failure);
    try {
      const done = await api.post(`/api/levels/${level.id}/clear`, { confirm: confirm.value() });
      box.close();
      const message = `${preview.name}'s roster is deleted. ${done.terminal ? `${capital(done.terminal)}.` : ""}`.trim();
      announce(message);
      toast(message);
      await reload();
    } catch (error) {
      setBusy(go, false);
      // The hint says what to do about a terminal that did not answer, so it is shown with the error.
      // In a panel of its own: shown as the confirm field's error, it told a screen reader that the
      // level's name had been typed wrong when it had not (audit, 2026-09-24).
      fill(failure, panel({ tone: "failure", title: `${preview.name}'s roster was not deleted`, role: "alert",
        body: error instanceof ApiError ? [error.message, error.hint].filter(Boolean).join(" ")
          : "That did not work." }));
    }
  });
}

function capital(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}
