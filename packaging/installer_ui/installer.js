// The installer window's screens. packaging/installer_window.py does the work and calls
// hw.progress, hw.finished and hw.failed as it goes; this only draws what it is told.
//
// Screens: welcome (install or update), confirm (remove), working, done, removed, failed. One
// primary button on each, at the bottom right, and focus moves to the screen's title so a screen
// reader hears each change.

const screen = document.getElementById("screen");
const note = document.getElementById("note");
const actions = document.getElementById("actions");
const live = document.getElementById("live");

let info = null;
let current = null;           // the steps on the working screen, while there is one
let withDesktopShortcut = true;

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function button(label, onClick, kind = "") {
  return h("button", { type: "button", class: `button${kind ? ` button--${kind}` : ""}`, onClick }, label);
}

/** A title without its closing full stop: the sentences Python sends end in one, titles do not. */
function titled(text) {
  return String(text).replace(/\.$/, "");
}

const STAGES = {
  install: ["Welcome", "Installing", "Finished"],
  update: ["Welcome", "Updating", "Finished"],
  remove: ["Confirm", "Removing", "Finished"],
};
let stageNames = STAGES.install;

/** The rail's steps: those before ``at`` ticked, ``at`` current, a failed one crossed. */
function stages(at, failed = false) {
  document.getElementById("stages").replaceChildren(...stageNames.map((name, index) => {
    const state = index < at ? "done" : index === at ? (failed ? "failed" : "current") : "waiting";
    return h("li", { class: "stages__item", "data-state": state,
      "aria-current": index === at ? "step" : null },
    h("span", { class: "stages__dot", "aria-hidden": "true" },
      state === "done" ? "✓" : state === "failed" ? "✕" : String(index + 1)),
    name,
    state === "done" ? h("span", { class: "hw-visually-hidden" }, ", done") : null,
    state === "failed" ? h("span", { class: "hw-visually-hidden" }, ", stopped") : null);
  }));
}

function show({ nodes, foot = "", buttons = [], focus = null, busy = false, stage = 0, failed = false }) {
  current = null;
  stages(stage, failed);
  screen.replaceChildren(...nodes.filter(Boolean));
  screen.style.animation = "none";
  void screen.offsetWidth;                    // restart the arrival, once per screen
  screen.style.animation = "";
  note.textContent = foot;
  actions.replaceChildren(...buttons);
  document.querySelector(".setup").setAttribute("aria-busy", String(busy));
  (focus || screen).focus();
}

function places(rows) {
  return h("ul", { class: "places" }, rows.map(([label, path, why]) =>
    h("li", { class: "places__row" },
      h("span", { class: "places__label" }, label),
      h("span", {}, h("span", { class: "places__path" }, path), h("span", { class: "places__why" }, why)))));
}

function title(text) {
  return h("h1", { class: "setup__title", tabindex: "-1" }, text);
}

// -- installing ------------------------------------------------------------------------------------

function welcome() {
  const again = info.previous && info.previous === info.version;
  const updating = info.previous && !again;
  const heading = again ? "Install Herewise again" : updating ? "Update Herewise" : "Install Herewise";
  const lede = again
    ? `Version ${info.version} is already here. This puts a fresh copy over it, and your register stays exactly as it is.`
    : updating
      ? `From ${info.previous} to ${info.version}. Your register, and every class and scan in it, stay exactly as they are.`
      : "Everything Herewise needs is copied onto this computer. It takes under a minute.";
  const desktop = h("input", { type: "checkbox", id: "desktop", checked: true });
  const go = button(updating ? "Update" : "Install", () => install(desktop.checked), "primary");
  const heading1 = title(heading);
  show({
    nodes: [
      heading1,
      h("p", { class: "setup__lede" }, lede),
      places([
        ["Installs to", info.program_dir, "Just for you, so it needs no administrator rights."],
        ["Your register", info.register_dir, info.register_exists
          ? "Already here, and left exactly as it is."
          : "Made the first time Herewise opens. Installing or removing never touches it."],
      ]),
      h("label", { class: "choice", for: "desktop" }, desktop, "Put a shortcut on the desktop"),
    ],
    foot: "A shortcut also goes in the Start menu.",
    buttons: [button("Cancel", () => window.pywebview.api.close(), "quiet"), go],
    focus: go,
  });
  heading1.id = "heading";
}

const INSTALL_STEPS = [
  ["copy", "Copy the program"],
  ["shortcuts", "Make the shortcuts"],
  ["entry", "Add it to Installed apps"],
  ["runtime", "Check the window runtime"],
];
const REMOVE_STEPS = [
  ["check", "Check Herewise is closed"],
  ["shortcuts", "Remove the shortcuts"],
  ["entry", "Take it out of Installed apps"],
];

function working(heading, steps) {
  const fill = h("span", { class: "meter__fill" });
  const track = h("div", { class: "meter__track", role: "progressbar", "aria-label": heading,
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0" }, fill);
  const what = h("span", { class: "meter__what" }, "Getting ready");
  const percent = h("span", { class: "meter__percent hw-tnum" }, "0%");
  const items = steps.map(([key, label]) => h("li", { class: "steps__item", "data-step": key, "data-state": "waiting" },
    h("span", { class: "steps__icon", "aria-hidden": "true" }), h("span", {}, label),
    h("span", { class: "hw-visually-hidden", "data-said": "" }, ", waiting")));
  show({
    nodes: [title(heading),
      h("div", { class: "meter" }, h("div", { class: "meter__top" }, what, percent), track),
      h("ol", { class: "steps" }, items)],
    foot: "Keep this window open. It takes under a minute.",
    busy: true,
    stage: 1,
  });
  current = { steps: steps.map(([key]) => key), items, fill, track, what, percent };
}

function progress({ step, done, total, detail }) {
  if (!current) return;
  const share = total ? Math.round((done / total) * 100) : 0;
  current.fill.style.width = `${share}%`;
  current.track.setAttribute("aria-valuenow", String(share));
  current.percent.textContent = `${share}%`;
  current.what.textContent = detail;
  const at = step === "done" ? current.steps.length
    : step === "prepare" ? 0 : Math.max(0, current.steps.indexOf(step));
  current.items.forEach((item, index) => {
    const state = index < at ? "done" : index === at ? "active" : "waiting";
    if (item.dataset.state === state) return;
    item.dataset.state = state;
    item.querySelector(".steps__icon").textContent = state === "done" ? "✓" : "";
    item.querySelector("[data-said]").textContent = `, ${state === "done" ? "done" : state === "active" ? "in progress" : "waiting"}`;
    if (state === "active") live.textContent = item.textContent.replace(/, in progress$/, "");
  });
}

async function install(withDesktop) {
  withDesktopShortcut = withDesktop;
  working(info.previous && info.previous !== info.version ? "Updating Herewise" : "Installing Herewise", INSTALL_STEPS);
  try {
    await window.pywebview.api.install(withDesktop);
  } catch (error) {
    failed({ heading: "The installer stopped", body: String(error), code: "error" });
  }
}

function finished(result) {
  if (result.mode === "remove") return removed(result);
  const updated = result.replacing;
  const open = button("Open Herewise", () => window.pywebview.api.open_app(), "primary");
  const where = result.desktop ? "the Start menu or the desktop" : "the Start menu";
  show({
    nodes: [
      h("div", { class: "setup__badge setup__badge--done", "aria-hidden": "true" }, "✓"),
      title(updated ? "Herewise is updated" : "Herewise is installed"),
      h("p", { class: "setup__lede" }, updated && result.previous && result.previous !== result.version
        ? `Updated from ${result.previous} to ${result.version}. Open it from ${where}.`
        : `Open it from ${where} whenever you need it.`),
      places([
        ["Program", info.program_dir, `Version ${result.version}`],
        ["Shortcuts", result.desktop ? "Start menu and desktop" : "Start menu", "Search for Herewise to find it"],
        ["Your register", info.register_dir, updated ? "Just as you left it" : "Made the first time Herewise opens"],
      ]),
      result.runtime
        ? h("p", { class: "notice" }, h("span", { class: "notice__icon", "aria-hidden": "true" }, "i"), result.runtime)
        : null,
    ],
    foot: "",
    buttons: [button("Close", () => window.pywebview.api.close()), open],
    focus: open,
    stage: 2,
  });
  live.textContent = updated ? "Herewise is updated." : "Herewise is installed.";
}

// -- removing --------------------------------------------------------------------------------------

function confirmRemove() {
  // Cancel has the focus, not Remove: pressing Enter on a screen that deletes a program should
  // do nothing.
  const keep = button("Cancel", () => window.pywebview.api.close());
  show({
    nodes: [
      title("Remove Herewise?"),
      h("p", { class: "setup__lede" },
        "The program comes off this computer. Your register stays, with every class and scan in it."),
      places([
        ["Removes", info.program_dir, "The program, its shortcuts and its entry in Installed apps."],
        ["Keeps", info.register_dir, info.register_exists
          ? "Delete this folder yourself if you want the attendance records gone as well."
          : "There is no register here yet, so there is nothing to keep."],
      ]),
    ],
    foot: "",
    buttons: [keep, button("Remove Herewise", remove, "destructive")],
    focus: keep,
  });
}

async function remove() {
  working("Removing Herewise", REMOVE_STEPS);
  try {
    await window.pywebview.api.uninstall();
  } catch (error) {
    failed({ heading: "The uninstaller stopped", body: String(error), code: "error" });
  }
}

function removed(result) {
  const close = button("Close", () => window.pywebview.api.close(), "primary");
  show({
    nodes: [
      h("div", { class: "setup__badge setup__badge--done", "aria-hidden": "true" }, "✓"),
      title("Herewise is removed"),
      h("p", { class: "setup__lede" }, result.register_exists
        ? `Your register is still in ${result.register}. Install Herewise again and it opens just as it was.`
        : "Nothing of it is left on this computer."),
    ],
    foot: "The program folder goes as soon as this window closes.",
    stage: 2,
    buttons: [
      result.register_exists ? button("Open the register folder", () => window.pywebview.api.open_register(), "quiet") : null,
      close,
    ].filter(Boolean),
    focus: close,
  });
  live.textContent = "Herewise is removed.";
}

// -- when something stops it ------------------------------------------------------------------------

function failed(error) {
  const running = error.code === "running";
  const retry = button(info.mode === "remove" ? "Close Herewise and remove it" : "Close Herewise and continue", async () => {
    retry.disabled = true;
    retry.textContent = "Closing Herewise";
    await window.pywebview.api.close_running();
    if (info.mode === "remove") remove(); else install(withDesktopShortcut);
  }, "primary");
  const close = button(running ? "Cancel" : "Close", () => window.pywebview.api.close(), running ? "" : "primary");
  show({
    nodes: [
      // Open is not a failure, so it is not drawn as one: a pause mark rather than a red cross.
      running
        ? h("div", { class: "setup__badge setup__badge--paused", "aria-hidden": "true" }, "!")
        : h("div", { class: "setup__badge setup__badge--failed", "aria-hidden": "true" }, "✕"),
      title(titled(error.heading)),
      h("p", { class: "setup__lede" }, running
        ? "Herewise is open, and a program cannot be replaced while it is running. Nothing has been changed yet."
        : error.body),
    ],
    foot: running ? "Herewise saves every change as it happens, so closing it loses nothing." : "",
    buttons: running ? [close, retry] : [close],
    focus: running ? retry : close,
    stage: running ? 0 : 1,
    failed: !running,
  });
  live.textContent = titled(error.heading);
}

// -- what Python calls ------------------------------------------------------------------------------

window.hw = { progress, finished, failed };

document.addEventListener("keydown", (event) => {
  // Escape is Cancel wherever Cancel is offered, and does nothing while work is under way.
  if (event.key !== "Escape" || current) return;
  window.pywebview.api.close();
});

async function start() {
  info = await window.pywebview.api.info();
  document.querySelector("[data-bind=version]").textContent = `Version ${info.version}`;
  stageNames = info.mode === "remove" ? STAGES.remove
    : info.previous && info.previous !== info.version ? STAGES.update : STAGES.install;
  document.title = info.mode === "remove" ? "Remove Herewise" : "Herewise Setup";
  if (info.mode === "remove") confirmRemove(); else welcome();
}

if (window.pywebview && window.pywebview.api) start();
else window.addEventListener("pywebviewready", start, { once: true });

// Looking at the screens in a browser, with preview.js standing in for the installer. The file is
// left out of every build (installer_window.stage_ui), so this does nothing in the real window.
if (new URLSearchParams(location.search).has("preview")) import("./preview.js").then(start);
