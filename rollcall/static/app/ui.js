// The pieces every screen is built from, and the rules that would otherwise be re-decided 44 times.
//
// Three of those rules come straight from docs/COMPONENT-GUIDE.md ("Forms, everywhere") and are
// implemented here rather than per screen:
//   the save action is disabled until something actually changes, and says so;
//   it takes a loading state and cannot be pressed twice;
//   a save confirms itself in words, because silence is not confirmation.
// And one from docs/SCREENS.md: a control the role does not allow is visible and disabled with the
// reason written beneath it, never hidden.

import { ApiError, api, download } from "./api.js";
import { session } from "./session.js";

// -- building elements ---------------------------------------------------------------------------

/** h("p", {class: "hw-muted"}, "text") . Text children are set as text, never parsed as HTML, so a
 *  name with an ampersand in it survives. */
export function h(tag, props = null, ...kids) {
  const el = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") el.textContent = value;
      else if (key === "html") el.innerHTML = value;           // only for generated glyph markup
      // Object.assign would write data-width="null" for a key that was left out, and a selector
      // matching [data-width] would then catch every field.
      else if (key === "dataset") {
        for (const [name, item] of Object.entries(value)) {
          if (item !== null && item !== undefined && item !== false) el.dataset[name] = item;
        }
      }
      else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
      else if (key.startsWith("on") && typeof value === "function") {
        el.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) el.setAttribute(key, "");
      else el.setAttribute(key, String(value));
    }
  }
  append(el, kids);
  return el;
}

export function append(parent, kids) {
  for (const kid of kids.flat(4)) {
    if (kid === null || kid === undefined || kid === false) continue;
    parent.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return parent;
}

export function frag(...kids) {
  return append(document.createDocumentFragment(), kids);
}

export function clear(node) {
  // Replacing what has focus sent focus to the top of the document: End attendance, Cancel or Delete
  // redrew the screen under the control focus was about to go back to. It goes to the screen itself
  // instead, which is where arriving on a screen puts it (audit, 2026-09-24).
  const active = document.activeElement;
  const had = active && active !== document.body && active !== node && node.contains(active);
  node.replaceChildren();
  if (had) node.closest?.("main[tabindex]")?.focus({ preventScroll: true });
  return node;
}

/**
 * Clear a container and put fresh children in it. Always this rather than `clear(x).append(...)`:
 * the DOM's own append turns a null child into the text "null", and a screen built from
 * conditionals is full of them. It printed "nullnull" above the class register's counts.
 */
export function fill(node, ...kids) {
  return append(clear(node), kids);
}

// -- the studio's credit -------------------------------------------------------------------------

/**
 * Herewise ships under the studio's name, and says so on every screen (owner, 2026-09-21). The link
 * is the site's root only: a link inside installed software can never be changed for the copies
 * already out there, and StudyPomo's shipped privacy link is the proof that a deeper path becomes a
 * promise (the studio's vault). No person is named, only the studio.
 *
 * target="_blank" is what sends it to the person's own browser from the app window
 * (rollcall/window.py) instead of replacing the register with a website. Opening the link is the
 * person's choice; the app itself still fetches nothing from outside.
 */
export const STUDIO = { name: "Emberfig", url: "https://emberfig.com/" };

export function studioLink() {
  return h("a", { class: "hw-credit__link", href: STUDIO.url, target: "_blank",
    rel: "noopener noreferrer" },
  STUDIO.name, h("span", { class: "hw-visually-hidden" }, " (opens in your browser)"));
}

export function credit() {
  return h("p", { class: "hw-credit" }, "Made by ", studioLink());
}

let counter = 0;
export function uid(prefix = "hw") {
  counter += 1;
  return `${prefix}-${counter}`;
}

// -- text ----------------------------------------------------------------------------------------

// A direct-entry student has no matric number yet and reads "DE" wherever the number would go, the
// lecturer's own convention (2026-09-23). Stored as nothing, so it can never clash with a real number;
// rollcall/names.py has the same rule for exports.
export const DIRECT_ENTRY = "DE";

export function matricText(value) {
  return value || DIRECT_ENTRY;
}

export function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many ?? `${one}s`}`;
}

export function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
}

export function longDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

/** "Sunday 20 September", for a date inside the current session, where the year adds nothing. */
export function dayAndMonth(iso) {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })
    .replace(",", "");
}

export function clockTime(iso) {
  if (!iso) return "";
  return iso.length <= 8 ? iso.slice(0, 5) : iso.slice(11, 16);
}

export function dateAndTime(iso) {
  if (!iso) return "";
  return `${shortDate(iso)}, ${clockTime(iso)}`;
}

/** "2 hours ago", for the last pull. Plain words, never a bare timestamp the reader has to subtract. */
export function ago(iso) {
  if (!iso) return "never";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return iso;
  const seconds = Math.round((Date.now() - then.getTime()) / 1000);
  if (seconds < 90) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${plural(minutes, "minute")} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${plural(hours, "hour")} ago`;
  const days = Math.round(hours / 24);
  if (days < 14) return `${plural(days, "day")} ago`;
  return `on ${shortDate(iso)}`;
}

// -- status ----------------------------------------------------------------------------------------
// Glyph, word and colour together. Never colour alone, on any screen (docs/DESIGN-BRIEF.md).

export const STATUS = {
  present: { glyph: "✓", word: "Present", tone: "present" },
  marked_present: { glyph: "✓", word: "Present, corrected", tone: "present" },
  absent: { glyph: "✕", word: "Absent", tone: "absent" },
  marked_absent: { glyph: "✕", word: "Absent, corrected", tone: "absent" },
  excused: { glyph: "E", word: "Excused", tone: "excused" },
  review: { glyph: "?", word: "Review", tone: "review" },
  not_held: { glyph: "–", word: "No class", tone: "neutral" },
  upcoming: { glyph: "○", word: "Upcoming", tone: "neutral" },
  cancelled: { glyph: "✕", word: "Cancelled", tone: "neutral" },
};

export function pill(state, { word, glyph, tone } = {}) {
  const spec = STATUS[state] || { glyph: "○", word: state, tone: "neutral" };
  return h("span", { class: "hw-pill", dataset: { tone: tone || spec.tone } },
    h("span", { class: "hw-pill__glyph", "aria-hidden": "true", text: glyph || spec.glyph }),
    word || spec.word);
}

/**
 * `since` is when the state was last true, so "connected" is a claim with a time on it rather than
 * a colour that stays green after the cable comes out (reported on a second run, 2026-09-22).
 */
export function chip(state, word, since = null) {
  const glyph = { connected: "●", busy: "◔", unreachable: "✕", wrong: "✕", unknown: "○" }[state] || "○";
  return h("span", { class: "hw-chip", dataset: { state },
                     title: since ? `Checked ${ago(since)}` : null },
    h("span", { class: "hw-chip__glyph", "aria-hidden": "true", text: glyph }), word,
    since ? h("span", { class: "hw-chip__since" }, ago(since)) : null);
}


// -- buttons and gating ----------------------------------------------------------------------------

/**
 * A button that knows about permissions. Pass `permission` and, if the account does not hold it,
 * the button renders visible and disabled with the backend's own refusal written beneath it, so an
 * operator can see what to ask for. Pass `reason` for any other refusal (self-correction, a device
 * that is busy, a feature waiting on a real file).
 *
 * Returns the wrapper when there is a reason to show, and the bare button otherwise, so callers can
 * always append the result.
 */
export function button({ label, onClick, primary = false, variant = "", permission = null, reason = "",
                         disabled = false, busyLabel = "", type = "button", href = null,
                         align = "start", glyph = "", id = "" } = {}) {
  let why = reason;
  if (!why && permission && !session.can(permission)) why = session.denial(permission);
  const off = disabled || Boolean(why);
  const classes = ["hw-button"];
  if (primary) classes.push("hw-button--primary");
  if (variant) classes.push(`hw-button--${variant}`);

  const el = href && !off
    ? h("a", { class: classes.join(" "), href, id: id || null })
    : h("button", { class: classes.join(" "), type, disabled: off || null, id: id || null });
  if (glyph) el.append(h("span", { "aria-hidden": "true", text: glyph }));
  el.append(label);
  // Always bound, even when the button starts disabled: `disabled` is what stops it firing, and a
  // button that is switched on later would otherwise be dead for good. Found on the correction
  // drawer, whose Save starts disabled until a mark is chosen.
  if (onClick) el.addEventListener("click", onClick);
  el.dataset.action = label;

  if (busyLabel) el._busyLabel = busyLabel;
  if (!why) return el;

  const note = h("p", { class: "hw-reason", id: uid("reason") }, why);
  el.setAttribute("aria-describedby", note.id);
  el.title = why;
  return h("span", { class: `hw-control${align === "end" ? " hw-control--end" : ""}` }, el, note);
}

/**
 * A row of buttons with any reasons gathered underneath them, rather than each disabled button
 * carrying its own reason inline. Inline, a 44ch reason makes its button's column 44ch wide: on
 * Accounts that put three buttons on three lines and made the owner's row 224px tall against 55px
 * for the others (measured 2026-09-22). The reasons are still written and still tied to their
 * button by aria-describedby, which is the rule; only where they sit changes.
 */
export function actionRow(...controls) {
  // A leading { parted: true } keeps a destructive control away from a primary one in the same row.
  const options = controls.length && controls[0] && controls[0].parted === true ? controls.shift() : {};
  const buttons = [];
  const reasons = [];
  for (const control of controls.flat(3)) {
    if (!control) continue;
    if (control.classList?.contains("hw-control")) {
      buttons.push(control.firstElementChild);
      reasons.push(control.lastElementChild);
    } else {
      buttons.push(control);
    }
  }
  return h("div", { class: "hw-actions" },
    h("div", { class: `hw-row${options.parted ? " hw-row--parted" : ""}`,
               style: { justifyContent: "flex-end" } }, ...buttons), ...reasons);
}

// -- how far along something is --------------------------------------------------------------------
//
// Sending a level to the terminal takes about thirty seconds and emptying it about the same, and
// until now the only sign was a button that said "Sending". Asked for on a second run: a bar while
// it runs, and a plain statement when it is done (2026-09-22).
//
// The bar is only drawn where the backend knows the total. A bar that moves without knowing what it
// is measuring says "this much is left" and does not know, which is worse than no bar: work with no
// total gets the sentence and a barber's pole instead.

export function progress({ what = "Working", detail = "", done = 0, total = null } = {}) {
  const known = typeof total === "number" && total > 0;
  const percent = known ? Math.min(100, Math.round((done / total) * 100)) : null;
  return h("div", { class: "hw-progress", role: "status", "aria-live": "polite" },
    h("div", { class: "hw-progress__line" },
      h("span", { class: "hw-progress__what" }, what),
      known ? h("span", { class: "hw-progress__count hw-tnum" }, `${done} of ${total}`) : null),
    h("div", { class: "hw-progress__track", role: "progressbar",
               "aria-valuenow": known ? String(percent) : null,
               "aria-valuemin": "0", "aria-valuemax": "100",
               "aria-valuetext": known ? `${percent}%` : "still going",
               dataset: known ? null : { unknown: "true" } },
      h("div", { class: "hw-progress__fill", style: known ? { inlineSize: `${percent}%` } : null })),
    detail ? h("p", { class: "hw-progress__detail" }, detail) : null);
}

/**
 * Run a long request with the bar above it and a plain statement underneath when it lands.
 *
 * `host` is where the bar goes, `run` is the promise, and `whileWaiting` is what to call it before
 * the backend says anything. The backend's own report, /api/jobs/current, is polled while it runs,
 * so the count is real work rather than an animation.
 */
export async function withProgress(host, run, { whileWaiting = "Working", done = "Done" } = {}) {
  let stop = false;
  fill(host, progress({ what: whileWaiting }));
  const poll = async () => {
    while (!stop) {
      try {
        const now = await api.get("/api/jobs/current");
        if (stop) return;
        if (now && now.state === "running") {
          fill(host, progress({ what: now.what || whileWaiting, detail: now.detail,
                                done: now.done, total: now.total }));
        }
      } catch {
        // The bar is a courtesy; the request underneath is the thing that matters.
      }
      await new Promise((wake) => setTimeout(wake, 600));
    }
  };
  poll();
  try {
    const answer = await run;
    stop = true;
    fill(host, h("div", { class: "hw-progress hw-progress--done", role: "status" },
      h("p", { class: "hw-confirmation", style: { margin: 0 } },
        h("span", { class: "hw-confirmation__glyph", "aria-hidden": "true" }, "\u2713"),
        typeof done === "function" ? done(answer) : done)));
    return answer;
  } catch (error) {
    stop = true;
    fill(host);
    throw error;
  }
}

/**
 * Change the reason written under a control, or take it away. A reason drawn once and never changed
 * outlives the state that wrote it: Add students sat under "Preview first, so you can see what it
 * would do" while its own button read "Add 1 student" (found driving the screen, 2026-09-22).
 */
export function setReason(control, why) {
  const button = control.matches?.("button, a") ? control : control.querySelector("button, a");
  const note = control.querySelector?.(".hw-reason");
  if (button) {
    if (why) button.title = why;
    else button.removeAttribute("title");
  }
  if (!note) return;
  note.textContent = why || "";
  note.hidden = !why;
}

/** Put a button into its saving state, and take it out again. It cannot be pressed twice. */
// A busy button refuses presses without being disabled. Disabled, it lost focus the moment it was
// pressed, so somebody on the keyboard was sent back to the top of the page by every Save, and a
// dialog it opened had nothing to give focus back to (audit, 2026-09-24).
function refuseWhileBusy(event) {
  if (!event.currentTarget.dataset.busy) return;
  event.preventDefault();
  event.stopImmediatePropagation();
}

export function setBusy(el, busy) {
  const btn = el.matches?.("button, a") ? el : el.querySelector("button, a");
  if (!btn) return;
  if (busy) {
    btn._label = btn.textContent;
    btn.dataset.busy = "true";
    if (!btn._refusesWhileBusy) {
      btn.addEventListener("click", refuseWhileBusy, true);
      btn._refusesWhileBusy = true;
    }
    btn.setAttribute("aria-disabled", "true");
    btn.setAttribute("aria-busy", "true");
    if (btn._busyLabel) btn.textContent = btn._busyLabel;
  } else {
    // `disabled` is the screen's to decide and is left as it is: this used to switch it back on,
    // so a Save that had just disabled itself ("Nothing has changed since the last save") was
    // pressable again the moment it finished.
    delete btn.dataset.busy;
    btn.removeAttribute("aria-disabled");
    btn.removeAttribute("aria-busy");
    if (btn._label) btn.textContent = btn._label;
  }
}

/** After a control that had focus disables itself, put focus on what it just said, not the page's top. */
export function keepFocusOn(note) {
  // Chrome moves focus off a disabled control at its next frame, so a control disabled a moment ago
  // can still be the active element: that counts as lost as well.
  const active = document.activeElement;
  const lost = !active || active === document.body || active.disabled;
  if (!lost || !note?.isConnected) return;
  note.tabIndex = -1;
  note.focus();
}

// -- fields ----------------------------------------------------------------------------------------

/**
 * A labelled field. `validate(value)` returns an error sentence or nothing; it runs on blur, never
 * while someone is still typing, and the error clears the moment they start fixing it
 * (flows-showing-input-error). The message says what to do, not only what is wrong.
 */
/**
 * `width` sizes the control to what goes in it: "short" for a number or a time, "medium" for a
 * code or a name, "long" for a sentence, and the default caps everything else so no field is a
 * 1,100px box waiting for two digits. A field's width is a promise about the answer, and Settings
 * was breaking it sixteen times over (measured 2026-09-22).
 *
 * `layout: "row"` puts the label and its help on the left and the control on the right, the way
 * every desktop settings screen does it. Sixteen stacked fields made Settings 3,551px tall; the
 * same fields in rows are under half that, and the shape is the one people already know.
 */
export function field({ label, name, value = "", type = "text", help = "", required = false,
                        placeholder = "", validate = null, options = null, rows = 0, ids = false,
                        autocomplete = null, inputmode = null, min = null, max = null, step = null,
                        disabled = false, readonly = false, onInput = null, onBlur = null,
                        labelAside = null, width = "", layout = "" } = {}) {
  const inputId = uid("field");
  const helpId = help ? uid("help") : null;
  const errorId = uid("error");

  let control;
  if (readonly) {
    control = h("div", { class: `hw-readonly${ids ? " hw-ids" : ""}`, id: inputId }, value);
  } else if (options) {
    control = h("select", { class: "hw-select", id: inputId, name, disabled: disabled || null });
    for (const option of options) {
      const opt = h("option", { value: option.value }, option.label);
      if (String(option.value) === String(value)) opt.selected = true;
      control.append(opt);
    }
  } else if (rows) {
    control = h("textarea", { class: "hw-textarea", id: inputId, name, rows, placeholder,
      disabled: disabled || null }, value);
  } else {
    control = h("input", { class: `hw-input${ids ? " hw-ids" : ""}`, id: inputId, name, type, value,
      placeholder, autocomplete, inputmode, min, max, step, disabled: disabled || null,
      required: required || null });
  }

  const error = h("p", { class: "hw-field__error", id: errorId, hidden: true },
    h("span", { "aria-hidden": "true", class: "hw-panel__glyph", text: "✕" }), h("span", {}));
  const labelEl = h("label", { class: "hw-field__label", for: inputId }, label);
  const wrap = h("div", { class: "hw-field", dataset: { width: width || null, layout: layout || null } },
    // A control on the label's row (Show, a unit, a link) sits beside the label rather than over the
    // input, so it never covers what is being typed and it is a real tab stop.
    labelAside ? h("div", { class: "hw-row hw-row--between" }, labelEl, labelAside) : labelEl,
    control,
    help ? h("p", { class: "hw-field__help", id: helpId }, help) : null,
    error);

  const described = [helpId].filter(Boolean);
  if (described.length) control.setAttribute("aria-describedby", described.join(" "));

  wrap.control = control;
  wrap.showError = (message) => {
    if (!message) {
      delete wrap.dataset.invalid;
      error.hidden = true;
      control.removeAttribute("aria-invalid");
      control.setAttribute("aria-describedby", described.join(" ") || "");
      if (!described.length) control.removeAttribute("aria-describedby");
      return false;
    }
    wrap.dataset.invalid = "true";
    error.hidden = false;
    error.lastElementChild.textContent = message;
    control.setAttribute("aria-invalid", "true");
    control.setAttribute("aria-describedby", [...described, errorId].join(" "));
    return true;
  };
  wrap.check = () => (validate ? wrap.showError(validate(control.value) || "") : false);
  wrap.value = () => control.value;

  // On blur, but only once someone has actually typed in it. A field that took focus because it was
  // first on the screen, and lost it again untouched, has not been got wrong yet.
  let touched = false;
  if (validate) control.addEventListener("blur", () => { if (touched) wrap.check(); });
  control.addEventListener("input", (event) => {
    touched = true;
    if (wrap.dataset.invalid) wrap.showError("");        // back to default as soon as they fix it
    onInput?.(event);
  });
  if (onBlur) control.addEventListener("blur", onBlur);
  return wrap;
}

/**
 * Check every field a form sends, show each one's error, and move focus to the first that is wrong.
 * True when any is. Without the focus, a keyboard or screen reader user pressed the button, heard
 * nothing, and stayed on it while the errors appeared somewhere above (audit, 2026-09-24): focus on
 * the field reads its label, that it is invalid, and the error it is described by.
 */
export function invalid(...fields) {
  const wrong = fields.filter((f) => f.check());
  wrong[0]?.control?.focus();
  return wrong.length > 0;
}

// -- panels, states and confirmations --------------------------------------------------------------

const PANEL_GLYPH = { failure: "✕", success: "✓", info: "i", quiet: "i", review: "?" };

export function panel({ tone = "info", title = "", body = "", children = [], role = null } = {}) {
  return h("div", { class: "hw-panel", dataset: { tone }, role },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true", text: PANEL_GLYPH[tone] || "i" }),
    h("div", {},
      title ? h("p", { class: "hw-panel__title" }, title) : null,
      body ? h("p", { class: "hw-panel__body" }, body) : null,
      ...children));
}

/** Icon, heading, description and an action. Never one sentence in a card (web-app-empty-state). */
export function emptyState({ icon = "☰", heading, body = "", action = null, tone = "" } = {}) {
  return h("div", { class: "hw-state", dataset: tone ? { tone } : null },
    h("span", { class: "hw-state__icon", "aria-hidden": "true", text: icon }),
    h("h2", { class: "hw-state__heading" }, heading),
    body ? h("p", { class: "hw-state__body" }, body) : null,
    action);
}

export function errorState({ heading = "That did not load.", body = "", onRetry = null } = {}) {
  return h("div", { class: "hw-state", dataset: { tone: "failure" }, role: "alert" },
    h("span", { class: "hw-state__icon", "aria-hidden": "true", text: "✕" }),
    h("h2", { class: "hw-state__heading" }, heading),
    h("p", { class: "hw-state__body" },
      body || "Herewise may have stopped. Check its window is still open, then try again."),
    onRetry ? button({ label: "Try again", onClick: onRetry }) : null);
}

/** Header row kept real, the rows drawn as skeletons: the shape of the answer while it loads. */
export function loadingTable(headings, rows = 6) {
  const body = h("tbody", { "aria-hidden": "true" });
  for (let r = 0; r < rows; r += 1) {
    body.append(h("tr", {}, ...headings.map((_, c) =>
      h("td", {}, h("span", { class: `hw-skeleton${c === 1 ? " hw-skeleton--wide" : ""}` })))));
  }
  return h("div", { class: "hw-table-frame", "aria-busy": "true" },
    h("table", { class: "hw-table" },
      h("thead", {}, h("tr", {}, ...headings.map((t) => h("th", { scope: "col" }, t)))),
      body));
}

export function loadingCards(count = 3) {
  return h("div", { class: "hw-grid", "aria-busy": "true" },
    ...Array.from({ length: count }, () => h("div", { class: "hw-card" },
      h("p", { class: "hw-skeleton" }), h("p", { class: "hw-skeleton hw-skeleton--wide" }))));
}

/** A save confirms itself in words, beside the control that did it. */
export function confirmation(text) {
  return h("span", { class: "hw-confirmation", role: "status" },
    h("span", { class: "hw-confirmation__glyph", "aria-hidden": "true", text: "✓" }), text);
}

// -- announcements and toasts ------------------------------------------------------------------

let live = null;
export function announce(text) {
  if (!live) {
    live = h("p", { class: "hw-visually-hidden", role: "status", "aria-live": "polite" });
    document.body.append(live);
  }
  live.textContent = "";
  // A timer, not an animation frame: frames stop in a hidden window and the sentence never arrives
  // (docs/DECISIONS-AND-LESSONS.md, 2026-09-19).
  setTimeout(() => { live.textContent = text; }, 50);
}

let toasts = null;
export function toast(text, tone = "success") {
  if (!toasts) {
    toasts = h("div", { class: "hw-toasts" });
    document.body.append(toasts);
  }
  const glyph = tone === "failure" ? "✕" : "✓";
  const node = h("div", { class: "hw-toast", dataset: { tone }, role: "status" },
    h("span", { class: "hw-toast__glyph", "aria-hidden": "true", text: glyph }), h("span", {}, text));
  toasts.append(node);
  setTimeout(() => node.remove(), 6000);
  return node;
}

// -- files the backend builds ----------------------------------------------------------------

/**
 * Save a file the backend builds, from a control that shows it is working.
 *
 * Every export goes through here so that all three things happen every time: the control says it is
 * working while a 258-student PDF is drawn, the file is saved under the name the backend chose, and
 * a refusal arrives as the backend's own sentence in a toast. Before this the window aborted slow
 * downloads and Edge said "Something went wrong" outside the app, where nothing could explain it.
 */
export async function saveFile(control, path, what) {
  setBusy(control, true);
  try {
    const name = await download(path);
    toast(`${what} is saved as ${name}.`);
    announce(`${what} is saved as ${name}.`);
    return name;
  } catch (error) {
    toast(error instanceof ApiError ? error.message : `${what} could not be saved.`, "failure");
    return null;
  } finally {
    setBusy(control, false);
  }
}

// -- dialogs ---------------------------------------------------------------------------------

/**
 * A dialog with a close button, Escape and a scrim click, because one way out is not enough
 * (docs/DESIGN-DEVIATIONS.md, screens 3 and 8). Focus returns where it came from.
 *
 * It tidies itself up on `close` and on `toggle`, and only once. Chrome 152 fires `toggle` with a
 * newState of "closed" and does not fire `close` at all for a dialog closed from script, so every
 * dialog in the app was left in the page, closed and invisible, and focus never went back to
 * whatever opened it. Found on 2026-09-21 by opening the same dialog twice.
 */
export function dialog({ title, body, actions = [], aside = null, onClose = null, labelledBy = null } = {}) {
  const opener = document.activeElement;
  const titleId = uid("dialog-title");
  const el = h("dialog", { class: "hw-dialog", "aria-labelledby": labelledBy || titleId });
  const close = () => { if (el.open) el.close(); };
  el.append(
    h("div", { class: "hw-dialog__head" },
      h("h2", { class: "hw-dialog__title", id: titleId }, title),
      h("button", { class: "hw-dialog__close", type: "button", "aria-label": "Close",
        dataset: { action: "close" }, onClick: close }, "✕")),
    h("div", { class: "hw-dialog__body" }, body),
    actions.length || aside
      ? h("div", { class: "hw-dialog__foot" }, ...actions, aside)
      : null);
  el.addEventListener("click", (event) => { if (event.target === el) close(); });
  let torn = false;
  const teardown = () => {
    if (torn || el.open) return;
    torn = true;
    onClose?.();
    el.remove();
    // What opened it may have been redrawn away by what the dialog did; then focus goes to the
    // screen rather than to the top of the document.
    if (opener?.isConnected) opener.focus();
    else document.querySelector("main[tabindex]")?.focus({ preventScroll: true });
  };
  el.addEventListener("close", teardown);
  el.addEventListener("toggle", (event) => { if (event.newState === "closed") teardown(); });
  document.body.append(el);
  el.showModal();
  return el;
}

// -- tables ----------------------------------------------------------------------------------

/**
 * A table wider than its frame becomes its own scroll region (see .hw-table-frame). Chrome makes no
 * scroll container focusable, so a keyboard-only user could not reach the columns off the right
 * edge, and nothing said they were there. This marks the frame only while it overflows: focusable,
 * named, and carrying the edge shading. A table that fits adds no tab stop and keeps the page as
 * its scroller, so its header still pins to the top of the window.
 */
function watchOverflow(frame, what) {
  const label = what ? `${what}: scrolls to show the rest` : "Table: scrolls to show the rest";
  const measure = () => {
    const on = frame.dataset.overflowing === "true";
    // Two different measurements, so the frame cannot flap between the states. While it scrolls,
    // scrollWidth is the table and clientWidth excludes the scrollbar. While it does not, the frame
    // clips, so the table's own box is what to compare. Turning the scroll off only ever gives the
    // table more room, so a frame that stops overflowing stays stopped.
    const inner = frame.firstElementChild;
    const wide = on ? frame.scrollWidth - frame.clientWidth > 1
                    : (inner ? inner.getBoundingClientRect().width : 0) - frame.clientWidth > 1;
    if (wide === on) return;
    frame.dataset.overflowing = String(wide);
    if (wide) {
      frame.tabIndex = 0;
      frame.setAttribute("role", "region");
      frame.setAttribute("aria-label", label);
    } else {
      frame.removeAttribute("tabindex");
      frame.removeAttribute("role");
      frame.removeAttribute("aria-label");
    }
  };
  if (typeof ResizeObserver === "function") {
    const watch = new ResizeObserver(measure);
    watch.observe(frame);
    // The table's own width changes when rows are filtered, not only when the window resizes.
    if (frame.firstElementChild) watch.observe(frame.firstElementChild);
  }
  return frame;
}

/**
 * A read-only table. `columns` are {key, label, align, render(row), className}. A row with `href`
 * opens on click and on Enter, and carries a real link in its first cell so the keyboard reaches it.
 */
export function table({ columns, rows, caption = "", density = "", empty = null, rowHref = null,
                        rowAttrs = null, limit = 0, what = "row", whatMany = "" } = {}) {
  if (!rows.length && empty) return empty;
  const head = h("tr", {}, ...columns.map((c) =>
    h("th", { scope: "col", dataset: c.align ? { align: c.align } : null }, c.label)));
  const body = h("tbody");

  function rowFor(row) {
    const tr = h("tr", rowAttrs ? rowAttrs(row) : null);
    const href = rowHref ? rowHref(row) : null;
    if (href) tr.dataset.href = href;
    for (const [index, column] of columns.entries()) {
      const content = column.render ? column.render(row) : row[column.key];
      const cell = h(index === 0 ? "th" : "td",
        { scope: index === 0 ? "row" : null, class: column.className || null,
          dataset: column.align ? { align: column.align } : null });
      if (index === 0 && href) cell.append(h("a", { class: "hw-link", href }, content));
      else append(cell, [content]);
      tr.append(cell);
    }
    return tr;
  }

  // A cap, not a page number. 258 students made Enrolment 15,349px of scroll, and every figure
  // worth reading was in the first screen of it (measured 2026-09-22). The rest is one press away
  // and stays on the same screen, so nothing is hidden and nothing has to be paged back to.
  const capped = limit > 0 && rows.length > limit;
  for (const row of rows.slice(0, capped ? limit : rows.length)) body.append(rowFor(row));

  if (rowHref) {
    body.addEventListener("click", (event) => {
      if (event.target.closest("a, button, input, label")) return;
      const tr = event.target.closest("tr[data-href]");
      if (tr) location.hash = tr.dataset.href;
    });
  }

  const frame = h("div", { class: "hw-table-frame" },
    h("table", { class: "hw-table", dataset: density ? { density } : null },
      caption ? h("caption", { class: "hw-visually-hidden" }, caption) : null,
      h("thead", {}, head), body));

  if (capped) {
    const all = plural(rows.length, what, whatMany || undefined);
    const more = button({ label: `Show the other ${plural(rows.length - limit, what, whatMany || undefined)}` });
    const foot = h("div", { class: "hw-table__more" },
      h("p", { class: "hw-muted", style: { margin: 0 } }, `Showing ${limit} of ${all}`),
      more);
    more.addEventListener("click", () => {
      for (const row of rows.slice(limit)) body.append(rowFor(row));
      foot.remove();
      announce(`All ${all} are showing.`);
    });
    frame.append(foot);
  }
  return watchOverflow(frame, caption);
}

// -- the diagnostic chain -------------------------------------------------------------------

/**
 * The chain from GET /api/devices/{id}/diagnose or POST /api/setup/test-device.
 * `remedySaid` is true when the panel above already carries the broken link's own sentence, so the
 * chain does not print it a second time.
 */
export function chain(checks, { remedySaid = false } = {}) {
  let firstFailure = true;
  return h("ul", { class: "hw-chain" }, ...checks.map((check) => {
    // "Not checked" is asked first: a step whose result was suppressed must never read as a pass.
    const state = check.checked === false ? "skipped" : check.ok ? "pass" : "fail";
    const glyph = { pass: "✓", fail: "✕", skipped: "○" }[state];
    const quiet = state === "fail" && remedySaid && firstFailure;
    if (state === "fail") firstFailure = false;
    return h("li", { class: "hw-chain__step", dataset: { state } },
      h("span", { class: "hw-chain__glyph", "aria-hidden": "true", text: glyph }),
      h("span", {},
        h("span", { class: "hw-chain__label" }, check.label || check.name),
        quiet ? null : h("span", { class: "hw-chain__message" }, check.message),
        h("span", { class: "hw-visually-hidden" },
          state === "pass" ? " Passed." : state === "fail" ? " Failed." : " Not checked.")));
  }));
}

/**
 * A card that is a way through to another screen: the whole card is the link, the heading is
 * underlined and carries an arrow, and an account whose role does not allow it gets the same card
 * with the backend's own refusal under it, never a card that silently does nothing.
 */
export function actionCard({ label, href, note, permission = null }) {
  const allowed = !permission || session.can(permission);
  const body = [h("p", { class: "hw-card__body" }, note)];
  if (!allowed) {
    return h("article", { class: "hw-card hw-stack hw-stack--tight" },
      h("h3", { class: "hw-card__title" }, label), ...body,
      h("p", { class: "hw-reason" }, session.denial(permission)));
  }
  return h("a", { class: "hw-card hw-card--action hw-stack hw-stack--tight", href },
    h("h3", { class: "hw-card__title" }, label), ...body);
}


// -- page furniture --------------------------------------------------------------------------

export function page({ title, subtitle = "", actions = null, children = [], wide = false,
                      crumbs = null } = {}) {
  return h("div", { class: `hw-page${wide ? " hw-page--wide" : ""}` },
    crumbs ? h("p", { class: "hw-crumbs" }, ...crumbs) : null,
    h("header", { class: "hw-page__head" },
      h("div", { class: "hw-page__titles" },
        h("h1", { class: "hw-page__title" }, title),
        subtitle ? h("p", { class: "hw-page__subtitle" }, subtitle) : null),
      actions ? h("div", { class: "hw-page__actions" }, actions) : null),
    ...children);
}

/**
 * The action bar for a form long enough that its top is off the screen by the time the last field
 * is filled in. It sticks to the bottom of the window, so Save is never something to scroll back
 * for: Settings put its Save 3,400px above the last setting it saved (measured 2026-09-22).
 */
export function stickyActions(...children) {
  return h("div", { class: "hw-sticky" },
    h("div", { class: "hw-sticky__inner" }, ...children));
}

export function section(title, ...children) {
  return h("section", { class: "hw-section" },
    title ? h("h2", { class: "hw-section__title" }, title) : null, ...children);
}
