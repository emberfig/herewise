// Screen 27: Device. Mockups: Deviceallset.png, Devicenotreachable.png, Deviceterminal.png,
// Devicewrongterminal.png. Fix list: docs/DESIGN-DEVIATIONS.md, "27 Device".
//
// Kept from the mockup, and worth copying: when the terminal does not answer, every figure that came
// from it goes stale and says so. Serial and firmware become dashes labelled "Last known value, not
// current", the capacity gauges are drawn hatched and empty rather than holding their last fill, the
// clock reads "Unknown, the device is not answering", and every action is disabled under one reason.
// A gauge still showing 81% with the cable out would be a quiet lie.
//
// Fixed from the mockup: both "not yet on the terminal" rows put their link in the same place, and
// every warning carries its cross.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  actionCard, ago, announce, button, dateAndTime, dialog, fill, h, loadingCards, page, plural,
  section, setBusy, toast, withProgress,
} from "../ui.js";

export default {
  id: "device",
  title: "Device",
  permission: "device.read",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Device", children: [loadingCards(3)] }));
    const reload = () => this.render(fill(view), ctx);

    const devices = await api.get("/api/devices");
    const device = devices.find((d) => d.is_default) || devices[0];
    if (!device) {
      fill(host, page({ title: "Device", children: [h("div", { class: "hw-table-frame" },
        h("div", { class: "hw-state" },
          h("span", { class: "hw-state__icon", "aria-hidden": "true" }, "☰"),
          h("h2", { class: "hw-state__heading" }, "No device is set up"),
          h("p", { class: "hw-state__body" },
            "Herewise talks to one ZKTeco terminal over a network cable. Add its address to get started.")))] }));
      return;
    }

    // Drawn from what this computer already knows, then filled in when the terminal answers.
    // Reading the device takes up to ten seconds with the cable out, and a screen that sits blank
    // for ten seconds is the screen someone opens when attendance has already failed.
    const roles = await api.get(`/api/devices/${device.id}/roles`).catch(() => null);
    draw(host, device, null, null, roles, reload, ctx, { reading: true });
    try {
      const status = await api.get(`/api/devices/${device.id}/status`);
      ctx.shell.setDevice("connected");
      draw(host, device, status, null, roles, reload, ctx);
    } catch (error) {
      const failure = error instanceof ApiError ? error : new ApiError(0, null);
      ctx.shell.setDevice(failure.code === "wrong_device" ? "wrong" : "unreachable");
      draw(host, device, null, failure, roles, reload, ctx);
    }
  },
};

function draw(host, device, status, failure, roles, reload, ctx, { reading = false } = {}) {
  // What the terminal itself holds, written back into the register. Everything else on this screen
  // is a reading; this is the one action that settles a disagreement. A push that reached the
  // terminal and failed to record left this register saying 3 people were on it while the terminal
  // held 259, and nothing in the app could say so (found on a first run, 2026-09-21).
  const check = button({ label: "Check what is on it", busyLabel: "Reading the terminal",
    permission: "device.manage",
    onClick: async () => {
      setBusy(check, true);
      try {
        const found = await api.post(`/api/devices/${device.id}/sync-fingers`, {});
        const extra = (found.unknown_device_users || []).length;
        toast(`The terminal holds ${plural(found.device_users, "person", "people")} and `
          + `${plural(found.templates, "fingerprint")}. This register now says the same`
          + (extra ? `, and ${plural(extra, "device ID")} on it belong to nobody here.` : "."));
        announce("The register now matches the terminal.");
        await reload();
      } catch (error) {
        toast(error instanceof ApiError ? error.message : "The terminal did not answer.", "failure");
      } finally {
        setBusy(check, false);
      }
    } });

  const live = Boolean(status);
  const why = live ? ""
    : reading ? "Reading the device. This takes a few seconds."
      : "Needs the device. It is not answering at the moment.";

  const sync = button({
    label: "Sync the clock", permission: "device.manage", reason: why, busyLabel: "Syncing",
    primary: live && status.clock_warning ? true : false,
    onClick: async () => {
      setBusy(sync, true);
      try {
        await api.post(`/api/devices/${device.id}/sync-time`, {});
        toast("The device clock is set from this computer.");
        await reload();
      } catch (error) {
        setBusy(sync, false);
        toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
      }
    },
  });

  // For a terminal that answers the enrol command with OK and never asks for a finger, which a
  // K40 did for over an hour on 2026-09-22 until a restart cured it. Its screen goes dark for about
  // 35 seconds; nothing on it is lost.
  const restartHost = h("div");
  const restart = button({
    label: "Restart the terminal", permission: "device.manage", reason: why, busyLabel: "Restarting",
    onClick: async () => {
      setBusy(restart, true);
      restartHost.style.marginBlockEnd = "var(--hw-space-6)";
      try {
        ctx.shell.setDevice("busy");
        const answer = await withProgress(restartHost,
          api.post(`/api/devices/${device.id}/restart`, {}),
          { whileWaiting: "Restarting the terminal",
            done: (r) => `The terminal is back after ${r.back_after_seconds} seconds.` });
        ctx.shell.setDevice("connected");
        toast(`The terminal is back after ${answer.back_after_seconds} seconds.`);
        announce("The terminal is back.");
        await reload();
      } catch (error) {
        setBusy(restart, false);
        toast(error instanceof ApiError ? error.message : "The terminal did not restart.", "failure");
      }
    },
  });

  fill(host, page({
    title: "Device",
    // Derived from what this screen saw: once the terminal has answered, "5 minutes ago" from the
    // list fetched before the read would be a stale claim (found against the K40, 2026-09-21).
    subtitle: `${device.name} · ${device.ip}:${device.port}`
      + (live ? " · answering now"
        : device.last_seen_at ? ` · last answered ${ago(device.last_seen_at)}` : ""),
    actions: [check, sync, restart],
    children: [
      restartHost,
      reading ? readingPanel(device) : null,
      failure ? failurePanel(failure, device) : null,
      live && status.clock_warning ? clockAlarm(status) : null,
      identity(device, status, reading),
      capacity(status),
      cover(roles, device),
      actions(device, why, reload, ctx),
      disagreement(reload),
    ],
  }));
}

function readingPanel(device) {
  return h("div", { class: "hw-panel", dataset: { tone: "info" }, role: "status",
    style: { marginBlockEnd: "var(--hw-space-6)" } },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "i"),
    h("div", {},
      h("p", { class: "hw-panel__title" }, `Reading ${device.name}`),
      h("p", { class: "hw-panel__body" },
        "Everything below is the last value Herewise read. It updates in a few seconds, or says so "
        + "if the terminal does not answer.")));
}

function failurePanel(failure, device) {
  return h("div", { class: "hw-panel", dataset: { tone: "failure" }, role: "alert",
    style: { marginBlockEnd: "var(--hw-space-6)" } },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✕"),
    h("div", {},
      h("p", { class: "hw-panel__title" }, failure.message),
      failure.hint ? h("p", { class: "hw-panel__body" }, failure.hint) : null,
      h("p", { class: "hw-panel__body" },
        "Everything below is the last value Herewise read, not what the device says now."),
      h("p", { style: { margin: "var(--hw-space-2) 0 0" } },
        h("a", { class: "hw-link", href: href("device/connection") }, "Run the connection check"))));
}

function clockAlarm(status) {
  return h("div", { class: "hw-panel", dataset: { tone: "failure" }, role: "alert",
    style: { marginBlockEnd: "var(--hw-space-6)" } },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✕"),
    h("div", {},
      h("p", { class: "hw-panel__title" }, status.clock_warning),
      h("p", { class: "hw-panel__body" },
        "Every scan carries the device's own time, and classes are matched to it by this computer's "
        + "clock. While they disagree, attendance lands in the wrong class or in no class at all.")));
}

function identity(device, status, reading) {
  const dash = "–";
  const stale = !status;
  const rows = [
    ["Serial", status ? status.serial : (device.serial || dash)],
    ["Firmware", status ? status.firmware : (device.firmware || dash)],
    ["Platform", status ? status.platform : (device.platform || dash)],
    ["Device clock", status
      ? `${dateAndTime(status.device_time)} · ${driftWords(status.clock_drift_seconds)}`
      : "Unknown, the device is not answering"],
  ];
  return section("What is on the cable",
    h("dl", { class: "hw-facts hw-ids" }, ...rows.flatMap(([label, value]) =>
      [h("dt", {}, label), h("dd", {}, value)])),
    stale ? h("p", { class: "hw-section__help" },
      "Last known value, not current.") : null);
}

function driftWords(seconds) {
  const off = Math.abs(seconds);
  if (off < 5) return "in step with this computer";
  const mins = Math.floor(off / 60);
  const rest = off % 60;
  const span = mins ? `${plural(mins, "minute")}${rest ? ` ${rest} s` : ""}` : `${rest} s`;
  return `${span} ${seconds > 0 ? "ahead of" : "behind"} this computer`;
}

function capacity(status) {
  const gauges = [
    ["People", status && status.users, "students and staff written to the device"],
    ["Fingerprints", status && status.templates, "two per student"],
    ["Scans stored", status && status.records, "cleared only after every one is stored here"],
  ];
  return section("How full it is",
    h("div", { class: "hw-grid" }, ...gauges.map(([label, figures, note]) => gauge(label, figures, note))));
}

// -- when the register and the terminal disagree ---------------------------------------------------
//
// Asked for on a second run: a terminal emptied from its own menu leaves this register claiming
// fingerprints that are no longer on it, and there was no way to say so (2026-09-22). This removes
// a record, not a fingerprint: the templates live on the terminal and nowhere else, so if they are
// still there, Check what is on it puts these rows straight back. That is the point of offering
// both.

function disagreement(reload) {
  return section("If this register and the terminal disagree",
    h("div", { class: "hw-card hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        "Check what is on it reads the terminal and makes this register match, which is the right "
        + "answer nearly always. Forgetting the fingerprints is for the other case: the terminal "
        + "has been emptied or reset by somebody else, and you want to start enrolling again "
        + "without it claiming everybody is already done."),
      h("div", { class: "hw-row hw-row--parted" },
        button({ label: "Forget the fingerprints in this register", variant: "destructive",
          permission: "device.manage", onClick: () => forgetDialog(reload) }))));
}

function forgetDialog(reload) {
  const go = button({ label: "Forget them", variant: "destructive", busyLabel: "Forgetting" });
  const box = dialog({
    title: "Forget the fingerprints in this register?",
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        "Every student goes back to nothing enrolled, so Enrolment offers them all again."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "The terminal is not touched. No fingerprint is deleted from it: this only changes what "
        + "this register believes. If the templates are still on the terminal, Check what is on it "
        + "puts them back.")),
    actions: [button({ label: "Leave them", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      const done = await api.post("/api/fingers/forget", {});
      box.close();
      toast(`${plural(done.forgotten, "fingerprint record")} forgotten. The terminal is untouched.`);
      announce("The fingerprint records are forgotten.");
      await reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}

/** Hatched and empty when nothing was read: a gauge holding its last fill would be a quiet lie. */
function gauge(label, figures, note) {
  const known = Boolean(figures);
  const percent = known && figures.capacity ? Math.round((figures.used / figures.capacity) * 100) : 0;
  return h("div", { class: "hw-card hw-stack hw-stack--tight" },
    h("p", { class: "hw-headline__label", style: { margin: 0 } }, label),
    h("p", { class: "hw-headline__value hw-ids", style: { margin: 0 } },
      known ? `${figures.used.toLocaleString("en-GB")} of ${figures.capacity.toLocaleString("en-GB")}`
        : "–"),
    h("div", { class: "hw-gauge", dataset: known ? null : { unknown: "true" },
      role: "img", "aria-label": known ? `${percent} per cent used` : "Not read, the device is not answering" },
      known ? h("span", { class: "hw-gauge__fill", style: { width: `${percent}%` } }) : null),
    h("p", { class: "hw-muted", style: { margin: 0, fontSize: "var(--hw-text-body)" } },
      known ? `${percent}% used · ${note}` : "Not read, the device is not answering"));
}

function cover(roles, device) {
  if (!roles) return null;
  const admins = roles.admins || [];
  return section("Who can open the device menu",
    h("div", { class: "hw-card hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        h("span", { class: "hw-pill", dataset: { tone: admins.length >= 2 ? "present" : "absent" } },
          h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, admins.length >= 2 ? "✓" : "✕"),
          `${admins.length} of 2 Super Admins`)),
      ...roles.warnings.map((warning) => h("p", { class: "hw-row", style: { margin: 0, gap: "var(--hw-space-2)" } },
        h("span", { "aria-hidden": "true", style: { color: "var(--hw-absent)" } }, "✕"),
        h("span", {}, warning))),
      h("p", { class: "hw-card__foot" },
        session.can("device.manage")
          ? h("a", { class: "hw-link", href: href("device/admins") }, "Choose Super Admins")
          : h("span", { class: "hw-reason" }, session.denial("device.manage")))));
}

function actions(device, why, reload, ctx) {
  const items = [
    ["Send people to the device", "device/push", "device.manage",
      "Write a level, a course or chosen people onto the terminal."],
    ["Connection check", "device/connection", "device.read",
      "Walk the cable, the address, the route and the port, one link at a time."],
    ["Unmatched scans", "device/unmatched", "register.read",
      "Scans from device IDs nobody in the roster has."],
    ["Unlock the device menu", "device/unlock", "device.manage",
      "Lockout recovery: demote every Super Admin over the cable."],
    ["Clear the scans on the device", "device/clear", "device.manage",
      "Free space, but only after every scan is confirmed stored here."],
    ["Empty the terminal", "device/empty", "device.manage",
      "Take every person and every fingerprint off it. The scans on it stay."],
    ["Import from a USB drive", "device/usb", "register.pull",
      "For when the cable cannot be used. Waiting on a real file from this K40."],
  ];
  return section("What you can do with it",
    h("div", { class: "hw-grid" }, ...items.map(([label, path, permission, note]) =>
      actionCard({ label, href: href(path), note, permission }))));
}
