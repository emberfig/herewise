// Putting this computer's Ethernet on the terminal's network, and taking it off again. Shared by the
// Connection check (screen 28) and setup's terminal step (screen 1): a new computer meets the
// problem in setup first, and a computer that has been in use meets it on Device (0.1.16, asked for
// on 2026-09-26 after 0.1.15 stopped at "This computer's address" on the lecturer's laptop).
//
// The backend decides everything that matters: whether to offer at all (only when the chain stopped
// at this computer's address or the route), which adapter, which address, the exact commands and
// the steps by hand (rollcall/netsetup.py). This file draws them, and says beforehand what Windows'
// own prompt will show, because a careful person shown "Windows Command Processor wants to make
// changes" with no warning presses No, and they would be right to.

import { ApiError, api } from "../api.js";
import { announce, button, dialog, fill, h, panel, setBusy, toast } from "../ui.js";

/** The verdict panel's sentence when there is an offer: the action is below, not in the panel. */
export function offerLead(network) {
  const choice = network?.offer?.choices?.[0];
  if (!choice) return null;
  if (choice.route_only) {
    return `${choice.name} has ${choice.address}, but Windows sends the terminal's traffic out through `
      + `${others(network) || "another adapter"} instead. Herewise can send it down the cable, below.`;
  }
  return `${choice.name} has no address on the terminal's network. Herewise can give it one, below, `
    + "with one question from Windows.";
}

function others(network) {
  return (network?.others || []).join(" and ");
}

function list(items, ordered = true) {
  return h(ordered ? "ol" : "ul", { class: "hw-stack hw-stack--tight", style: { margin: 0 } },
    ...items.map((item) => h("li", {}, item)));
}

function commands(lines) {
  return h("details", { class: "hw-well" },
    h("summary", {}, "What Windows will be asked to run"),
    h("p", { class: "hw-muted" },
      "Windows shows these under Show more details in its question. They change this computer's "
      + "network settings for the Ethernet adapter and nothing else."),
    list(lines.map((line) => h("code", { class: "hw-ids" }, line))));
}

/** The steps by hand, for a No to Windows' question, or an account that cannot say Yes. */
export function manualSteps(steps, note = "", { open = false } = {}) {
  if (!steps?.length) return null;
  return h("details", { class: "hw-well", open: open || null },
    h("summary", {}, "Do it by hand instead"),
    list(steps),
    note ? h("p", { class: "hw-muted", style: { marginBlockEnd: 0 } }, note) : null);
}

/**
 * The offer. `path` is where to send it: `/api/devices/{id}/network/setup` on Device, or
 * `/api/setup/network` in setup, which also needs the terminal's `body`. `onDone(answer)` redraws
 * with what the backend walked afterwards, so the chain the person sees is the one after the change.
 */
export function ethernetOffer({ network, path, body = {}, permission = null, onDone }) {
  const offer = network?.offer;
  if (!offer?.choices?.length) return null;
  let chosen = offer.choices[0];

  const outcome = h("div");
  const byHand = manualSteps(network.manual, network.manual_note);
  const lead = h("p", { style: { margin: 0 } });
  const shown = h("div");
  const describe = () => {
    lead.textContent = chosen.route_only
      ? `${chosen.name} already has ${chosen.address}. Herewise can add a route that sends only the `
        + "terminal's traffic down the cable."
      : `Herewise can give ${chosen.name} the address ${chosen.address} for the terminal`
        + (chosen.dhcp ? ", beside the one it gets automatically, so the port still works on any "
          + "other network." : ".");
    fill(shown, commands(chosen.steps));
  };
  describe();

  const pick = offer.choices.length > 1
    ? h("fieldset", { class: "hw-fieldset" },
        h("legend", {}, "Which Ethernet adapter is the cable to the terminal in?"),
        ...offer.choices.map((choice, n) => {
          const input = h("input", { type: "radio", name: "ethernet-adapter", value: choice.index,
            checked: n === 0 || null });
          input.addEventListener("change", () => { chosen = choice; describe(); });
          return h("label", { class: "hw-choice" }, input,
            h("span", {}, h("span", { class: "hw-choice__label" }, choice.name)));
        }))
    : null;

  // setBusy refuses a second press while Windows is asking; the backend refuses one too.
  const go = button({ label: "Set up this computer's Ethernet", primary: true,
    busyLabel: "Waiting for Windows", permission, onClick: () => setUp() });
  async function setUp() {
    setBusy(go, true);
    fill(outcome, null);
    announce("Windows is asking whether to allow the change.");
    try {
      const answer = await api.post(path, { ...body, adapter: chosen.index });
      const result = answer.setup;
      if (result.result === "done" || result.result === "already") {
        toast(result.message);
        announce(result.message);
        await onDone(answer);
        return;
      }
      const declined = result.result === "declined";
      showOutcome(declined ? "review" : "failure",
        declined ? "Nothing was changed" : "Windows did not make the change", result.message);
    } catch (error) {
      showOutcome("failure", "Windows was not asked",
        error instanceof ApiError ? error.message : "Herewise may have stopped. Check its window is open.");
    }
    setBusy(go, false);
  }

  function showOutcome(tone, title, message) {
    const note = panel({ tone, title, body: message, role: "alert" });
    fill(outcome, note);
    if (byHand) byHand.open = true;
    // The button is still there and keeps focus; the panel is read out as an alert.
  }

  return h("div", { class: "hw-card hw-stack", dataset: { part: "ethernet-offer" } },
    h("h3", { class: "hw-card__title", style: { margin: 0 } }, "Let Herewise set it up"),
    lead,
    pick,
    others(network)
      ? h("p", { style: { margin: 0 } },
        `${others(network)} also uses the terminal's numbers. Herewise sends only the terminal's `
        + `traffic down the cable. If websites stop opening over ${others(network)} while the cable is `
        + "in, disconnect from it for the class.")
      : null,
    h("p", { class: "hw-muted", style: { margin: 0 } },
      "Windows will then ask whether Windows Command Processor may make changes to this device. That "
      + "is Windows' own command line running the commands below: press Yes. If this Windows account "
      + "is not an administrator, it asks for an administrator's password instead."),
    h("div", {}, go),
    outcome,
    shown,
    byHand);
}

/**
 * What an undo would take off, with the button that does it. Shown on the Connection check whenever
 * an Ethernet adapter holds the terminal's address, set by Herewise or by hand, because the port may
 * be needed on another network that uses the same numbers.
 */
export function ethernetUndo({ network, path, permission = null, onDone }) {
  const held = network?.set || [];
  if (!held.length) return null;
  return h("div", { class: "hw-stack" }, ...held.map((entry) => {
    const what = [entry.addresses.length ? entry.addresses.join(", ") : null,
      entry.route ? "a route that sends the terminal's traffic down it" : null].filter(Boolean);
    return h("div", { class: "hw-card hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        `${entry.name} holds ${what.join(", and ")} for the terminal. Take it off if this port is `
        + "needed on another network that uses the same numbers, or this computer stops taking "
        + "attendance."),
      h("div", { class: "hw-row hw-row--parted" },
        button({ label: `Take it off ${entry.name}`, permission,
          onClick: () => undoDialog(entry, path, onDone) })));
  }));
}

function undoDialog(entry, path, onDone) {
  const go = button({ label: "Take it off", variant: "destructive", busyLabel: "Waiting for Windows",
    onClick: () => takeOff() });
  const failed = h("div");
  const box = dialog({
    title: `Take the terminal's address off ${entry.name}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        "Herewise will not reach the terminal down this cable until it is set up again. Windows asks "
        + "once, the same way as when it was set up."),
      commands(entry.steps),
      failed),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  async function takeOff() {
    setBusy(go, true);
    try {
      const answer = await api.post(path, { adapter: entry.index });
      const result = answer.setup;
      if (result.result === "done" || result.result === "already") {
        // Redraw only once the dialog has tidied itself up. Its tidy-up puts focus back on what
        // opened it, and that button is gone after a redraw, so it sent focus to the page after the
        // redraw had put it on the new answer (seen from the keyboard, 2026-09-27). Chrome fires
        // toggle rather than close for a dialog closed from script, so either will do.
        const closed = new Promise((resolve) => {
          box.addEventListener("close", resolve, { once: true });
          box.addEventListener("toggle", (event) => { if (event.newState === "closed") resolve(); });
        });
        box.close();
        await closed;
        await new Promise((resolve) => setTimeout(resolve, 0));
        toast(result.message);
        announce(result.message);
        await onDone(answer);
        return;
      }
      fill(failed, panel({ tone: result.result === "declined" ? "review" : "failure",
        title: "Nothing was taken off", body: result.message, role: "alert" }));
    } catch (error) {
      fill(failed, panel({ tone: "failure", title: "Windows was not asked",
        body: error instanceof ApiError ? error.message : "Try again.", role: "alert" }));
    }
    setBusy(go, false);
  }
}
