// Screen 39: Backup, with restore (known gap 14, built 2026-09-21). Mockups: Backup.png,
// BackupDownloaded.png, BackupNeverbackedup.png, BackupViewerrole.png. Fix list:
// docs/DESIGN-DEVIATIONS.md, "39 Backup". Contracts: GET /api/backups, GET /api/backup,
// POST /api/restore/inspect, POST /api/restore, DELETE /api/restore/{token}.
//
// Restoring replaces the whole register, so it goes in two steps and nothing changes until the
// second: look at what the backup holds beside what the register holds now, then replace it with the
// password typed again. The register as it was is kept as a copy first, so a restore can be undone
// from this same screen. The backend decides what can be restored (rollcall/restore.py); this screen
// says what it decided.
//
// Known gap 18 stands: the "What is in it" card states that keypad passwords are in the file.
//
// Fixed from the mockup: a Viewer's disabled controls give the role reason; the line about asking
// somebody else is shown only to accounts that cannot take a backup themselves.
//
// Fixed on 2026-09-21: the dates read `at` and `created_at`, which GET /api/backups has never sent
// (it sends `taken_at`), so every date on this screen was blank. Found by the screen checks.

import { ApiError, api, download } from "../api.js";
import { session } from "../session.js";
import {
  announce, button, dateAndTime, field, fill, h, loadingCards, page, panel, plural, saveFile,
  section, setBusy, table, toast,
} from "../ui.js";

export default {
  id: "backup",
  nav: "settings",
  title: "Backup",
  permission: "backup.run",

  async render(view) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Backup", children: [loadingCards(3)] }));
    const load = async () => {
      const data = await api.get("/api/backups").catch(() => ({ backups: [], folder: "" }));
      draw(host, data, { look: null }, load);
    };
    await load();
  },
};

function draw(host, data, state, reload) {
  const redraw = () => draw(host, data, state, reload);
  const last = data.backups[0] || null;
  const canRun = session.can("backup.run");

  fill(host, page({
    title: "Backup",
    subtitle: "A copy of every record on this computer, to keep somewhere safe.",
    children: [
      takeCard(last),
      whatIsInIt(),
      restoreCard(data, state, redraw, reload),
      copiesSection(data, state, redraw),
      canRun ? null : h("p", { class: "hw-reason" },
        "If you need a backup taken, ask somebody whose role allows it."),
    ],
  }));
}

// -- taking one ---------------------------------------------------------------------------------

function takeCard(last) {
  return section("", h("div", { class: "hw-card hw-stack hw-stack--tight" },
    h("h2", { class: "hw-card__title" }, "Take a backup now"),
    h("p", { class: "hw-muted", style: { margin: 0 } },
      last
        ? `The newest copy on this computer was taken ${dateAndTime(last.taken_at)}. Changes since `
          + "then are only in the register itself."
        : "No copy has been taken yet. Herewise takes one automatically after every pull that "
          + "stores new scans, and you can download one at any time."),
    h("p", { class: "hw-card__foot" },
      backupButton())));
}

function whatIsInIt() {
  return section("", h("div", { class: "hw-card hw-stack hw-stack--tight" },
    h("h2", { class: "hw-card__title" }, "What is in it"),
    h("ul", { class: "hw-bullets" },
      h("li", {}, "Every student, level, course, class, scan, correction and excused absence, and "
        + "the activity log."),
      h("li", {}, "Accounts and roles. Passwords to sign in are stored scrambled and cannot be read "
        + "back."),
      h("li", {}, "Keypad passwords for the terminal, in plain digits. Anyone with the file could "
        + "open the terminal's menu."),
      h("li", {}, "No fingerprints. They stay on the terminal.")),
    h("p", { style: { margin: 0, fontWeight: "var(--hw-weight-emphasis)" } },
      "Keep it on a flash drive locked away, not on a shared computer or in email.")));
}

// -- restoring ----------------------------------------------------------------------------------

function restoreCard(data, state, redraw, reload) {
  if (state.done) return restoredCard(state.done);
  if (state.look) return compareCard(state, redraw);

  const canRestore = session.can("backup.restore");
  // Hidden outright, not only visually: the button beside it opens it, and a visually hidden input
  // was a second, unlabelled tab stop (axe-core "label", 2026-09-21).
  const input = h("input", { type: "file", accept: ".db,application/octet-stream", hidden: true,
    id: "restore-file", "aria-label": "Backup file to restore" });
  const choose = button({ label: "Choose a backup file", busyLabel: "Reading the backup",
    permission: "backup.restore", onClick: () => input.click() });
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    await inspect(form, choose, state, redraw);
  });

  return section("", h("div", { class: "hw-card hw-stack" },
    h("h2", { class: "hw-card__title" }, "Restore from a backup"),
    h("p", { style: { margin: 0 } },
      "This replaces the whole register with the backup. Nothing changes until you have seen what "
      + "the backup holds beside what the register holds now, and typed your password. The register "
      + "as it is now is kept first, as a copy on this computer, so a restore can be undone."),
    h("div", {}, input, choose)));
}

// -- what is already on this computer -----------------------------------------------------------
//
// Its own section. It was a second heading inside the restore card, so the page had an h2 nested
// inside another h2's card and the list read as part of the restore instructions rather than as
// what is already here (2026-09-22).

function copiesSection(data, state, redraw) {
  if (state.done || state.look) return null;
  const canRestore = session.can("backup.restore");
  return section("Copies on this computer", data.backups.length
      ? table({
        caption: "Backups on this computer",
        density: "compact",
        rows: data.backups,
        columns: [
          { label: "When", render: (b) => h("span", { class: "hw-tnum" }, dateAndTime(b.taken_at)) },
          { label: "What", render: (b) => kindOf(b) },
          { label: "Size", align: "end", render: (b) =>
            h("span", { class: "hw-tnum" }, `${Math.max(1, Math.round(b.bytes / 1024)).toLocaleString("en-GB")} KB`) },
          { label: "Restore", align: "end", render: (b) => {
            const again = button({ label: "Restore this copy", variant: "quiet",
              busyLabel: "Reading the copy",
              reason: canRestore ? "" : session.denial("backup.restore"),
              onClick: async () => {
                const form = new FormData();
                form.append("name", b.name);
                await inspect(form, again, state, redraw);
              } });
            return again;
          } },
        ],
      })
      : panel({ tone: "quiet", body: "No copy has been taken on this computer yet. The first "
        + "appears after the first pull that stores new scans." }));
}

function kindOf(copy) {
  const name = copy.name || "";
  const [what, detail] =
    name.startsWith("before-restore-") ? ["Before a restore", "the register as it was"]
      : name.startsWith("before-schema-") ? ["Before an update", "taken before Herewise changed its format"]
        : name.startsWith("auto-") ? ["After a pull", "taken automatically"]
          : ["A copy", ""];
  return h("span", {}, what,
    h("span", { class: "hw-muted hw-ids", style: { display: "block" } }, name),
    detail ? h("span", { class: "hw-visually-hidden" }, `, ${detail}`) : null);
}

async function inspect(form, control, state, redraw) {
  setBusy(control, true);
  try {
    state.look = await api.upload("/api/restore/inspect", form);
    redraw();
    document.getElementById("restore-compare")?.focus();
  } catch (error) {
    setBusy(control, false);
    toast(error instanceof ApiError ? error.message : "That backup could not be read.", "failure");
  }
}

const FIGURES = [
  ["Last change recorded", (s) => s.last_change ? dateAndTime(s.last_change) : "Not recorded"],
  ["Academic session", (s) => s.academic_session || "None set"],
  ["Students", (s) => s.students.toLocaleString("en-GB")],
  ["Courses", (s) => s.courses.toLocaleString("en-GB")],
  ["Classes", (s) => s.classes.toLocaleString("en-GB")],
  ["Scans", (s) => s.scans.toLocaleString("en-GB")],
  ["Last scan", (s) => s.last_scan ? dateAndTime(s.last_scan) : "None"],
  ["Corrections", (s) => s.corrections.toLocaleString("en-GB")],
  ["Accounts that can sign in", (s) => String(s.accounts.length)],
];

function compareCard(state, redraw) {
  const look = state.look;
  const me = session.account?.username || "";
  const password = field({ label: "Your password", name: "password", type: "password",
    autocomplete: "current-password",
    help: "Typed again because this replaces everything, and the person at the keyboard should be "
      + "the person signed in." });
  const others = look.backup.accounts.slice(0, 4).join(", ");

  const replace = button({ label: "Replace the register with this backup", variant: "destructive",
    busyLabel: "Replacing the register",
    onClick: async () => {
      if (!password.value()) {
        password.showError("Type your password to replace the register.");
        password.control.focus();
        return;
      }
      setBusy(replace, true);
      try {
        const done = await api.post("/api/restore", { token: look.token, password: password.value() });
        state.look = null;
        state.done = { ...done, label: look.label, accountIn: look.your_account_in_backup, others,
          backupLastChange: look.backup.last_change };
        redraw();
        document.getElementById("restore-done")?.focus();
      } catch (error) {
        setBusy(replace, false);
        const message = error instanceof ApiError ? error.message : "The register was not replaced.";
        if (error instanceof ApiError && error.refused) password.showError(message);
        else toast(message, "failure");
      }
    } });

  const cancel = button({ label: "Choose a different backup", variant: "quiet",
    onClick: async () => {
      await api.del(`/api/restore/${look.token}`).catch(() => {});
      state.look = null;
      redraw();
    } });

  return section("", h("div", { class: "hw-card hw-stack", id: "restore-compare", tabindex: "-1" },
    h("h2", { class: "hw-card__title" }, `Restore ${look.label}?`),
    table({
      caption: "What the backup holds beside what the register holds now",
      density: "compact",
      rows: FIGURES,
      columns: [
        { label: "What it holds", render: ([label]) => label },
        { label: "In the backup", align: "end",
          render: ([, read]) => h("span", { class: "hw-tnum" }, read(look.backup)) },
        { label: "In the register now", align: "end",
          render: ([, read]) => h("span", { class: "hw-tnum" }, read(look.current)) },
      ],
    }),
    panel({ tone: "review", title: "What happens when you replace it", children: [
      h("ul", { class: "hw-bullets" },
        h("li", {}, look.backup.last_change
          ? `The register goes back to how it was on ${dateAndTime(look.backup.last_change)}. `
            + "Anything recorded since then is not in it."
          : "The register becomes exactly what the backup holds."),
        h("li", {}, "The register as it is now is kept first, as a copy on this computer. Restoring "
          + "that copy undoes this."),
        h("li", {}, look.your_account_in_backup
          ? `Everyone is signed out. Sign in again as ${me}, with the password that account had `
            + "when the backup was taken."
          : `Everyone is signed out, and your account, ${me}, is not in this backup. Sign in with `
            + `one that is: ${others}.`),
        h("li", {}, "The terminal is not changed. If people were sent to it or scans were cleared "
          + "after the backup was taken, get attendance and check the Device screen afterwards.")),
    ] }),
    password,
    h("div", { class: "hw-cardfoot" }, cancel, h("span", { class: "hw-cardfoot__end" }, replace))));
}

function restoredCard(done) {
  const restored = done.restored || {};
  return section("", h("div", { class: "hw-card hw-stack", id: "restore-done", tabindex: "-1",
    role: "status" },
    // "As it was on" is the backup's own last change, read before the restore: the restored
    // register's newest entry is the restore itself, which said the wrong time when first tried.
    panel({ tone: "success", title: "The register has been replaced",
      body: `It now holds ${done.label}: ${plural(restored.students || 0, "student")} and `
        + `${plural(restored.scans || 0, "scan")}, as it was on `
        + `${done.backupLastChange ? dateAndTime(done.backupLastChange) : "the day it was taken"}.` }),
    h("p", { style: { margin: 0 } },
      `The register as it was before is kept on this computer as ${done.kept}. It is listed with `
      + "the other copies on this screen, and restoring it undoes this."),
    h("p", { style: { margin: 0 } }, done.accountIn
      ? "Everyone has been signed out. Sign in again with the password your account had when the "
        + "backup was taken."
      : `Everyone has been signed out. Your account is not in this backup, so sign in with one that `
        + `is: ${done.others}.`),
    h("p", { class: "hw-card__foot" },
      button({ label: "Sign in again", primary: true, onClick: () => {
        location.hash = "#/signin";
        location.reload();
      } }))));
}


function backupButton() {
  const go = button({ label: "Download your data", primary: true, glyph: "↓",
    permission: "backup.run", busyLabel: "Copying the register",
    onClick: () => saveFile(go, "/api/backup", "The backup") });
  return go;
}
