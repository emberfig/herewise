// Screen 35 Settings and screen 36 Academic sessions, with the way through to Roles, Accounts,
// the Activity log, Backup and About. Mockups: Settings.png, Settingssaved.png,
// Settingsvalueoutofrange.png, Settingsreadonly.png, Academicsessions.png.
//
// Settings are grouped by what they change, not by what they are called in the database, because
// "clock_drift_warn_seconds" is not a thing anybody came here looking for.
//
// Every value states its allowed range, and the save is disabled until something actually changes.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  keepFocusOn, invalid, actionCard, announce, button, dialog, field, fill, h, loadingCards, longDate, page, plural,
  saveFile, section, setBusy, stickyActions, table, toast,
} from "../ui.js";
import { appearanceChoice } from "../appearance.js";

// Seven settings left this screen on 2026-09-23, once attendance was taken with Start and End: the
// grace either side of a class, the three numbers for working classes out from scans, how long a
// reminder waits, and where attendance usually comes from. Their values are fixed in the code now
// (register.py, reminders.py, db.SCHEMA_V12).
const GROUPS = [
  {
    title: "Percentages and eligibility",
    fields: [
      ["attendance_threshold_percent", "Default pass mark", "%", 0, 100,
        "The starting figure for a new course. Each course can be given its own."],
    ],
  },
  {
    title: "The device",
    fields: [
      ["clock_drift_warn_seconds", "Clock drift before a warning", "seconds", 10, 3600,
        "Scans carry the device's own time, so a drifting clock files attendance in the wrong class."],
    ],
  },
  {
    title: "Backups",
    fields: [
      ["auto_backup_after_pull", "Back up after every pull", "", 0, 1,
        "A copy is taken whenever a pull stores new scans.",
        [["1", "Yes, after every pull"], ["0", "No, take them by hand"]]],
      ["backup_keep", "Copies to keep", "copies", 1, 100,
        "The oldest is deleted when there are more than this."],
    ],
  },
];

const CHOICES = {
  excused_rule: { label: "An excused absence", options: [
    ["excluded", "comes out of the student's total"],
    ["present", "counts as if they attended"],
  ], help: "A scan in an excused period still counts as present, and a correction beats both." },
  paper_size: { label: "Paper size for exports", options: [["a4", "A4"], ["letter", "Letter"]],
    help: "A4 everywhere but North America, the Philippines and parts of Latin America." },
};

export default {
  id: "settings",
  title: "Settings",
  permission: "settings.manage",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Settings", children: [loadingCards(3)] }));
    const reload = () => this.render(fill(view), ctx);
    const [settings, sessions] = await Promise.all([
      api.get("/api/settings"),
      api.get("/api/academic-sessions").catch(() => []),
    ]);
    draw(host, settings, sessions, reload);
  },
};

function draw(host, settings, sessions, reload) {
  const changed = new Map();
  const controls = [];
  // What is saved right now, kept up to date by the save itself. Each field used to be compared
  // against the value it was drawn with, so after one save, putting a setting back to what it had
  // been counted as no change: the Save button stayed dead and the only way to undo it was to
  // reload the screen (found in the audit, 2026-09-21).
  const saved = { ...settings };

  const save = button({ label: "Save the settings", primary: true, disabled: true,
    reason: "Nothing has changed yet.", busyLabel: "Saving" });
  const saveButton = save.matches("button") ? save : save.querySelector("button");
  const savedNote = h("span", { role: "status" });

  function touched(key, value) {
    if (String(value) === String(saved[key])) changed.delete(key);
    else changed.set(key, String(value));
    saveButton.disabled = changed.size === 0;
    saveButton.title = changed.size ? "" : "Nothing has changed yet.";
    fill(savedNote, changed.size
      ? h("span", { class: "hw-reason" },
        `${plural(changed.size, "change")} not saved yet.`)
      : null);
  }

  // Every setting is a row: what it is on the left, what it is set to on the right, the shape of
  // a desktop settings screen. Stacked fields with full-width boxes made this screen 3,551px tall
  // and gave a two-digit number a 1,100px box (measured 2026-09-22).
  const groups = GROUPS.map((group) => section(group.title,
    group.help ? h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-3)" } },
      group.help) : null,
    h("div", { class: "hw-card hw-rows" },
      ...group.fields.map(([key, label, unit, min, max, help, options]) => {
        const original = settings[key];
        const control = options
          ? field({
            label,
            value: String(original),
            help,
            layout: "row",
            width: "medium",
            options: options.map(([value, text]) => ({ value, label: text })),
            onInput: (event) => touched(key, event.target.value),
          })
          : field({
            label: unit ? `${label} (${unit})` : label,
            value: original,
            type: "number",
            min,
            max,
            layout: "row",
            width: "short",
            help: `${help} From ${min} to ${max}.`,
            validate: (v) => (v !== "" && Number(v) >= min && Number(v) <= max ? ""
              : `${label} must be a whole number from ${min} to ${max}.`),
            onInput: (event) => touched(key, event.target.value),
          });
        controls.push({ key, control });
        return control;
      }))));

  const choices = section("Rules", h("div", { class: "hw-card hw-rows" },
    ...Object.entries(CHOICES).map(([key, spec]) => {
      const original = settings[key];
      const control = field({ label: spec.label, value: original, help: spec.help,
        layout: "row", width: "medium",
        options: spec.options.map(([value, label]) => ({ value, label })),
        onInput: (event) => touched(key, event.target.value) });
      controls.push({ key, control });
      return control;
    })));

  saveButton.addEventListener("click", async () => {
    if (invalid(...controls.map(({ control }) => control).filter((c) => c.check))) return;
    setBusy(save, true);
    try {
      const fresh = await api.put("/api/settings", Object.fromEntries(changed));
      Object.assign(saved, fresh);
      changed.clear();
      saveButton.disabled = true;
      saveButton.title = "Nothing has changed since the last save.";
      fill(savedNote, h("span", { class: "hw-confirmation" },
        h("span", { class: "hw-confirmation__glyph", "aria-hidden": "true" }, "✓"),
        "Saved. Every screen uses these now."));
      announce("The settings are saved.");
      keepFocusOn(savedNote);
      Object.assign(settings, fresh);
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "That did not save.", "failure");
    } finally {
      setBusy(save, false);
    }
  });

  fill(host, page({
    title: "Settings",
    subtitle: "What Herewise does, for everyone on this computer",
    children: [
      yourData(),
      ...groups, choices,
      // Save sits in a bar at the foot of the window rather than beside the title: it acts on
      // every group above it, and from the last setting the title is off the screen.
      stickyActions(savedNote, save),
      academicSessions(sessions, reload),
      appearanceSection(),
      elsewhere(),
    ],
  }));
}

// -- your data, first on the screen ---------------------------------------------------------------
//
// Asked for on 2026-09-23: "the backing up data should be in settings somewhere where people can get
// access to it easily so they can back up when they want to move to another device". The Backup
// screen had it, one link down in "Elsewhere". This is the same file (GET /api/backup), and the
// other computer takes it from "Already used Herewise? Import your data" when Herewise first opens.

function yourData() {
  const go = button({ label: "Download your data", primary: true, glyph: "↓",
    permission: "backup.run", busyLabel: "Copying the register",
    onClick: () => saveFile(go, "/api/backup", "Your data") });
  return section("Your data", h("div", { class: "hw-card hw-stack hw-stack--tight" },
    h("p", { style: { margin: 0, maxWidth: "70ch" } },
      "Everything in this register in one file: students, courses, classes, scans and corrections. "
      + "Keep it as a backup, or take it to another computer. There, choose Already used Herewise? "
      + "Import your data when Herewise first opens."),
    h("p", { class: "hw-muted", style: { margin: 0, maxWidth: "70ch" } },
      "Accounts and passwords stay here: on the other computer you make your own. Fingerprints stay "
      + "on the terminal. The file holds the terminal's keypad passwords, so keep it on a USB stick "
      + "you look after, not in email."),
    h("p", { class: "hw-card__foot" }, go,
      h("a", { class: "hw-link", href: href("settings/backup"), style: { marginInlineStart: "var(--hw-space-4)" } },
        "Backups and restoring"))));
}

// -- appearance -----------------------------------------------------------------------------------
//
// Asked for on 2026-10-22. Takes effect when it is picked and is kept for this computer alone, so it
// is outside the Save bar: it is not a setting of the register, and it is also in the account menu
// for anybody whose role cannot open this screen.

function appearanceSection() {
  return section("Appearance", h("div", { class: "hw-card hw-stack hw-stack--tight" },
    appearanceChoice({ legend: "How Herewise looks on this computer", name: "appearance-settings" }),
    h("p", { class: "hw-muted", style: { margin: 0 } },
      "Changes as soon as you choose, for everyone who uses Herewise on this computer. Exported PDFs "
      + "and Excel files look the same whichever you choose.")));
}

// -- screen 36 ------------------------------------------------------------------------------------

function academicSessions(sessions, reload) {
  return section("Academic sessions",
    h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-3)" } },
      "A student keeps their device ID for good, but their level belongs to one session. Making a "
      + "new session and importing each level again is how a year turns over: returning students "
      + "keep their ID and their fingerprints, and only their level changes."),
    table({
      caption: "Academic sessions",
      rows: sessions,
      columns: [
        { label: "Session", render: (s) => h("span", { class: "hw-ids" }, s.name) },
        { label: "", render: (s) => s.is_current
          ? h("span", { class: "hw-pill", dataset: { tone: "present" } },
            h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "✓"), "Current")
          : null },
        { label: "Made", align: "end", render: (s) =>
          h("span", { class: "hw-tnum" }, longDate((s.created_at || "").slice(0, 10))) },
        { label: "", align: "end", render: (s) => s.is_current ? null
          : button({ label: "Make it current", onClick: () => makeCurrent(s, reload) }) },
      ],
    }),
    h("p", { style: { marginBlockStart: "var(--hw-space-3)" } },
      button({ label: "New session", onClick: () => newSession(reload) })));
}

function newSession(reload) {
  const now = new Date();
  const start = now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1;
  const name = field({ label: "Session", value: `${start + 1}/${start + 2}`, ids: true,
    help: "For example 2027/2028.",
    validate: (v) => (v.trim().length >= 4 ? "" : "Type the session, for example 2027/2028.") });
  const current = h("input", { type: "checkbox", checked: true });
  const save = button({ label: "Make the session", primary: true, busyLabel: "Making" });
  const box = dialog({
    title: "A new academic session",
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        "Nothing moves by itself. Import each level's new roster afterwards, and returning students "
        + "keep the device ID and the fingerprints they already have."),
      name,
      h("label", { class: "hw-choice" }, current,
        h("span", { class: "hw-choice__label" }, "Make it the current session straight away"))),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(name)) return;
    setBusy(save, true);
    try {
      await api.post("/api/academic-sessions", { name: name.value().trim(),
        make_current: current.checked });
      box.close();
      toast("The session is made.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      name.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}

async function makeCurrent(session_, reload) {
  try {
    await api.post(`/api/academic-sessions/${session_.id}/make-current`, {});
    toast(`${session_.name} is the current session.`);
    await reload();
  } catch (error) {
    toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
  }
}

function elsewhere() {
  const items = [
    ["Accounts", "settings/accounts", "accounts.manage", "Who can sign in, and what each one holds."],
    ["Roles", "settings/roles", "roles.manage", "Make a role, name it, and tick what it may do."],
    ["Activity log", "settings/activity", "audit.read", "Who did what, narrowed and exportable."],
    ["Backup", "settings/backup", "backup.run", "Take a copy of the whole register."],
    ["About", "settings/about", null, "Version, licences and what this is."],
  ];
  return section("Elsewhere", h("div", { class: "hw-grid" }, ...items.map(([label, path, permission, note]) =>
    actionCard({ label, href: href(path), note, permission }))));
}
