// Boot. Decides between first-run setup, sign in and the app, then hands each route its screen.

import { ApiError, api } from "./api.js";
import { define, current, go, match, start } from "./router.js";
import { session } from "./session.js";
import * as shell from "./shell.js";
import { announce, button, clear, dialog, errorState, fill, h, loadingCards } from "./ui.js";
import { appearanceChoice } from "./appearance.js";

// -- the routes ------------------------------------------------------------------------------
// Each screen is loaded the first time its route opens, so starting the app parses one screen.

define("signin", () => import("./screens/signin.js"));
define("setup", () => import("./screens/setup.js"));
define("today", () => import("./screens/today.js"));
define("courses", () => import("./screens/courses.js"));
// literal before pattern: "new" is not a course id
define("courses/new", () => import("./screens/course-new.js"));
define("courses/:id", () => import("./screens/course-redirect.js"));
define("courses/:id/sheet", () => import("./screens/course-sheet.js"));
define("courses/:id/setup", () => import("./screens/sheet-setup.js"));
define("courses/:id/classes", () => import("./screens/course-classes.js"));
define("courses/:id/students", () => import("./screens/course-students.js"));
define("courses/:id/groups", () => import("./screens/course-groups.js"));
define("courses/:id/percentages", () => import("./screens/course-percentages.js"));
define("courses/:id/eligibility", () => import("./screens/course-eligibility.js"));
define("courses/:id/progress", () => import("./screens/course-progress.js"));
define("students", () => import("./screens/students.js"));
define("students/:id", () => import("./screens/student.js"));
define("levels", () => import("./screens/levels.js"));
define("levels/:id/import", () => import("./screens/roster-import.js"));
define("excusals", () => import("./screens/excusals.js"));
define("settings", () => import("./screens/settings.js"));
define("settings/accounts", () => import("./screens/accounts.js"));
define("settings/roles", () => import("./screens/roles.js"));
define("settings/activity", () => import("./screens/activity.js"));
define("settings/backup", () => import("./screens/backup.js"));
define("settings/about", () => import("./screens/about.js"));
define("classes/:id", () => import("./screens/class-register.js"));
define("pull", () => import("./screens/pull.js"));
define("pull/:id", () => import("./screens/pull.js"));
define("unassigned", () => import("./screens/unassigned.js"));
define("corrections", () => import("./screens/corrections.js"));
define("enrolment", () => import("./screens/enrolment.js"));
define("live", () => import("./screens/live.js"));
define("device", () => import("./screens/device.js"));
define("device/connection", () => import("./screens/device-connection.js"));
define("device/admins", () => import("./screens/device-admins.js"));
define("device/push", () => import("./screens/device-push.js"));
define("device/unmatched", () => import("./screens/unmatched.js"));
define("device/usb", () => import("./screens/usb.js"));
define("device/:kind", () => import("./screens/device-guarded.js"));

const DEFAULT_ROUTE = "today";

// -- boot ------------------------------------------------------------------------------------

const root = document.getElementById("app");
shell.build(root);

window.addEventListener("hw-refresh-banners", () => { shell.refresh(); });
window.addEventListener("hw-account-menu", () => accountMenu());
window.addEventListener("hw-signed-in", async () => {
  needsSetup = false;
  await shell.refresh();
  go(pendingRoute() || DEFAULT_ROUTE, { replace: true });
  // Screen 3: the Super Admin question is asked straight after signing in, because until somebody
  // is Super Admin anyone at the keypad can open the device menu and delete everything on it.
  askAboutSuperAdmins();
});

async function askAboutSuperAdmins() {
  const reminder = (session.reminders || [])[0];
  if (!reminder || !session.can("device.manage")) return;
  const { reminderDialog } = await import("./screens/device-admins.js");
  reminderDialog(reminder, { onDone: () => shell.refresh() });
}

let pending = null;
let needsSetup = false;

function pendingRoute() {
  const next = pending;
  pending = null;
  return next;
}

async function boot() {
  const status = await api.get("/api/setup/status").catch(() => null);
  needsSetup = Boolean(status && status.needs_setup);
  if (needsSetup) {
    // The hash is set before the router starts, so nobody sees sign in flash past on a fresh install.
    window.__hwSetupStatus = status;
    if (current().path !== "setup") history.replaceState(null, "", "#/setup");
    start(route);
    return;
  }
  try {
    await session.load();
    // Also on an ordinary reload, not only after signing in: the cookie outlives the page, so the
    // top bar and the banners have to be built for someone who was already signed in.
    await shell.refresh();
  } catch (error) {
    if (!(error instanceof ApiError) || !error.signedOut) {
      clear(shell.view()).append(errorState({
        heading: "Herewise did not start.",
        body: "The app is running but did not answer. Close the window and open Herewise again.",
        onRetry: () => location.reload(),
      }));
      return;
    }
  }
  start(route);
}

async function route({ path, query }) {
  const home = session.signedIn ? DEFAULT_ROUTE : needsSetup ? "setup" : "signin";
  const wanted = path || home;
  if (needsSetup && !session.signedIn && wanted !== "setup") {
    go("setup", { replace: true });
    return;
  }
  if (!session.signedIn && !["signin", "setup"].includes(wanted)) {
    pending = wanted;
    go("signin", { replace: true });
    return;
  }
  if (session.signedIn && ["signin", "setup"].includes(wanted)) {
    go(DEFAULT_ROUTE, { replace: true });
    return;
  }

  const found = match(wanted);
  if (!found) return notFound(wanted);

  const view = shell.view();
  fill(view, loadingCards(2));
  let screen;
  try {
    screen = (await found.route.load()).default;
  } catch {
    fill(view, errorState({ heading: "That screen did not load.", onRetry: () => location.reload() }));
    return;
  }

  shell.chrome(screen.chrome !== false);
  shell.setCurrent(screen.nav || screen.id, wanted);
  shell.suppressBanners(screen.suppressBanners);
  document.title = screen.title ? `${screen.title} · Herewise` : "Herewise";

  if (screen.permission && !session.can(screen.permission)) return refused(screen);

  try {
    clear(view);
    await screen.render(view, { params: found.params, query, go, shell });
    // The rail and its banners are derived from the register, so they are read again once the
    // screen has drawn. They used to be read only at sign-in, so a lecturer who imported 258
    // students watched the rail go on saying "No students yet" until they restarted the app
    // (found on a first run, 2026-09-21). It is three small queries on a local database.
    shell.refresh();
  } catch (error) {
    if (error instanceof ApiError && error.signedOut) {
      session.clear();
      pending = wanted;
      go("signin", { replace: true });
      return;
    }
    fill(view, errorState({
      heading: `${screen.title} did not load.`,
      body: error instanceof ApiError ? error.message : undefined,
      onRetry: () => route({ path, query }),
    }));
  }
  view.focus({ preventScroll: true });
}

function refused(screen) {
  // A screen the role cannot open says which permission it needs, never which job title.
  clear(shell.view()).append(h("div", { class: "hw-page" }, errorState({
    heading: `You cannot open ${screen.title}.`,
    body: `${session.denial(screen.permission)} Ask someone whose role allows managing roles to add it.`,
  })));
  announce(session.denial(screen.permission));
}

function notFound(path) {
  clear(shell.view()).append(h("div", { class: "hw-page" }, errorState({
    heading: "That screen is not here.",
    body: `Herewise has no screen at "${path}". Use the rail on the left to get back.`,
    onRetry: () => go(DEFAULT_ROUTE),
  })));
}

function accountMenu() {
  const me = session.account;
  if (!me) return;
  const box = dialog({
    title: me.display_name,
    body: h("div", { class: "hw-stack" },
      h("dl", { class: "hw-facts" },
        h("dt", {}, "Username"), h("dd", {}, me.username),
        h("dt", {}, "Role"), h("dd", {}, me.role || "None")),
      h("p", { class: "hw-muted" },
        "Your role decides what you can do. Anything it does not allow stays on screen with the reason written on it."),
      // Here because the account menu is on every screen and needs no permission (2026-10-22).
      appearanceChoice({ legend: "Appearance on this computer", name: "appearance-menu", quiet: true })),
    actions: [
      button({ label: "Sign out", variant: "destructive", onClick: signOut }),
      h("span", { class: "hw-cardfoot__end" },
        button({ label: "About Herewise", href: "#/settings/about",
          onClick: () => box.close() }),
        button({ label: "Close", onClick: () => box.close() })),
    ],
  });
}

async function signOut() {
  await api.post("/api/logout", {}).catch(() => {});
  session.clear();
  document.querySelector("dialog.hw-dialog")?.close();
  sessionStorage.setItem("hw-signed-out", "1");
  go("signin", { replace: true });
  location.reload();
}

boot();
