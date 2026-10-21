// Screen 1: First-run setup. Mockups: SetupAcablenotconnected.png, Setupterminalconnected.png,
// SetupBreview.png, SetupCfirstroster.png, SetupDresuming.png. Fix list: docs/DESIGN-DEVIATIONS.md,
// "1 First-run setup". Backend: rollcall/firstrun.py (known gap 2, closed 2026-09-20).
//
// Five steps, and nothing is written until step 4. The answers live in setup_drafts until then, so
// the app can be closed and reopened; the password is never in the draft and is typed again here.
//
// Fixed from the mockups:
//   a failed test keeps both lines, "Your progress is saved" and "You can finish setup without the
//     terminal and connect it later", because a failure is when someone is most likely to walk away;
//   the slashed zero goes on addresses, ports and serials only, never on a count of people;
//   the two footer actions share one line, and a disabled button's reason sits beneath it alone;
//   the step indicator joins its steps with rules, so progress reads left to right.

import { ApiError, api } from "../api.js";
import { icon, mark } from "../icons.js";
import { session } from "../session.js";
import {
  invalid, announce, button, chain, clear, credit, dateAndTime, field, fill, h, panel, setBusy, uid,
} from "../ui.js";
import {
  ACCEPT, UNTICKED, columnQuestion, holdUntilTicked, previewForm, refusal, templateButton, tooBig,
  warningBoxes,
} from "./roster-file.js";
import { ethernetOffer, offerLead } from "./ethernet.js";

const STEPS = ["Your account", "Session", "Terminal", "Review", "First roster"];

const DEFAULTS = {
  display_name: "", username: "", academic_session: "", ip: "192.168.1.201", port: "4370", comm_key: "0",
};

const state = {
  step: 0,
  draft: { ...DEFAULTS },
  tested: null,          // the last POST /api/setup/test-device result
  resumed: false,
  thisComputer: [],
  levelId: null,
  file: null,
  preview: null,
  ask: null,             // "which column is which", when the roster file could not say (roster-file.js)
  importing: false,      // the other way in: another computer's data (importCard)
  look: null,            // what POST /api/setup/import/inspect said the file holds
  lookAccepted: false,
};

export default {
  id: "setup",
  title: "Set up this computer",
  chrome: false,
  permission: null,

  async render(view) {
    const status = window.__hwSetupStatus || await api.get("/api/setup/status");
    window.__hwSetupStatus = null;
    state.thisComputer = status.this_computer || [];
    if (status.resume) {
      state.draft = { ...DEFAULTS, ...status.resume.draft };
      state.step = Math.min(Number(status.resume.draft.step) || 0, 2);
      state.resumed = true;
    }

    const column = h("div", { class: "hw-column hw-column--wide" },
      h("div", { class: "hw-column__brand" }, mark({ size: 36 }), h("span", {}, "herewise")),
      h("p", { class: "hw-column__lead" }, "Set up this computer. About five minutes."),
      h("div", { id: "setup-body" }),
      credit());
    view.append(column);
    draw();
  },
};

function body() {
  return document.getElementById("setup-body");
}

function draw() {
  const host = clear(body());
  if (state.importing) {
    host.append(importCard());
    host.querySelector("input:not([hidden]), select, button")?.focus?.();
    return;
  }
  // First on the screen, before the steps: somebody who has used Herewise before should see it
  // before they start making a new register, not after.
  if (state.step === 0) host.append(importOffer());
  host.append(stepper(), h("p", { class: "hw-stepper__count" }, `Step ${state.step + 1} of ${STEPS.length}`));
  if (state.resumed && state.step === 2) host.append(resumePanel());
  host.append([accountStep, sessionStep, terminalStep, reviewStep, rosterStep][state.step]());
  host.querySelector("input, select, button")?.focus?.();
}

// -- the other way in: data from another computer ------------------------------------------------
//
// Asked for on 2026-09-23: set the real register up on one laptop, then move "all the data" to the
// lecturer's, "only the data, not the account name and password", from an optional "already used
// Herewise? Import your data" here. The file is the one Settings downloads (Download your data). The
// lecturer still makes their own account; the file's accounts come across switched off, with no
// password (rollcall/restore.py, import_data).

function importOffer() {
  const offer = panel({
    tone: "info",
    title: "Already used Herewise?",
    body: "Import your data from the other computer: students, courses, classes and attendance. "
      + "You still make your own account here.",
    children: [h("p", { style: { margin: "var(--hw-space-3) 0 0" } },
      button({ label: "Import your data",
        onClick: () => { state.importing = true; draw(); } }))],
  });
  offer.style.marginBlockEnd = "var(--hw-space-6)";
  return offer;
}

function leaveImport(event) {
  event?.preventDefault();
  if (state.look) api.del(`/api/setup/import/${state.look.token}`).catch(() => {});
  Object.assign(state, { importing: false, look: null, lookAccepted: false });
  draw();
}

function importCard() {
  if (!state.look) return chooseFile();
  if (!state.lookAccepted) return whatItHolds();
  return importAccount();
}

function chooseFile() {
  const failure = h("div");
  // Hidden outright, with the button as its only way in, as on the Backup screen: a visually hidden
  // file input is a second, unlabelled tab stop.
  const input = h("input", { type: "file", accept: ".db,application/octet-stream", hidden: true,
    "aria-label": "The data file from the other computer" });
  const choose = button({ label: "Choose the file", primary: true, busyLabel: "Reading the file",
    onClick: () => input.click() });
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setBusy(choose, true);
    clear(failure);
    try {
      state.look = await api.upload("/api/setup/import/inspect", form);
      draw();
    } catch (error) {
      setBusy(choose, false);
      input.value = "";
      failure.append(panel({ tone: "failure", title: "That file cannot be imported",
        body: error instanceof ApiError ? error.message : "Try the file again.", role: "alert" }));
    }
  });
  return card({
    heading: "Import your data",
    lead: "On the other computer, open Settings and press Download your data. Bring the file here "
      + "on a USB stick, then choose it. Nothing changes until you have seen what it holds.",
    children: [input, failure],
    back: false,
    aside: h("a", { class: "hw-link", href: "#/setup", dataset: { action: "set-up-new" },
      onClick: leaveImport }, "Set up from nothing instead"),
    primary: choose,
  });
}

function whatItHolds() {
  const held = state.look.backup;
  const count = (n) => Number(n || 0).toLocaleString("en-GB");
  const terminal = state.look.terminal;
  const go = button({ label: "Continue", primary: true,
    onClick: () => { state.lookAccepted = true; draw(); } });
  return card({
    heading: "This is the data you are bringing",
    lead: `From ${state.look.label.replace(/^the file /, "")}, as it was ${held.last_change
      ? dateAndTime(held.last_change) : "when it was saved"}.`,
    children: [
      h("dl", { class: "hw-facts" },
        h("dt", {}, "Session"), h("dd", {}, held.academic_session || "None set"),
        h("dt", {}, "Students"), h("dd", { class: "hw-tnum" }, count(held.students)),
        h("dt", {}, "Courses"), h("dd", { class: "hw-tnum" }, count(held.courses)),
        h("dt", {}, "Classes"), h("dd", { class: "hw-tnum" }, count(held.classes)),
        h("dt", {}, "Scans"), h("dd", { class: "hw-tnum" }, count(held.scans)),
        h("dt", {}, "Corrections"), h("dd", { class: "hw-tnum" }, count(held.corrections)),
        h("dt", {}, "Terminal"), h("dd", {}, terminal
          ? h("span", {}, `${terminal.name}, `, h("span", { class: "hw-ids" }, `${terminal.ip} port ${terminal.port}`))
          : "None set up")),
      panel({ tone: "info", body: "Accounts and passwords stay on the other computer. Next, you make "
        + "your own account, and it owns the register here." }),
    ],
    back: false,
    aside: h("a", { class: "hw-link", href: "#/setup", dataset: { action: "choose-another" },
      onClick: (event) => {
        event.preventDefault();
        api.del(`/api/setup/import/${state.look.token}`).catch(() => {});
        state.look = null;
        draw();
      } }, "Choose a different file"),
    primary: go,
  });
}

function importAccount() {
  const name = field({ label: "Your name", name: "display_name", value: state.draft.display_name,
    help: "Shown on the app and on every correction you sign.", autocomplete: "name",
    validate: (v) => (v.trim() ? "" : "Type the name that should appear on the register.") });
  const username = field({ label: "Username", name: "username", value: state.draft.username,
    help: "What you type to sign in. Lower case, no spaces.", autocomplete: "username",
    validate: (v) => (v.trim() ? "" : "Choose a username to sign in with.") });
  const password = field({ label: "Password", name: "password", type: "password",
    autocomplete: "new-password",
    help: "At least 8 characters. Write it down somewhere safe: nobody can reset it for you while "
      + "yours is the only account.",
    validate: (v) => (v.length >= 8 ? "" : "Use at least 8 characters.") });
  const again = field({ label: "Password again", name: "password_again", type: "password",
    autocomplete: "new-password",
    validate: (v) => (v === password.value() ? "" : "The two passwords are different.") });

  const failure = h("div");
  const finish = button({ label: "Import and finish", primary: true, busyLabel: "Bringing your data in" });
  finish.addEventListener("click", async () => {
    if (invalid(name, username, password, again)) return;
    setBusy(finish, true);
    clear(failure);
    try {
      await api.post("/api/setup/import", { token: state.look.token, username: username.value().trim(),
        display_name: name.value().trim(), password: password.value() });
      announce("Your data is here and your account is made.");
      // A full start, so the app draws its frame for a signed-in owner with the imported register.
      location.replace(`${location.pathname}#/today`);
      location.reload();
    } catch (error) {
      setBusy(finish, false);
      failure.append(panel({ tone: "failure", title: "Nothing was imported",
        body: error instanceof ApiError ? error.message : "Try again.", role: "alert" }));
    }
  });

  return card({
    heading: "Your account",
    lead: "This account owns the register on this computer. It can do everything, including making "
      + "other accounts.",
    children: [name, username,
      h("div", { class: "hw-row", style: { alignItems: "flex-start", gap: "var(--hw-space-4)" } },
        h("div", { style: { flex: "1 1 240px" } }, password),
        h("div", { style: { flex: "1 1 240px" } }, again)),
      failure],
    back: false,
    aside: h("a", { class: "hw-link", href: "#/setup", dataset: { action: "back" },
      onClick: (event) => { event.preventDefault(); state.lookAccepted = false; draw(); } }, "Back"),
    primary: finish,
    note: "This brings your data in and makes your account, in one step.",
  });
}

function stepper() {
  const list = h("ol", { class: "hw-stepper" });
  STEPS.forEach((label, index) => {
    const at = index < state.step ? "done" : index === state.step ? "current" : "todo";
    const glyph = at === "done" ? "✓" : at === "current" ? "●" : "○";
    list.append(h("li", { class: "hw-stepper__step", dataset: { state: at },
      "aria-current": at === "current" ? "step" : null },
      h("span", { class: "hw-stepper__glyph", "aria-hidden": "true", text: glyph }),
      h("span", {}, label),
      h("span", { class: "hw-visually-hidden" },
        at === "done" ? " (done)" : at === "current" ? " (this step)" : " (not started)")));
  });
  return list;
}

function resumePanel() {
  return panel({
    tone: "info",
    body: `Welcome back. Your answers so far are kept, and nothing has been created yet. You stopped at ${STEPS[state.step].toLowerCase()}.`,
    children: [h("p", { style: { margin: "var(--hw-space-2) 0 0" } },
      h("a", { class: "hw-link", href: "#/setup", dataset: { action: "start-again" },
        onClick: async (event) => {
          event.preventDefault();
          await api.del("/api/setup/draft").catch(() => {});
          Object.assign(state, { step: 0, draft: { ...DEFAULTS }, tested: null, resumed: false });
          draw();
        } }, "Start again instead"))],
  });
}

// -- the card and its footer -----------------------------------------------------------------

function card({ heading, lead = "", children = [], back = true, primary, note = "", aside = null }) {
  const foot = h("div", { class: "hw-cardfoot" },
    back ? h("a", { class: "hw-link", href: "#/setup", dataset: { action: "back" },
      onClick: (event) => { event.preventDefault(); state.step -= 1; state.resumed = false; draw(); } }, "Back") : null,
    aside,
    h("span", { class: "hw-cardfoot__end" }, primary),
    note ? h("p", { class: "hw-cardfoot__note", id: "setup-note" }, note) : null);
  return h("div", { class: "hw-card hw-stack" },
    h("h1", { class: "hw-page__title", style: { fontSize: "var(--hw-text-title)" } }, heading),
    lead ? h("p", { class: "hw-muted", style: { margin: 0, maxWidth: "62ch" } }, lead) : null,
    ...children, foot);
}

// A failed test is the moment someone is most likely to walk away, so the line saying their answers
// are kept must not be the one that gets replaced: after a failure both lines show.
const SAVED = "Your progress is saved. You can close the app and carry on later.";
const WITHOUT = "You can finish setup without the terminal and connect it later.";

function terminalNote() {
  return state.tested && !state.tested.ok ? `${SAVED} ${WITHOUT}` : SAVED;
}

function remember(extra = {}) {
  Object.assign(state.draft, extra, { step: state.step });
  api.put("/api/setup/draft", { draft: state.draft }).catch(() => {});
}

// -- step 1: the account ---------------------------------------------------------------------

function accountStep() {
  const name = field({ label: "Your name", name: "display_name", value: state.draft.display_name,
    help: "Shown on the app and on every correction you sign.", autocomplete: "name",
    validate: (v) => (v.trim() ? "" : "Type the name that should appear on the register.") });
  const username = field({ label: "Username", name: "username", value: state.draft.username,
    help: "What you type to sign in. Lower case, no spaces.", autocomplete: "username",
    validate: (v) => (v.trim() ? "" : "Choose a username to sign in with.") });

  const next = button({ label: "Continue", primary: true, onClick: () => {
    const bad = invalid(name, username);
    if (bad) return;
    state.step = 1;
    remember({ display_name: name.value().trim(), username: username.value().trim() });
    draw();
  } });

  return card({
    heading: "Your account",
    lead: "This is the first account, and it owns the register. It can do everything, including making " +
      "other accounts and deciding what each one is allowed to do.",
    children: [name, username],
    back: false,
    primary: next,
    note: "Nothing is saved until the review step.",
  });
}

// -- step 2: the academic session --------------------------------------------------------------

function sessionStep() {
  const guess = state.draft.academic_session || suggestSession();
  const value = field({ label: "Academic session", name: "academic_session", value: guess, ids: true,
    help: "The year this register belongs to. A new session starts a new set of levels.",
    validate: (v) => (v.trim().length >= 4 ? "" : "Type the session, for example 2026/2027.") });

  const next = button({ label: "Continue", primary: true, onClick: () => {
    if (invalid(value)) return;
    state.step = 2;
    remember({ academic_session: value.value().trim() });
    draw();
  } });

  return card({
    heading: "Which session is this?",
    lead: "Students keep their device ID for good, but their level belongs to one session. Next year " +
      "you make a new session and import each level again.",
    children: [value],
    primary: next,
    note: "Nothing is saved until the review step.",
  });
}

function suggestSession() {
  const now = new Date();
  const start = now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1;
  return `${start}/${start + 1}`;
}

// -- step 3: the terminal ------------------------------------------------------------------------

function terminalStep() {
  const ip = field({ label: "Terminal address", name: "ip", value: state.draft.ip, ids: true,
    validate: (v) => (/^\d{1,3}(\.\d{1,3}){3}$/.test(v.trim()) ? "" : "Type the address shown on the terminal under Menu, COMM., Ethernet.") });
  const port = field({ label: "Port", name: "port", value: state.draft.port, ids: true, inputmode: "numeric",
    validate: (v) => (Number(v) > 0 && Number(v) < 65536 ? "" : "The port is a number from 1 to 65535. The K40 uses 4370.") });
  const key = field({ label: "Comm key", name: "comm_key", value: state.draft.comm_key, ids: true,
    inputmode: "numeric", help: "Leave as 0 unless it was changed on the terminal." });
  const addresses = (list) => (list.length ? list.join(", ") : "No network adapter found");
  const here = field({ label: "This computer", readonly: true, ids: true,
    value: addresses(state.thisComputer),
    help: "Read from this computer's network card. If it is not on the terminal's network, the test "
      + "offers to set it up." });

  const result = h("div");
  const terminal = () => ({ ip: ip.value().trim(), port: Number(port.value()), comm_key: Number(key.value() || 0) });
  // After the Ethernet is set up the backend tests again, so the result shown is the one after it.
  const showTested = (tested, { focus = false } = {}) => {
    state.tested = tested;
    fill(result, testResult(tested, { body: terminal(), onDone: changed }));
    document.getElementById("setup-note").textContent = terminalNote();
    if (focus) result.querySelector("[data-part='verdict']")?.focus();
  };
  // The Ethernet was just changed, so "This computer" is read again rather than left showing the
  // addresses it had when the step opened.
  const changed = async (answer) => {
    showTested(answer.tested, { focus: true });
    try {
      state.thisComputer = (await api.get("/api/setup/status")).this_computer || [];
      const shown = here.querySelector(".hw-readonly");
      if (shown) shown.textContent = addresses(state.thisComputer);
    } catch {
      // The field keeps what it had; the test result above it is already the new one.
    }
  };
  const test = button({ label: "Test the connection", busyLabel: "Testing" });
  test.addEventListener("click", async () => {
    if (invalid(ip, port)) return;
    setBusy(test, true);
    clear(result);
    try {
      showTested(await api.post("/api/setup/test-device", terminal()));
      announce(state.tested.heading);
    } catch (error) {
      state.tested = null;
      result.append(panel({ tone: "failure", title: "The test could not run",
        body: error instanceof ApiError ? error.message : "Try again.", role: "alert" }));
    } finally {
      setBusy(test, false);
    }
  });
  if (state.tested) result.append(testResult(state.tested, { body: terminal(), onDone: changed }));

  const next = button({ label: "Continue", primary: true, onClick: () => {
    if (invalid(ip, port)) return;
    state.step = 3;
    remember({ ip: ip.value().trim(), port: port.value().trim(), comm_key: (key.value() || "0").trim() });
    draw();
  } });

  return card({
    heading: "Connect the terminal",
    lead: "Plug the network cable into the back of the terminal and into this computer, then test the " +
      "connection. You can also do this later.",
    children: [
      h("div", { class: "hw-row", style: { alignItems: "flex-start", gap: "var(--hw-space-4)" } },
        h("div", { style: { flex: "1 1 240px" } }, ip),
        h("div", { style: { flex: "1 1 240px" } }, port)),
      h("div", { class: "hw-row", style: { alignItems: "flex-start", gap: "var(--hw-space-4)" } },
        h("div", { style: { flex: "1 1 240px" } }, key),
        h("div", { style: { flex: "1 1 240px" } }, here)),
      h("div", {}, test),
      result,
    ],
    primary: next,
    note: terminalNote(),
  });
}

function testResult(result, { body = {}, onDone = null } = {}) {
  const tone = result.ok ? "success" : "failure";
  // Scans left from an earlier register are something to act on before the first roster, so they
  // get a panel of their own under the result rather than a muted line in it (firstrun._holding).
  const oldScans = Boolean(result.identity?.records);
  // A new computer meets the Ethernet problem here first, so setup offers the same fix as the
  // Connection check (0.1.16). The panel then points at it instead of repeating the steps by hand.
  const broken = result.checks.find((c) => !c.ok);
  const lead = broken && ["pc_address", "route"].includes(broken.name) ? offerLead(result.network) : null;
  const offer = onDone ? ethernetOffer({ network: result.network, path: "/api/setup/network", body, onDone }) : null;
  const answered = h("div", { class: "hw-panel", dataset: { tone, part: "verdict" }, role: "status",
                              tabindex: "-1" },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true", text: result.ok ? "✓" : "✕" }),
    h("div", { class: "hw-stack hw-stack--tight", style: { flex: "1" } },
      h("p", { class: "hw-panel__title" }, result.heading),
      result.ok ? null : h("p", { class: "hw-panel__body" }, lead || result.remedy),
      chain(result.checks, { remedySaid: !result.ok }),
      result.holding && !oldScans ? h("p", { class: "hw-muted", style: { margin: 0 } }, result.holding) : null));
  if (!oldScans && !offer) return answered;
  return h("div", { class: "hw-stack" }, answered, offer,
    oldScans ? panel({ tone: "review", title: "Old scans are still on the terminal", body: result.holding }) : null);
}

// -- step 4: the review ---------------------------------------------------------------------------

function reviewStep() {
  const password = field({ label: "Password", name: "password", type: "password",
    autocomplete: "new-password",
    help: "At least 8 characters. Write it down somewhere safe: nobody can reset it for you while " +
      "yours is the only account.",
    validate: (v) => (v.length >= 8 ? "" : "Use at least 8 characters.") });
  const again = field({ label: "Password again", name: "password_again", type: "password",
    autocomplete: "new-password",
    validate: (v) => (v === password.value() ? "" : "The two passwords are different.") });

  const failure = h("div");
  const create = button({ label: "Create and continue", primary: true, busyLabel: "Creating" });
  create.addEventListener("click", async () => {
    if (invalid(password, again)) return;
    setBusy(create, true);
    clear(failure);
    try {
      await api.post("/api/setup", {
        username: state.draft.username,
        display_name: state.draft.display_name,
        password: password.value(),
        academic_session: state.draft.academic_session,
        device: { name: "K40", ip: state.draft.ip, port: Number(state.draft.port),
          comm_key: Number(state.draft.comm_key || 0) },
      });
      await session.load();
      state.step = 4;
      announce("Your account is made. One step left.");
      draw();
    } catch (error) {
      setBusy(create, false);
      failure.append(panel({ tone: "failure", title: "Nothing was created",
        body: error instanceof ApiError ? error.message : "Try again.", role: "alert" }));
    }
  });

  const terminal = state.tested && state.tested.ok
    ? h("span", { class: "hw-confirmation" },
      h("span", { class: "hw-confirmation__glyph", "aria-hidden": "true", text: "✓" }),
      h("span", { class: "hw-ids" },
        `${state.draft.ip}, port ${state.draft.port}, comm key ${state.draft.comm_key}`),
      " · tested, answered")
    : h("span", { class: "hw-muted" },
      h("span", { class: "hw-ids" },
        `${state.draft.ip}, port ${state.draft.port}, comm key ${state.draft.comm_key}`),
      " · not tested yet. You can connect it later from Device.");

  return card({
    heading: "Check before anything is saved",
    lead: "Nothing has been written yet. Change anything by going back to its step.",
    children: [
      reviewBlock("Your account", 0, [
        h("p", { style: { margin: "0 0 var(--hw-space-2)", fontWeight: "var(--hw-weight-emphasis)" } },
          state.draft.display_name),
        h("dl", { class: "hw-facts" },
          h("dt", {}, "Username"), h("dd", {}, state.draft.username),
          h("dt", {}, "Role"), h("dd", {}, "Lecturer")),
        h("p", { class: "hw-muted", style: { margin: "var(--hw-space-2) 0 0" } },
          "Owns the register. Can do everything, and cannot be edited or deleted."),
      ]),
      reviewBlock("Session", 1, [h("p", { style: { margin: 0 } },
        h("span", { class: "hw-ids" }, state.draft.academic_session), ", the current session")]),
      reviewBlock("Terminal", 2, [h("p", { style: { margin: 0 } }, terminal)]),
      h("div", { class: "hw-row", style: { alignItems: "flex-start", gap: "var(--hw-space-4)" } },
        h("div", { style: { flex: "1 1 240px" } }, password),
        h("div", { style: { flex: "1 1 240px" } }, again)),
      failure,
    ],
    primary: create,
    note: "This creates your account and saves these settings.",
  });
}

function reviewBlock(title, step, children) {
  const id = uid("review");
  return h("section", { class: "hw-well", "aria-labelledby": id },
    h("div", { class: "hw-row hw-row--between", style: { marginBlockEnd: "var(--hw-space-3)" } },
      h("h2", { id, style: { margin: 0, fontSize: "var(--hw-text-body)", fontWeight: "var(--hw-weight-label)" } }, title),
      h("a", { class: "hw-link", href: "#/setup", dataset: { action: `change-${step}` },
        onClick: (event) => { event.preventDefault(); state.step = step; state.resumed = false; draw(); } },
        h("span", {}, "Change"), h("span", { class: "hw-visually-hidden" }, ` ${title.toLowerCase()}`))),
    ...children);
}

// -- step 5: the first roster -----------------------------------------------------------------------

function rosterStep() {
  const chosen = h("p", { class: "hw-muted", style: { margin: 0 } });
  const input = h("input", { type: "file", class: "hw-visually-hidden", accept: ACCEPT, id: "setup-roster" });
  const result = h("div", { class: "hw-stack" });

  const levels = h("select", { class: "hw-select", id: "setup-level", "aria-label": "Level" });
  let levelRows = [];
  api.get("/api/levels").then((rows) => {
    levelRows = rows;
    for (const level of rows) {
      levels.append(h("option", { value: level.id },
        `${level.name} · device IDs ${level.id_block_start} to ${level.id_block_end}`));
    }
    state.levelId = rows[0]?.id ?? null;
  }).catch(() => {});
  levels.addEventListener("change", () => { state.levelId = Number(levels.value); });

  const tooLarge = tooBig(state.file);
  const preview = button({ label: "Preview the import", primary: true, busyLabel: "Reading the file",
    reason: !state.file ? "Choose a file first." : tooLarge ? "Choose a different file." : "", align: "end" });
  input.addEventListener("change", () => {
    state.file = input.files[0] || null;
    state.ask = null;
    draw();
  });
  // The same question and the same boxes as Levels (screens/roster-file.js), because a lecturer's
  // first roster is the likeliest one to be in a shape nobody planned for.
  const send = async (choice, control) => {
    setBusy(control, true);
    try {
      const answer = await api.upload(`/api/levels/${state.levelId || levels.value}/roster/preview`,
        previewForm(state.file, choice));
      if (answer.needs_columns) {
        state.ask = answer;
        fill(result, columnQuestion(answer, send));
        announce("Herewise needs to know which column is which.");
        result.querySelector("select")?.focus();
      } else {
        state.preview = answer;
        fill(result, choice && state.ask ? columnQuestion(state.ask, send) : null, previewPanel(answer));
        (result.querySelector("[data-preview] input[type=checkbox]")
          || result.querySelector("[data-preview] button:not([disabled])"))?.focus();
      }
    } catch (error) {
      fill(result, refusal(error instanceof ApiError ? error.message : "Try another file."));
    } finally {
      setBusy(control, false);
    }
  };
  if (tooLarge) result.append(refusal(tooLarge));
  if (state.file) {
    chosen.append(`${state.file.name}, ${Math.max(1, Math.round(state.file.size / 1024))} KB chosen.`);
    if (!tooLarge) preview.addEventListener("click", () => send(null, preview));
  }
  const template = templateButton(() => levelRows.find((l) => l.id === Number(state.levelId || levels.value)));

  const skip = h("a", { class: "hw-link", href: "#/today", dataset: { action: "skip" },
    onClick: (event) => { event.preventDefault(); finish(); } }, "Skip for now");

  return card({
    heading: "Bring in your first students",
    lead: "Import a level's list of students from a spreadsheet. You can do this now or later from Levels.",
    children: [
      h("div", { class: "hw-field" },
        h("label", { class: "hw-field__label", for: "setup-level" }, "Level"), levels),
      h("div", { class: "hw-well", style: { display: "grid", justifyItems: "center", gap: "var(--hw-space-2)", padding: "var(--hw-space-8)" } },
        input,
        icon("file", { size: 28 }),
        h("label", { class: "hw-link", for: "setup-roster", style: { cursor: "pointer", fontSize: "var(--hw-text-lead)" } },
          state.file ? "Choose a different file" : "Choose the roster file"),
        h("p", { class: "hw-muted", style: { margin: 0 } },
          "A spreadsheet from the portal (.xls or .xlsx) or a CSV. Columns needed: matric number "
          + "and full name, or surname and other names."),
        chosen,
        h("span", { class: "hw-row", style: { alignItems: "center" } },
          h("span", { class: "hw-muted" }, "No list yet?"), template)),
      result,
    ],
    back: false,
    aside: skip,
    primary: preview,
    note: "Skipping takes you straight to Today. Nothing is lost.",
  });
}

function previewPanel(plan) {
  const counts = [["new", plan.new], ["to update", plan.updated], ["unchanged", plan.unchanged],
    ["skipped", plan.skipped]].filter(([, n]) => n);
  const ticks = plan.can_commit && (plan.warnings || []).length > 0;
  let confirmed = [];
  const failed = h("div");
  const commit = button({ label: "Import these students", primary: true, busyLabel: "Importing",
    reason: ticks ? UNTICKED : "" });
  const pressable = commit.matches("button") ? commit : commit.querySelector("button");
  pressable.addEventListener("click", async () => {
    setBusy(commit, true);
    fill(failed);
    try {
      await api.post(`/api/roster-imports/${plan.import_id}/commit`, { confirm: confirmed });
      finish();
    } catch (error) {
      setBusy(commit, false);
      fill(failed, refusal(error instanceof ApiError ? error.message : "The import did not finish."));
    }
  });
  const boxes = ticks ? warningBoxes(plan, (ready, codes) => {
    confirmed = codes;
    holdUntilTicked(commit, ready);
  }) : null;
  const blocked = plan.errors && plan.errors.length ? plan.errors[0] : (plan.can_commit ? "" :
    "Nothing in this file is new, so there is nothing to import.");
  const summary = `${plan.rows} rows read: ${counts.map(([label, n]) => `${n} ${label}`).join(", ")}.` +
    (!plan.id_range ? "" : plan.id_range[0] === plan.id_range[1]
      ? ` The new student takes device ID ${plan.id_range[0]}.`
      : ` New students take device IDs ${plan.id_range[0]} to ${plan.id_range[1]}.`);
  return h("div", { class: "hw-stack hw-stack--tight", dataset: { preview: "" } },
    blocked ? null : boxes,
    panel({
      // Not "Ready" while a box above still has to be ticked.
      tone: blocked ? "failure" : ticks ? "info" : "success",
      title: blocked ? "This import cannot go ahead" : ticks ? "What this file would do" : "Ready to import",
      body: blocked || summary,
      role: "status",
    }),
    failed,
    blocked ? null : commit);
}

async function finish() {
  window.dispatchEvent(new CustomEvent("hw-signed-in"));
}
