// Screen 28: Connection check. Mockups: Connectioncheckallpassing.png,
// Connectioncheckcableunplugged.png, Connectioncheckwrongaddress.png, Connectioncheckwrongterminal.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "28 Connection check".
//
// The rule this screen exists for: no check below the failed one shows a result. That is the bug
// that once sent someone reconfiguring a network card that was fine while the cable lay unplugged.
//
// Fixed from the mockup: every step carries its mark, tick passed, cross failed, hollow circle not
// reached. The mockup drew none at all, so on the failing frame nothing told a skipped step from a
// passed one, which is the whole purpose of the screen.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { announce, button, chain, fill, h, loadingCards, page, section, setBusy } from "../ui.js";
import { ethernetOffer, ethernetUndo, offerLead } from "./ethernet.js";

const HEADINGS = {
  cable: "The cable is not connected, or the device is off",
  pc_address: "This computer is not on the device's network",
  route: "Traffic to the device is not going down the cable",
  ping: "The device did not answer",
  port: "The device answered, but not on that port",
};

export default {
  id: "device-connection",
  nav: "device",
  title: "Connection check",
  permission: "device.read",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    // A check with the cable out waits on Windows for several seconds (5.3 s measured on
    // 2026-09-24), so the wait says what it is doing rather than showing a blank card.
    fill(host, page({ title: "Connection check", children: [
      h("p", { class: "hw-page__subtitle", role: "status" },
        "Checking the cable, this computer's address, the route and the terminal. With the cable "
        + "out this takes several seconds."),
      loadingCards(1)] }));

    const devices = await api.get("/api/devices");
    const device = devices.find((d) => d.is_default) || devices[0];
    // A change to the Ethernet comes back with the chain walked again afterwards, so the screen is
    // redrawn from that rather than asking a second time.
    const show = (result, { focus = false } = {}) => {
      ctx.shell.setDevice(result.ok ? "connected" : "unreachable");
      draw(host, device, result, run, show);
      if (focus) host.querySelector("[data-part='verdict']")?.focus();
    };
    const run = async () => {
      const result = await api.get(`/api/devices/${device.id}/diagnose`);
      show(result);
      announce(result.ok ? "Every check passed." : verdict(result).heading);
    };
    await run();
  },
};

function verdict(result) {
  const broken = result.checks.find((c) => !c.ok);
  if (!broken) {
    return { heading: "Every link is working", body:
      "The cable, this computer's address, the route, the device and its port all check out. If "
      + "attendance is still not arriving, look at the classes rather than the cable." };
  }
  // With an offer below, the panel points at it rather than repeating the steps by hand, which sit
  // under the offer for anyone who says No to Windows.
  const lead = ["pc_address", "route"].includes(broken.name) ? offerLead(result.network) : null;
  return { heading: HEADINGS[broken.name] || "The device could not be reached", body: lead || broken.message };
}

function draw(host, device, result, run, show) {
  const answer = verdict(result);
  const redraw = (answered) => show(answered.diagnosis, { focus: true });
  const offer = ethernetOffer({ network: result.network, permission: "device.manage", onDone: redraw,
    path: `/api/devices/${device.id}/network/setup` });
  const undo = ethernetUndo({ network: result.network, permission: "device.manage", onDone: redraw,
    path: `/api/devices/${device.id}/network/undo` });
  const again = button({ label: "Run it again", primary: true, busyLabel: "Checking",
    onClick: async () => { setBusy(again, true); await run(); } });

  // Every step below the broken one says it was not reached, and its own result is not shown.
  let reached = true;
  const steps = result.checks.map((check) => {
    const item = { ...check, checked: reached,
      label: LABELS[check.name] ? LABELS[check.name].replace("{port}", device.port) : check.name };
    if (!reached) {
      item.ok = false;
      item.message = "Not checked, an earlier link is broken";
    }
    if (!check.ok) reached = false;
    return item;
  });

  fill(host, page({
    title: "Connection check",
    subtitle: `${device.name} at ${device.ip}:${device.port}`,
    actions: [again],
    children: [
      // tabindex -1 so a redraw after the Ethernet is set up can put focus on the new answer rather
      // than on the top of the document; it is never a tab stop.
      h("div", { class: "hw-panel", dataset: { tone: result.ok ? "success" : "failure", part: "verdict" },
        role: "status", tabindex: "-1", style: { marginBlockEnd: "var(--hw-space-6)" } },
        h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, result.ok ? "✓" : "✕"),
        h("div", {},
          h("p", { class: "hw-panel__title" }, answer.heading),
          h("p", { class: "hw-panel__body" }, answer.body))),
      offer ? section("Put this computer on the terminal's network", offer) : null,
      // The help sits inside the chain's section, so the section's own margin separates it from the
      // Ethernet section under it (it was a sibling, and ran into that heading).
      section("The chain, in the order it is walked", chain(steps, { remedySaid: !result.ok }),
        h("p", { class: "hw-section__help" },
          "The links are checked in order, physical first. Only the first broken one is worth acting "
          + "on: the ones below it were never reached, so their result would mean nothing.")),
      undo ? section("This computer's Ethernet", undo) : null,
      result.ok ? null : h("p", {},
        h("a", { class: "hw-link", href: href("device") }, "Back to Device")),
    ],
  }));
}

const LABELS = {
  cable: "Network cable",
  pc_address: "This computer's address",
  route: "Route to the device",
  ping: "The device answers",
  port: "Port {port}",
};
