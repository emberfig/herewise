// Screen 8: the correction drawer. Mockups: CorrectiondrawerSave.png, CorrectiondrawerRequest.png,
// CorrectiondrawerEmptynoteerror.png, CorrectiondrawerRefusedself.png.
// Spec: docs/COMPONENT-GUIDE.md, "Correction drawer". Fix list: docs/DESIGN-DEVIATIONS.md, "8".
// Contract: GET /api/sessions/{id}/students/{person_id}.
//
// Three outcomes, decided by the account's own permissions and by who the account is linked to:
//   register.correct        writes the mark, signed with the name of whoever applied it;
//   register.request only   raises a correction request for someone else to decide;
//   the student is you      refused outright and never queued, whatever the role allows, because
//                           this is not a permission: it is enforced separately in the backend.
//
// Kept from the mockup: the refusal panel sits at the top of the body, above the disabled controls,
// so the reason is read before the dead controls are reached, and its wording.
// Fixed from the mockup: the footer is pinned, so the primary action never scrolls out of reach on
// a drawer with any history; the "Send request" variant, which was never produced, is built from
// the spec; the "Currently" chip carries its glyph; the Excused description wraps; there is a close
// control in the header; the refusal panel has a warning glyph; and the scrim darkens the page
// rather than washing it grey.

import { ApiError, api } from "../app/api.js";
import { session } from "../app/session.js";
import { matricText, announce, button, clear, dateAndTime, fill, h, longDate, setBusy, uid } from "../app/ui.js";

const CSS = `
.hw-drawer {
  position: fixed; inset: 0; z-index: 50; display: flex; justify-content: flex-end;
}
/* --hw-ink at 32% over the page, so it darkens rather than greying it. */
.hw-drawer__scrim { position: absolute; inset: 0; background: rgb(34 29 23 / 0.32); }
.hw-drawer__panel {
  position: relative; display: flex; flex-direction: column;
  width: 420px; max-width: 100%; height: 100%;
  background: var(--hw-surface); color: var(--hw-ink);
  border-inline-start: var(--hw-rule-width) solid var(--hw-rule);
  box-shadow: -8px 0 24px rgb(0 0 0 / 0.12);
}
/* Below 900 px it becomes a sheet from the bottom, as the spec says. */
@media (max-width: 900px) {
  .hw-drawer { align-items: flex-end; justify-content: stretch; }
  .hw-drawer__panel { width: 100%; height: min(90vh, 720px); border-inline-start: 0;
    border-start-start-radius: var(--hw-radius-card); border-start-end-radius: var(--hw-radius-card); }
}
.hw-drawer__head {
  padding: var(--hw-space-6) var(--hw-space-6) var(--hw-space-4);
  border-block-end: var(--hw-rule-width) solid var(--hw-rule);
}
.hw-drawer__kicker {
  margin: 0 0 var(--hw-space-2); color: var(--hw-ink-muted);
  font-size: var(--hw-text-caption); font-weight: var(--hw-weight-label); letter-spacing: 0.08em;
  text-transform: uppercase;
}
.hw-drawer__name { margin: 0; font-size: var(--hw-text-section); font-weight: var(--hw-weight-emphasis); }
.hw-drawer__where { margin: var(--hw-space-1) 0 0; color: var(--hw-ink-muted); font-size: var(--hw-text-body); }
.hw-drawer__now { display: flex; align-items: center; gap: var(--hw-space-3); margin-block-start: var(--hw-space-3); }
.hw-drawer__close {
  position: absolute; inset-block-start: var(--hw-space-4); inset-inline-end: var(--hw-space-4);
  width: var(--hw-target-min); height: var(--hw-target-min);
  display: inline-flex; align-items: center; justify-content: center;
  background: none; border: var(--hw-rule-width) solid transparent; border-radius: var(--hw-radius-control);
  color: var(--hw-ink-muted); font: inherit; font-size: var(--hw-text-lead); cursor: pointer;
}
.hw-drawer__close:hover { border-color: var(--hw-rule); color: var(--hw-ink); }
.hw-drawer__body { flex: 1; overflow-y: auto; padding: var(--hw-space-6); display: grid; gap: var(--hw-space-6); align-content: start; }
/* Pinned, never scrolled out of reach. This is the single most important fix on this screen. */
.hw-drawer__foot {
  position: sticky; inset-block-end: 0;
  padding: var(--hw-space-4) var(--hw-space-6);
  background: var(--hw-surface);
  border-block-start: var(--hw-rule-width) solid var(--hw-rule);
  display: grid; gap: var(--hw-space-3);
}
.hw-drawer__heading { margin: 0 0 var(--hw-space-3); font-size: var(--hw-text-body); font-weight: var(--hw-weight-label); }
.hw-drawer__rule {
  margin: 0 0 var(--hw-space-3); padding-block-end: var(--hw-space-2);
  border-block-end: var(--hw-rule-width) solid var(--hw-rule);
  color: var(--hw-ink-muted); font-size: var(--hw-text-caption);
  font-weight: var(--hw-weight-label); letter-spacing: 0.08em; text-transform: uppercase;
}
.hw-drawer__event { margin: 0 0 var(--hw-space-3); font-size: var(--hw-text-body); }
.hw-drawer__event:last-child { margin-block-end: 0; }
.hw-drawer__event em { font-style: normal; color: var(--hw-ink-muted); }
.hw-drawer__note { display: block; margin-block-start: 2px; color: var(--hw-ink-muted); }
.hw-drawer__request {
  margin: 0; padding: var(--hw-space-3);
  background: var(--hw-accent-soft); color: var(--hw-ink);
  border-radius: var(--hw-radius-control); font-size: var(--hw-text-body);
}
`;

let styled = false;
function adoptStyles() {
  if (styled) return;
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(CSS);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  styled = true;
}

const CHOICES = [
  { value: "present", glyph: "✓", label: "Present", help: "Counts towards their attendance." },
  { value: "absent", glyph: "✕", label: "Absent", help: "Does not count." },
  { value: "excused", glyph: "E", label: "Excused",
    help: "Taken out of the total, not counted against them. Needs a reason and a category." },
];

const CATEGORIES = [
  { value: "medical", label: "Medical" },
  { value: "official", label: "Official university business" },
  { value: "bereavement", label: "Bereavement" },
  { value: "other", label: "Other" },
];

/**
 * Open the drawer over whatever is on screen. `detail` is the sheet's hw-sheet-open payload, or the
 * same shape from the class register. `onSaved(sessionId)` lets the caller refresh in place.
 */
export async function openDrawer({ person_id, session_id, courseId, onSaved = null,
                                   returnFocusTo = null } = {}) {
  adoptStyles();
  const opener = returnFocusTo || document.activeElement;
  const root = h("div", { class: "hw-drawer", role: "dialog", "aria-modal": "true" });
  const scrim = h("div", { class: "hw-drawer__scrim" });
  const panel = h("div", { class: "hw-drawer__panel" });
  root.append(scrim, panel);
  document.body.append(root);
  // The sheet behind does not scroll while the drawer is open.
  const previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";

  let dirty = false;
  const close = ({ force = false } = {}) => {
    if (dirty && !force
        && !window.confirm("Close without saving? The note you have typed will be lost.")) return;
    root.remove();
    document.body.style.overflow = previousOverflow;
    document.removeEventListener("keydown", onKey, true);
    opener?.focus?.();
  };
  const onKey = (event) => {
    if (event.key === "Escape") { event.stopPropagation(); close(); return; }
    if (event.key === "Tab") trapTab(event, panel);
  };
  document.addEventListener("keydown", onKey, true);
  scrim.addEventListener("click", () => close());

  panel.append(h("p", { class: "hw-drawer__body" }, "Loading this box."));
  let cell;
  try {
    cell = await api.get(`/api/sessions/${session_id}/students/${person_id}`);
  } catch (error) {
    fill(panel, 
      header({ name: "This box did not open", where: "", status: null, onClose: close }),
      h("div", { class: "hw-drawer__body" },
        h("div", { class: "hw-panel", dataset: { tone: "failure" }, role: "alert" },
          h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✕"),
          h("p", { class: "hw-panel__body" },
            error instanceof ApiError ? error.message : "Close the drawer and try again."))));
    return;
  }
  render(panel, cell, { close, onSaved, markDirty: () => { dirty = true; }, clean: () => { dirty = false; } });
  panel.querySelector("input, button, textarea")?.focus();
}

function trapTab(event, panel) {
  const focusable = [...panel.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])')]
    .filter((el) => el.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function header({ name, where, status, onClose }) {
  return h("div", { class: "hw-drawer__head" },
    h("p", { class: "hw-drawer__kicker" }, "Correct attendance"),
    h("h2", { class: "hw-drawer__name" }, name),
    where ? h("p", { class: "hw-drawer__where" }, where) : null,
    status,
    h("button", { class: "hw-drawer__close", type: "button", "aria-label": "Close",
      dataset: { action: "close" }, onClick: () => onClose() }, "✕"));
}

function statusPill(state, first_scan, excusal) {
  const spec = {
    present: ["✓", first_scan ? `Present, first scan ${first_scan.slice(11, 16)}` : "Present", "present"],
    marked_present: ["✓", "Present, corrected", "present"],
    absent: ["✕", "Absent", "absent"],
    marked_absent: ["✕", "Absent, corrected", "absent"],
    excused: ["E", excusal ? `Excused, ${excusal.category}` : "Excused", "excused"],
  }[state] || ["○", "Not held", "neutral"];
  return h("div", { class: "hw-drawer__now" },
    h("span", { class: "hw-muted" }, "Currently"),
    // The chip carries colour, the word and the glyph: the mockup left the glyph off.
    h("span", { class: "hw-pill", dataset: { tone: spec[2] } },
      h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, spec[0]), spec[1]));
}

function render(panel, cell, { close, onSaved, markDirty, clean }) {
  const s = cell.session;
  const self = session.isSelf(cell.student.person_id);
  const canCorrect = session.can("register.correct");
  const canRequest = session.can("register.request");
  const canExcuse = session.can("excusal.manage");
  const cancelled = Boolean(s.cancelled_at);

  // The order matters: being the student always wins, because it is not a permission.
  let refusal = null;
  if (self) {
    refusal = {
      title: "You cannot correct attendance for yourself. Ask someone else to do it.",
      body: "Nothing has been queued. This screen is only for viewing.",
    };
  } else if (cancelled) {
    refusal = {
      title: "This class was cancelled, so there is nothing to correct.",
      body: s.cancel_note ? `Cancelled: ${s.cancel_note}` : "Nothing has been queued.",
    };
  } else if (!canCorrect && !canRequest) {
    refusal = { title: session.denial("register.correct"),
      body: "Nothing has been queued. This screen is only for viewing." };
  }

  const mode = refusal ? "refused" : canCorrect ? "correct" : "request";
  const off = Boolean(refusal);

  const group = h("div", { class: "hw-fieldset", role: "radiogroup", "aria-label": "Change the mark to" });
  const name = uid("status");
  const radios = [];
  for (const choice of CHOICES) {
    const excusedOff = choice.value === "excused" && !canExcuse;
    const input = h("input", { type: "radio", name, value: choice.value,
      disabled: off || excusedOff || null });
    radios.push(input);
    const label = h("label", { class: "hw-choice" }, input,
      h("span", {},
        h("span", { class: "hw-choice__label" },
          h("span", { "aria-hidden": "true", style: { marginInlineEnd: "var(--hw-space-2)" } }, choice.glyph),
          choice.label),
        h("span", { class: "hw-choice__help" }, " ", choice.help),
        // A block, not a span: inline it ran straight on from the end of the help sentence.
        excusedOff ? h("p", { class: "hw-reason" }, session.denial("excusal.manage")) : null));
    input.addEventListener("change", () => { markDirty(); update(); });
    group.append(label);
  }

  const category = h("select", { class: "hw-select", "aria-label": "Why they are excused",
    disabled: off || null });
  for (const c of CATEGORIES) category.append(h("option", { value: c.value }, c.label));
  const categoryField = h("div", { class: "hw-field", hidden: true },
    h("label", { class: "hw-field__label" }, "Category"), category);

  const note = h("textarea", { class: "hw-textarea", rows: 4, disabled: off || null,
    placeholder: off ? "Note unavailable." : "" });
  note.addEventListener("input", () => { markDirty(); error.hidden = true; });
  const error = h("p", { class: "hw-field__error", hidden: true },
    h("span", { "aria-hidden": "true" }, "✕"), h("span", {}));
  const noteField = h("div", { class: "hw-field" },
    h("label", { class: "hw-field__label", for: note.id = uid("note") }, "Why"),
    note,
    h("p", { class: "hw-field__help" },
      "Required. This note is stored permanently and shown to anyone who asks why the mark changed."),
    error);

  const footNote = h("p", { class: "hw-reason", style: { maxWidth: "none" } });
  const save = button({ label: "Save correction", primary: true, disabled: true,
    busyLabel: "Saving", onClick: () => submit() });
  const foot = h("div", { class: "hw-drawer__foot" }, footNote, save,
    button({ label: "Cancel", onClick: () => close() }));

  function chosen() {
    return radios.find((r) => r.checked)?.value || "";
  }

  function update() {
    const value = chosen();
    categoryField.hidden = value !== "excused";
    const label = value === "excused" ? "Record excused absence"
      : mode === "request" ? "Send request" : "Save correction";
    const btn = save.matches("button") ? save : save.querySelector("button");
    btn.textContent = label;
    btn._busyLabel = value === "excused" ? "Recording" : mode === "request" ? "Sending" : "Saving";
    // Disabled until something actually changes, and it says so.
    btn.disabled = off || !value;
    btn.title = off ? refusal.title : value ? "" : "Choose what the mark should be first.";
    footNote.textContent = off ? ""
      : mode === "request"
        ? "Your role cannot apply a correction, so this goes to someone whose role allows it, "
          + "to approve or reject. Nothing on the sheet changes until they decide."
        : value === "excused"
          ? "This records an excused absence for this one class, on this course only."
          : "The correction is signed with your name and never overwrites the scan.";
    // The request variant's line sits on --hw-accent-soft, so it reads as part of the action rather
    // than as small print (docs/DESIGN-DEVIATIONS.md, screen 8).
    footNote.className = mode === "request" && !off ? "hw-drawer__request" : "hw-reason";
  }

  const where = `${matricText(cell.student.matric_no)} · ${s.course_code || "No course"}${s.course_title ? ` ${s.course_title}` : ""}`;
  const when = `${longDate(s.date)}, ${s.start_time} to ${s.end_time}`;

  fill(panel, 
    header({ name: cell.student.full_name, where: `${where}\n${when}`, onClose: close,
      status: statusPill(cell.status, cell.first_scan, cell.excusal) }),
    h("div", { class: "hw-drawer__body" },
      // The refusal sits above the dead controls, so the reason is read before they are reached.
      refusal ? h("div", { class: "hw-panel", dataset: { tone: "failure" }, role: "alert" },
        h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✕"),
        h("div", {}, h("p", { class: "hw-panel__title" }, refusal.title),
          h("p", { class: "hw-panel__body" }, refusal.body))) : null,
      h("div", {}, h("p", { class: "hw-drawer__heading" }, "Change to"), group),
      categoryField,
      noteField,
      history(cell)),
    foot);

  // Two lines in the header, because a matric number and a date do not belong on one.
  panel.querySelector(".hw-drawer__where").textContent = "";
  panel.querySelector(".hw-drawer__where").append(where, h("br"), when);
  update();

  async function submit() {
    const value = chosen();
    const text = note.value.trim();
    if (!text) {
      error.hidden = false;
      error.lastElementChild.textContent = "Type why the mark is changing. It is kept with the correction.";
      note.focus();
      return;
    }
    setBusy(save, true);
    try {
      if (value === "excused") {
        await api.post("/api/excusals", { person_id: cell.student.person_id, date_from: s.date,
          date_to: s.date, category: category.value, note: text, course_id: s.course_id });
        announce("The excused absence is recorded.");
      } else if (mode === "request") {
        await api.post(`/api/sessions/${s.id}/correction-requests`,
          { person_id: cell.student.person_id, status: value, note: text });
        announce("The request has been sent.");
      } else {
        await api.post(`/api/sessions/${s.id}/marks`,
          { person_id: cell.student.person_id, status: value, note: text });
        announce("The correction is saved.");
      }
      clean();
      close({ force: true });
      await onSaved?.(s.id);
    } catch (err) {
      setBusy(save, false);
      error.hidden = false;
      error.lastElementChild.textContent = err instanceof ApiError ? err.message : "That did not save.";
    }
  }
}

/** Everything that has happened to this box, oldest first, each line with who and when. */
function history(cell) {
  const lines = [];
  if (cell.first_scan) {
    lines.push(h("p", { class: "hw-drawer__event" },
      h("span", { "aria-hidden": "true" }, "✓ "), "Marked Present by the scan",
      h("em", {}, ` · ${dateAndTime(cell.first_scan)}`)));
  }
  if (cell.excusal) {
    lines.push(h("p", { class: "hw-drawer__event" },
      h("span", { "aria-hidden": "true" }, "E "), `Excused, ${cell.excusal.category}`,
      h("span", { class: "hw-drawer__note" }, cell.excusal.note)));
  }
  for (const mark of cell.history) {
    lines.push(h("p", { class: "hw-drawer__event" },
      h("span", { "aria-hidden": "true" }, mark.status === "present" ? "✓ " : "✕ "),
      `Marked ${mark.status === "present" ? "Present" : "Absent"} by ${mark.by}`,
      h("em", {}, ` · ${dateAndTime(mark.at)}`),
      h("span", { class: "hw-drawer__note" }, mark.note)));
  }
  for (const request of cell.pending_requests) {
    lines.push(h("p", { class: "hw-drawer__event" },
      h("span", { "aria-hidden": "true" }, "? "),
      `${request.by} asked for ${request.status}, waiting for a decision`,
      h("em", {}, ` · ${dateAndTime(request.at)}`),
      h("span", { class: "hw-drawer__note" }, request.note)));
  }
  if (!lines.length) {
    lines.push(h("p", { class: "hw-drawer__event hw-muted" },
      "Nothing has happened to this box yet. It is absent because no scan arrived."));
  }
  return h("div", {}, h("p", { class: "hw-drawer__rule" }, "Earlier corrections"), ...lines);
}
