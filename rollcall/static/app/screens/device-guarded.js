// Screens 31 Unlock device menu and 32 Clear device attendance: the two guarded confirms.
// Mockups: Unlockthedevicemenu.png, Unlockmenuready.png, Unlockmenuunlocked.png,
// Unlockmenuenrollmentrunning.png, Cleartheterminalsscans.png, Scanscleared.png, Scansnotstored.png,
// Newscansarrived.png. Fix list: docs/DESIGN-DEVIATIONS.md, "31" and "32".
//
// One component, one layout: the consequence first, then the typed confirmation, then the
// destructive action on its own line at the right, never beside the way out.
//
// Fixed from the mockups:
//   a disabled control keeps the --hw-sunken treatment used everywhere else, with muted ink. The
//     mockups drew a pale red button at 2.6:1, so the disabled state was carried by colour alone;
//   every step keeps its own name and adds the reason, rather than replacing the name with it;
//   tick, cross and hollow circle, never a coloured dot: a done step and a failed step must not
//     differ by hue on the screen that decides whether a student's evidence is safe to delete.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import {
  invalid, announce, button, chain, field, fill, h, loadingCards, page, plural, section, setBusy,
  withProgress,
} from "../ui.js";

const KINDS = {
  unlock: {
    title: "Unlock the device menu",
    lead: "Lockout recovery. This demotes every Super Admin on the terminal over the cable, so the "
      + "menu opens to anyone standing at it until you choose Super Admins again.",
    action: "Unlock the menu",
    route: (id) => `/api/devices/${id}/unlock-menu`,
    done: "The menu is unlocked. Choose Super Admins again before anyone else reaches the device.",
    after: ["device/admins", "Choose Super Admins"],
  },
  // Asked for on a first run: there was no way to take people or fingerprints off the terminal
  // short of the keypad menu (2026-09-21). The scans are deliberately left alone: they are the one
  // thing on the terminal that cannot be made again.
  empty: {
    title: "Empty the terminal",
    lead: "This takes every person and every fingerprint off the terminal, one user at a time. The "
      + "scans already on it are left exactly as they are. Nobody can scan until they are sent "
      + "again and their fingers enrolled again.",
    action: "Empty the terminal",
    route: (id) => `/api/devices/${id}/empty`,
    done: "The terminal holds nobody. Its scans are untouched.",
    after: ["device/push", "Send people to the device"],
  },
  clear: {
    title: "Clear the scans on the device",
    lead: "This frees space on the terminal. Herewise pulls first, checks every scan is stored here, "
      + "and clears only if the count on the device has not moved in between.",
    action: "Clear the scans",
    route: (id) => `/api/devices/${id}/clear-attendance`,
    done: "The scans are cleared from the device. Every one of them is still stored here, apart from any "
      + "belonging to a roster you deleted.",
    after: ["device", "Back to Device"],
  },
};

export default {
  id: "device-guarded",
  nav: "device",
  title: "Device",
  permission: "device.manage",

  async render(view, { params, shell }) {
    const kind = KINDS[params.kind] ? params.kind : "unlock";
    const spec = KINDS[kind];
    this.title = spec.title;
    const host = h("div");
    view.append(host);
    fill(host, page({ title: spec.title, children: [loadingCards(1)] }));

    const devices = await api.get("/api/devices");
    const device = devices.find((d) => d.is_default) || devices[0];
    const [status, roles] = await Promise.all([
      api.get(`/api/devices/${device.id}/status`).catch((error) => ({ error })),
      api.get(`/api/devices/${device.id}/roles`).catch(() => null),
    ]);
    const live = !status.error;
    shell.setDevice(live ? "connected" : "unreachable");
    draw(host, kind, spec, device, live ? status : null, status.error, roles, shell);
  },
};

function draw(host, kind, spec, device, status, failure, roles, shell) {
  const serial = (status && status.serial) || device.serial || "";
  const result = h("div");

  const typed = field({
    label: "Type the device serial to confirm",
    name: "confirm_serial",
    ids: true,
    help: serial
      ? `It is ${serial}, printed on the back of the terminal and shown on the Device screen.`
      : "It is printed on the back of the terminal.",
    validate: (v) => (v.trim() === serial ? "" : "That is not this device's serial."),
    onInput: () => update(),
  });

  const go = button({ label: spec.action, variant: "destructive", busyLabel: "Working" });
  const goButton = go.matches("button") ? go : go.querySelector("button");
  const reason = h("p", { class: "hw-reason" });

  function update() {
    let stop = "";
    if (failure) {
      stop = failure instanceof ApiError && failure.code === "device_busy"
        ? failure.message
        : "Needs the device. It is not answering at the moment.";
    } else if (typed.value().trim() !== serial) {
      stop = "Type the serial exactly to confirm.";
    }
    goButton.disabled = Boolean(stop);
    reason.textContent = stop;
    reason.hidden = !stop;
  }

  goButton.addEventListener("click", async () => {
    if (invalid(typed)) return;
    setBusy(go, true);
    fill(result);
    try {
      // Emptying a terminal is a delete per person, about thirty seconds for a level, so the bar
      // counts what has actually come off rather than spinning.
      const done = await withProgress(result,
        api.post(spec.route(device.id), { confirm_serial: typed.value().trim() }),
        { whileWaiting: spec.title, done: spec.done });
      fill(result, finished(kind, spec, done));
      announce(spec.done);
      shell.setDevice("connected");
    } catch (error) {
      fill(result, refused(kind, error, done_steps(kind, status)));
    } finally {
      setBusy(go, false);
      update();
    }
  });

  fill(host, page({
    title: spec.title,
    subtitle: `${device.name}${serial ? ` · ${serial}` : ""}`,
    children: [
      consequence(kind, spec, device, status, roles),
      section("Confirm", h("div", { class: "hw-card hw-stack" },
        typed,
        // The destructive action on its own line at the right, with the way out below and left, so
        // the two are never a pair of buttons side by side.
        h("div", { class: "hw-cardfoot" },
          h("span", { class: "hw-cardfoot__end hw-control hw-control--end" }, go, reason),
          h("p", { class: "hw-dialog__aside" },
            h("a", { class: "hw-link", href: href(spec.after[0]) }, spec.after[1]))))),
      result,
    ],
  }));
  update();
}

function consequence(kind, spec, device, status, roles) {
  const admins = (roles && roles.admins) || [];
  return h("div", { class: "hw-panel", dataset: { tone: "failure" },
    style: { marginBlockEnd: "var(--hw-space-6)" } },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✕"),
    h("div", {},
      h("p", { class: "hw-panel__title" }, "What this does"),
      h("p", { class: "hw-panel__body" }, spec.lead),
      kind === "unlock" && admins.length
        ? h("p", { class: "hw-panel__body", style: { marginBlockStart: "var(--hw-space-2)" } },
          `${admins.map((a) => `${a.surname} ${a.other_names}`.trim() + ` (ID ${a.device_user_id})`).join(" and ")} `
          + `${admins.length === 1 ? "loses" : "lose"} the menu. Their keypad passwords are kept.`)
        : null,
      kind === "clear" && status
        ? h("p", { class: "hw-panel__body", style: { marginBlockStart: "var(--hw-space-2)" } },
          `The device holds ${status.records.used.toLocaleString("en-GB")} scans. Herewise stores `
          + "every one of them here first, and refuses if the count moves while it works.")
        : null,
      kind === "empty" && status
        ? h("p", { class: "hw-panel__body", style: { marginBlockStart: "var(--hw-space-2)" } },
          `The terminal holds ${status.users.used.toLocaleString("en-GB")} people and `
          + `${status.templates.used.toLocaleString("en-GB")} fingerprints. Both go. Its `
          + `${status.records.used.toLocaleString("en-GB")} scans stay, and so does everything in `
          + "this register.")
        : null));
}

function done_steps(kind, status) {
  if (kind !== "clear") return [];
  return [
    { name: "pull", label: "Read every scan off the device", ok: true, checked: true,
      message: "Done before anything is cleared." },
    { name: "store", label: "Store them here", ok: true, checked: true,
      message: "Done. The register keeps them whatever happens next." },
    { name: "confirm", label: "Confirm the count has not moved", ok: true, checked: true,
      message: status ? `It held ${status.records.used.toLocaleString("en-GB")} when this started.` : "" },
  ];
}

function finished(kind, spec, done) {
  if (kind === "empty") {
    return h("div", { class: "hw-panel", dataset: { tone: "success" }, role: "status" },
      h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✓"),
      h("div", { style: { flex: "1" } },
        h("p", { class: "hw-panel__title" }, spec.done),
        chain([{ name: "empty", label: "Take every person off the terminal", ok: true, checked: true,
          message: `Done. ${plural(done.removed ?? 0, "person", "people")} removed, with their `
            + "fingerprints." }]),
        h("p", { style: { margin: "var(--hw-space-3) 0 0" } },
          h("a", { class: "hw-link", href: href(spec.after[0]) }, spec.after[1]))));
  }
  const lines = kind === "clear"
    ? [...done_steps(kind, null).map((s) => ({ ...s })),
      { name: "clear", label: "Clear the scans on the device", ok: true, checked: true,
        message: `Done. ${plural(done.cleared ?? 0, "scan")} removed from the terminal.`
          + (done.from_deleted_roster
            ? ` ${plural(done.from_deleted_roster, "was", "were")} from a roster you deleted, so not kept here.`
            : "") }]
    : [{ name: "demote", label: "Demote every Super Admin over the cable", ok: true, checked: true,
        message: `Done. ${plural((done.demoted || []).length, "person", "people")} demoted.` }];
  return h("div", { class: "hw-panel", dataset: { tone: "success" }, role: "status" },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✓"),
    h("div", { style: { flex: "1" } },
      h("p", { class: "hw-panel__title" }, spec.done),
      chain(lines),
      h("p", { style: { margin: "var(--hw-space-3) 0 0" } },
        h("a", { class: "hw-link", href: href(spec.after[0]) }, spec.after[1]))));
}

/** A refusal never claims anything happened, and offers the action that actually helps. */
function refused(kind, error, earlier) {
  const message = error instanceof ApiError ? error.message : "The device did not answer.";
  const labels = { clear: "Clear the scans on the device", empty: "Empty the terminal",
    unlock: "Unlock the menu" };
  const steps = [...earlier.map((s) => ({ ...s })),
    { name: "stop", label: labels[kind] || labels.unlock, ok: false, checked: true,
      message: `${message} Nothing was changed.` }];
  const helps = kind === "clear"
    ? ["today", "Get attendance first"]
    : ["device/connection", "Run the connection check"];
  return h("div", { class: "hw-panel", dataset: { tone: "failure" }, role: "alert" },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✕"),
    h("div", { style: { flex: "1" } },
      h("p", { class: "hw-panel__title" }, message),
      kind === "clear" ? chain(steps, { remedySaid: false }) : null,
      h("p", { class: "hw-panel__body", style: { marginBlockStart: "var(--hw-space-2)" } },
        "Nothing on the device was changed."),
      h("p", { style: { margin: "var(--hw-space-3) 0 0" } },
        h("a", { class: "hw-link", href: href(helps[0]) }, helps[1]))));
}
