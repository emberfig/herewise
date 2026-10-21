// The chrome around every signed-in screen: the rail, the top bar and the global banners.
//
// The rail is shaped by permissions, not by a fixed list of account types: an entry appears only
// when the account holds the permission behind it (docs/SCREENS.md). That is different from gating a
// control, which stays visible with its reason written on it, because a rail entry leads to a screen
// the account cannot open at all.
//
// One source of truth per screen: the device chip is set by whichever screen last spoke to the
// device, never guessed, so the chrome can no longer contradict the body (standing deviation 4).

import { api } from "./api.js";
import { icon, mark } from "./icons.js";
import { href } from "./router.js";
import { session } from "./session.js";
import { chip, clear, credit, fill, h, plural } from "./ui.js";

// A section's own screens hang under it in the rail, and appear while that section is the current
// one. Everything is then one click away from inside its section and two from anywhere, without a
// rail of nineteen rows on a 768px screen. Asked for on a first run: "why are the other settings
// listed inside, why not on the sidebar for easy access" (2026-09-21).
const NAV = [
  { id: "today", label: "Today", path: "today", permission: "register.read", icon: "today" },
  { id: "courses", label: "Courses", path: "courses", permission: "register.read", icon: "courses" },
  { id: "students", label: "Students", path: "students", permission: "students.read", icon: "students",
    children: [
      { label: "Excused absences", path: "excusals", permission: "excusal.manage" },
      { label: "Correction requests", path: "corrections", permission: "register.read" },
    ] },
  { id: "levels", label: "Levels", path: "levels", permission: "roster.manage" , icon: "levels" },
  { id: "enrolment", label: "Enrolment", path: "enrolment", permission: "enrollment.run", icon: "enrolment" },
  { id: "device", label: "Device", path: "device", permission: "device.read", icon: "device",
    children: [
      { label: "Connection check", path: "device/connection", permission: "device.read" },
      { label: "Send people", path: "device/push", permission: "device.manage" },
      { label: "Super Admins", path: "device/admins", permission: "device.manage" },
      { label: "Unmatched scans", path: "device/unmatched", permission: "device.read" },
      { label: "Clear the scans", path: "device/clear", permission: "device.manage" },
      { label: "Empty the terminal", path: "device/empty", permission: "device.manage" },
      { label: "Unlock the menu", path: "device/unlock", permission: "device.manage" },
    ] },
  { id: "settings", label: "Settings", path: "settings", permission: "settings.manage", icon: "settings",
    children: [
      { label: "Accounts", path: "settings/accounts", permission: "accounts.manage" },
      { label: "Roles", path: "settings/roles", permission: "roles.manage" },
      { label: "Activity log", path: "settings/activity", permission: "audit.read" },
      { label: "Backup", path: "settings/backup", permission: "backup.run" },
      { label: "About", path: "settings/about", permission: null },
    ] },
];

const DEVICE_WORDS = {
  unknown: "Device not checked",
  connected: "Device connected",
  unreachable: "Device not reachable",
  wrong: "Different device",
  busy: "Device busy",
};

const state = {
  device: { state: "unknown", word: DEVICE_WORDS.unknown },
  suppressed: new Set(),
  academic: null,
  currentPath: "",
  levelFoot: null,
  banners: { live: null, enrolment: null, device: null, unassigned: 0, reminders: [] },
};

let parts = null;

export function build(root) {
  const rail = h("nav", { class: "hw-rail", "aria-label": "Sections" },
    h("a", { class: "hw-rail__brand", href: href("today") }, mark({ size: 32 }), h("span", {}, "herewise")),
    h("div", { class: "hw-rail__nav" }),
    h("div", { class: "hw-rail__foot" }),
    // Its own element rather than part of the footer, because the collapsed rail hides the footer
    // and the credit is meant to be seen on every screen at every width.
    h("div", { class: "hw-rail__credit" }, credit()));
  const topbar = h("div", { class: "hw-topbar" });
  const main = h("main", { class: "hw-main", id: "main", tabindex: "-1" });
  const content = h("div", { class: "hw-content" }, topbar, main);
  const app = h("div", { class: "hw-app" }, rail, content);
  fill(root, app);
  parts = { app, rail, nav: rail.children[1], foot: rail.children[2], topbar, main, content };
  return parts;
}

export function chrome(on) {
  parts.app.dataset.chrome = on ? "full" : "none";
  if (on) renderRail();
}

export function view() {
  return parts.main;
}

/** Called by any screen that has just spoken to the device, so the chip and the body agree. */
export function setDevice(next, word) {
  state.device = { state: next, word: word || DEVICE_WORDS[next] || DEVICE_WORDS.unknown,
                   since: new Date().toISOString(), from: "screen" };
  state.banners.device = next === "unreachable" || next === "wrong" ? state.device.word : null;
  renderTopbar();
  renderBanners();
}

// -- the heartbeat -------------------------------------------------------------------------------
//
// The chip was set only by a screen that had just spoken to the terminal, so on Today, Courses or
// Students it went on saying "Device connected" long after the cable came out. This asks the
// terminal itself, on a timer. The check does not disable the terminal and answers "busy" rather
// than queueing, so it can never delay a pull or an enrolment, and it stops while the window is
// hidden because nobody is reading a chip they cannot see.

const HEARTBEAT_MS = 20000;
let heartbeat = null;
let checking = false;

async function checkDevice() {
  if (!session.account || !session.can("device.read")) return;
  if (document.hidden) return;
  // An enrolment or a pull owns the terminal and reports its own state; a heartbeat in the middle
  // of one would only argue with it. A "busy" the heartbeat heard for itself is asked again next
  // time, or the chip would stay on it until some screen happened to speak to the terminal.
  if (state.device.state === "busy" && state.device.from === "screen") return;
  // One check at a time. An unplugged terminal took thirty seconds to answer against a twenty
  // second interval, so each check found the last one still holding the terminal (2026-09-24).
  if (checking) return;
  checking = true;
  const asked = state.device;
  try {
    const seen = await api.get(`/api/devices/${state.deviceId || 1}/ping`);
    // A screen that spoke to the terminal while this was waiting knows better than this does.
    if (state.device !== asked && state.device.from === "screen") return;
    // The chip keeps its short word and the banner says the rest. The chip carried the terminal's
    // whole sentence, which wrapped the account's name onto two lines and cut off the search box.
    state.device = { state: seen.state, word: DEVICE_WORDS[seen.state] || DEVICE_WORDS.unknown,
                     since: seen.checked_at };
    state.banners.device = seen.state === "unreachable" || seen.state === "wrong"
      ? seen.detail || state.device.word : null;
    renderTopbar();
    renderBanners();
  } catch {
    // The app itself is what did not answer, which the rest of the screen will say for us.
  } finally {
    checking = false;
  }
}

export function startHeartbeat() {
  stopHeartbeat();
  checkDevice();
  heartbeat = setInterval(checkDevice, HEARTBEAT_MS);
  document.addEventListener("visibilitychange", onVisible);
}

export function stopHeartbeat() {
  if (heartbeat) clearInterval(heartbeat);
  heartbeat = null;
  document.removeEventListener("visibilitychange", onVisible);
}

// Back from a hidden window: ask at once rather than waiting out the rest of the interval, because
// the cable may have come out while nobody was looking.
function onVisible() {
  if (!document.hidden) checkDevice();
}

export function deviceState() {
  return state.device;
}

export function setRailFoot(text, detail) {
  state.levelFoot = text ? { text, detail } : null;
  renderRail();
}

export function setCurrent(id, path = "") {
  state.current = id;
  state.currentPath = path;
  renderRail();
}

/**
 * Banners a screen shows in full itself. Today lists the reminders under "Needs attention", and the
 * same sentence in the banner above it is noise rather than a second chance to read it.
 */
export function suppressBanners(kinds) {
  state.suppressed = new Set(kinds || []);
  if (parts) renderBanners();
}

export async function refresh() {
  const me = session.account;
  if (!me) return;
  // Started here rather than in main.js, because refresh() is what runs on sign-in and again after
  // every screen: whichever way somebody arrives, the terminal is being asked about from then on.
  if (!heartbeat) startHeartbeat();
  state.banners.reminders = session.reminders || [];
  const jobs = [];
  if (session.can("register.read")) {
    jobs.push(api.get("/api/sessions/unassigned")
      .then((rows) => { state.banners.unassigned = rows.length; })
      .catch(() => { state.banners.unassigned = 0; }));
    jobs.push(api.get("/api/academic-sessions")
      .then((rows) => { state.academic = rows.find((r) => r.is_current) || null; })
      .catch(() => { state.academic = null; }));
    // The footer belongs to the rail, so it is fetched with the rail rather than by whichever
    // screen happens to be open.
    jobs.push(api.get("/api/rail")
      .then((rail) => { state.levelFoot = railFoot(rail); })
      .catch(() => { state.levelFoot = null; }));
  }
  if (session.can("register.read")) {
    // A class taking attendance is shown on every screen, so leaving its screen cannot make it
    // look finished: until End is pressed nobody in it is absent (asked for on 2026-09-22).
    jobs.push(api.get("/api/live")
      .then((live) => { state.banners.live = live.open || null; })
      .catch(() => { state.banners.live = null; }));
  }
  if (session.can("enrollment.run")) {
    jobs.push(api.get("/api/enrollment/status")
      .then((status) => { state.banners.enrolment = status && status.state && status.state !== "idle" && status.state !== "finished" ? status : null; })
      .catch(() => { state.banners.enrolment = null; }));
  }
  await Promise.all(jobs);
  renderTopbar();
  renderRail();
  renderBanners();
}

function renderRail() {
  const nav = clear(parts.nav);
  for (const item of NAV) {
    if (!session.can(item.permission)) continue;
    const current = state.current === item.id;
    // The title is for the narrow rail, where the word is hidden and only the glyph is left.
    const link = h("a", { class: "hw-rail__item", href: href(item.path), title: item.label },
      icon(item.icon), h("span", {}, item.label));
    if (current) link.setAttribute("aria-current", "page");
    nav.append(link);
    // The section's own screens, while it is the section you are in.
    const children = current ? (item.children || []).filter((c) => session.can(c.permission)) : [];
    if (children.length) {
      nav.append(h("div", { class: "hw-rail__children" }, ...children.map((child) => {
        const sub = h("a", { class: "hw-rail__child", href: href(child.path) }, child.label);
        if (state.currentPath === child.path) sub.setAttribute("aria-current", "page");
        return sub;
      })));
    }
  }
  const foot = clear(parts.foot);
  if (state.levelFoot) {
    foot.append(h("b", {}, state.levelFoot.text));
    if (state.levelFoot.detail) foot.append(state.levelFoot.detail);
  } else {
    foot.append(h("b", {}, "No students yet"));
  }
}

/**
 * The register in one line. It said "No students yet" for two different situations: nobody
 * imported, and no academic session made current. It also showed one level's count when several
 * had been imported, which read as the whole register (reported on a first run, 2026-09-22).
 */
function railFoot(rail) {
  if (!rail || rail.session === false) {
    return { text: "No session yet", detail: "Settings, Academic sessions" };
  }
  if (!rail.students) return null;
  if (rail.level) return { text: `${rail.level} · ${plural(rail.students, "student")}`, detail: null };
  return { text: `${plural(rail.students, "student")}`,
           detail: `across ${plural(rail.levels, "level")}` };
}

// Only the session and the chip change once the bar is built. It used to be rebuilt whole by every
// heartbeat, every twenty seconds, which threw away the search box with whatever was being typed in
// it and the focus with it (audit, 2026-09-24). It is built again only when the account changes.
function renderTopbar() {
  const me = session.account;
  const who = me ? `${me.id}|${me.display_name}|${me.role || ""}|${session.can("students.read")}` : "";
  if (parts.topbar.dataset.builtFor !== who || !topbarParts) buildTopbar(who);
  topbarParts.session.textContent = state.academic ? `${state.academic.name} session` : "No session yet";
  const next = chip(state.device.state, state.device.word, state.device.since);
  topbarParts.chip.replaceWith(next);
  topbarParts.chip = next;
}

let topbarParts = null;

function buildTopbar(who) {
  const bar = clear(parts.topbar);
  bar.dataset.builtFor = who;
  const me = session.account;
  topbarParts = { session: h("span", { class: "hw-topbar__session" }), chip: h("span") };
  bar.append(topbarParts.session, topbarParts.chip);

  if (session.can("students.read")) {
    const search = h("input", { class: "hw-input", type: "search", id: "hw-student-search",
      placeholder: "Search a student by name or matric number", autocomplete: "off",
      "aria-label": "Search a student by name or matric number" });
    search.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const q = search.value.trim();
      location.hash = href(q ? `students?q=${encodeURIComponent(q)}` : "students");
    });
    bar.append(h("div", { class: "hw-topbar__search" }, search));
  }

  if (me) {
    const account = h("button", { class: "hw-topbar__account", type: "button",
      dataset: { action: "account" }, "aria-haspopup": "dialog" },
      h("b", {}, me.display_name), h("span", {}, me.role || ""));
    account.addEventListener("click", () => window.dispatchEvent(new CustomEvent("hw-account-menu")));
    bar.append(account);
  }
}

function renderBanners() {
  const shown = parts.content.querySelector(".hw-banner");
  const banner = highest();
  // Left alone when it would say the same thing: replaced on every heartbeat, it took focus off its
  // own link and was a new status for a screen reader to read out every twenty seconds.
  if (shown && banner && shown.outerHTML === banner.outerHTML) return;
  shown?.remove();
  if (!banner) return;
  parts.topbar.after(banner);
}

// One at a time, highest first (docs/SCREENS.md).
function highest() {
  const b = state.banners;
  const off = state.suppressed || new Set();
  if (b.live && !off.has("live")) {
    return h("p", { class: "hw-banner", dataset: { tone: "busy" }, role: "status" },
      h("span", { "aria-hidden": "true" }, "◔"),
      h("span", {}, `${b.live.code}${b.live.group ? ` ${b.live.group}` : ""}${b.live.week ? ` (${b.live.week}, class ${b.live.position})` : ""}`
        + ` is taking attendance, since ${b.live.opened_at.slice(11, 16)}: `
        + `${b.live.present} of ${b.live.students} present so far. Nobody is absent until it is ended.`),
      session.can("register.pull")
        ? h("a", { class: "hw-banner__spacer", href: href("live") }, "Open it")
        : null);
  }
  if (b.enrolment && !off.has("enrolment")) {
    return h("p", { class: "hw-banner", dataset: { tone: "busy" }, role: "status" },
      h("span", { "aria-hidden": "true" }, "◔"),
      h("span", {}, "An enrolment is running, so the device is locked. Wait for it to finish."),
      h("a", { class: "hw-banner__spacer", href: href("enrolment") }, "Open enrolment"));
  }
  if (b.device && !off.has("device")) {
    return h("p", { class: "hw-banner", dataset: { tone: "warn" }, role: "alert" },
      h("span", { "aria-hidden": "true" }, "✕"),
      // The terminal's own message ends in a full stop and the chip's word does not, so one is
      // taken off before the sentence adds its own. It read "192.168.1.201:4370.. Nothing" (2026-09-24).
      h("span", {}, `${b.device.replace(/\.+$/, "")}. Nothing can be sent to it or read from it until the cable is right.`),
      session.can("device.read")
        ? h("a", { class: "hw-banner__spacer", href: href("device/connection") }, "Run the connection check")
        : null);
  }
  if (b.unassigned && !off.has("unassigned")) {
    return h("p", { class: "hw-banner", dataset: { tone: "info" }, role: "status" },
      h("span", { "aria-hidden": "true" }, "i"),
      h("span", {}, `${plural(b.unassigned, "class", "classes")} could not be matched to a course.`),
      session.can("class.manage")
        ? h("a", { class: "hw-banner__spacer", href: href("unassigned") }, "Assign them")
        : null);
  }
  if (b.reminders.length && !off.has("reminders")) {
    const reminder = b.reminders[0];
    return h("p", { class: "hw-banner", dataset: { tone: "info" }, role: "status" },
      h("span", { "aria-hidden": "true" }, "i"),
      h("span", {}, reminder.title),
      h("a", { class: "hw-banner__spacer", href: href("device/admins") }, "Choose someone"));
  }
  return null;
}

export const RAIL = NAV;
