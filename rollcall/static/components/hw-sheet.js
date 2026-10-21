// <hw-sheet>: the Living sheet. Spec: design/components/living-sheet.md.
// Renders GET /api/templates/{id}/sheet and nothing else. It never computes attendance: every state,
// count and total comes from the contract, and a correction replaces a column from the class register.

// "waiting" is a student in a class still taking attendance who has not scanned yet: blank, like an
// upcoming box, because nobody is absent until the lecturer ends the class (2026-09-22).
// "elsewhere" is a box on a group's sheet for a class the student was not in that group for: they
// moved in or out (2026-09-29). Not absent and not counted, so it is shaded like a week with no class
// and crossed by one diagonal, the mark a paper register uses for a box that does not apply. The
// diagonal is drawn, not typed, so it cannot be read as the absent cross.
const GLYPH = { present: "✓", marked_present: "✓", absent: "✕", marked_absent: "✕",
  excused: "E", not_held: "–", upcoming: "", waiting: "", elsewhere: "" };
const NOT_OPENABLE = new Set(["not_held", "upcoming", "elsewhere"]);
const FROZEN = 3;              // S/N, MATRIC NO., FULL NAME
const GROUP = 20;              // rows per content-visibility group
const FILTER_PAUSE = 120;      // ms after the last keystroke before rows are dimmed

const CSS = `
/* Redesigned 2026-09-23, after "the sheet is too compact and isn't clean and professional": matric
   numbers and long names were cut off by fixed widths, the week columns were 44px and "WK 10" touched
   "WK 11", the grid stopped two thirds of the way across a wide window, and every cell had a box drawn
   round it. Now the matric and name columns are measured from what is in them (--sheet-*-fit, set in
   render), the weeks share whatever width is left, a week header carries its start date on a second
   line, and the only lines are between rows and between weeks. */
hw-sheet {
  --sheet-sn: 52px; --sheet-matric: var(--sheet-matric-fit, 136px); --sheet-name: var(--sheet-name-fit, 320px);
  --sheet-box: 52px; --sheet-row: 44px; --sheet-head: 52px; --sheet-subhead: 30px;
  --sheet-frozen: calc(var(--sheet-sn) + var(--sheet-matric) + var(--sheet-name));
  display: block; font-size: var(--hw-text-body); color: var(--hw-ink);
}
hw-sheet[projection] { --sheet-box: 60px; --sheet-row: 52px; --sheet-name: calc(var(--sheet-name-fit, 320px) + 64px); font-size: var(--hw-text-lead); }
/* Projection (docs/DESIGN-BRIEF.md): no muted ink, and statuses as solid soft fills with bold marks.
   The tick stays unfilled so absences are still what stands out from the back of a room. */
hw-sheet[projection] :is(.sheet__head, .sheet__count, .sheet__orientation, .sheet__help, .sheet__legend, [data-notheld]) { color: var(--hw-ink); }
hw-sheet[projection] .sheet__box { font-size: var(--hw-text-section); font-weight: var(--hw-weight-emphasis); }
hw-sheet[projection] .sheet__box:is([data-state="absent"], [data-state="marked_absent"]) { background: var(--hw-absent-soft); }
hw-sheet[projection] .sheet__box[data-state="excused"] { background: var(--hw-excused-soft); font-size: var(--hw-text-lead); }
.sheet__warnings { display: grid; gap: var(--hw-space-2); margin-block-end: var(--hw-space-4); }
.sheet__warning, .sheet__notice {
  display: flex; gap: var(--hw-space-3); align-items: baseline; padding: var(--hw-space-3) var(--hw-space-4);
  border-radius: var(--hw-radius-control); font-size: var(--hw-text-body);
}
.sheet__warning { background: var(--hw-absent-soft); color: var(--hw-absent); }
.sheet__notice { background: var(--hw-sunken); color: var(--hw-ink); }
.sheet__warning a { color: inherit; font-weight: var(--hw-weight-emphasis); margin-inline-start: auto; white-space: nowrap; }
.sheet__glyph { font-weight: var(--hw-weight-emphasis); }
.sheet__toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--hw-space-3) var(--hw-space-4); margin-block-end: var(--hw-space-4); }
/* What the screen around the sheet hands it (sheet.tools): density, Sheet setup, the exports. One row
   with the search, instead of a tab row of actions and a lone "Compact rows" link on a line of its own. */
.sheet__tools { display: flex; flex-wrap: wrap; align-items: center; gap: var(--hw-space-2); margin-inline-start: auto; }
.sheet__summary { display: flex; flex-wrap: wrap; gap: var(--hw-space-1) var(--hw-space-2); align-items: baseline; }
.sheet__summary > :not([hidden]) + :not([hidden])::before { content: "·"; margin-inline-end: var(--hw-space-2); color: var(--hw-ink-muted); }
.sheet__filter {
  width: 260px; min-height: var(--hw-target-min); padding: var(--hw-space-2) var(--hw-space-3);
  font: inherit; font-size: var(--hw-text-body); color: var(--hw-ink); background: var(--hw-surface);
  border: var(--hw-rule-width) solid var(--hw-rule-strong); border-radius: var(--hw-radius-control);
}
.sheet__count, .sheet__orientation, .sheet__muted { color: var(--hw-ink-muted); font-size: var(--hw-text-body); }
.sheet__count, .sheet__orientation { white-space: nowrap; }
.sheet__filter { max-width: 100%; }
.sheet__frame {
  border: var(--hw-rule-width) solid var(--hw-rule); border-radius: var(--hw-radius-card);
  background: var(--hw-surface); overflow: hidden;
}
.sheet__scroller {
  overflow: auto; max-height: var(--sheet-max-height, 70vh); position: relative;
  scroll-padding-top: calc(var(--sheet-head) + var(--sheet-subhead) * (var(--sheet-head-rows, 2) - 1));
  scroll-padding-left: var(--sheet-frozen);
  scroll-padding-bottom: calc(var(--sheet-row) * 2);
}
/* The horizontal bar is drawn under the week columns only (.sheet__hbar), so hide this one. */
.sheet__scroller::-webkit-scrollbar { width: 12px; height: 0; }
.sheet__scroller::-webkit-scrollbar-thumb { background: var(--hw-rule-strong); border-radius: var(--hw-radius-pill); border: 3px solid var(--hw-surface); }
.sheet__scroller::-webkit-scrollbar-track { background: var(--hw-surface); }
/* At least as wide as the weeks need, and otherwise the whole frame: the weeks take up the slack. */
.sheet__grid { width: max(100%, var(--sheet-width)); outline: none; }
.sheet__row { display: grid; grid-template-columns: var(--sheet-cols); height: var(--sheet-row); }
.sheet__headrows .sheet__row:first-child { height: var(--sheet-head); }
.sheet__headrows .sheet__row + .sheet__row { height: var(--sheet-subhead); }
.sheet__group { content-visibility: auto; contain-intrinsic-block-size: auto calc(var(--sheet-row) * var(--rows)); }
/* Lines between rows, and between weeks, and nowhere else. A box round every cell made 3,000 small
   squares out of a register whose rows are what the eye follows. */
.sheet__cell, .sheet__head {
  display: flex; align-items: center; justify-content: center; min-width: 0;
  border-block-end: var(--hw-rule-width) solid var(--hw-rule);
  background: var(--hw-surface); font-variant-numeric: tabular-nums slashed-zero; white-space: nowrap;
}
[data-weekend] { border-inline-end: var(--hw-rule-width) solid var(--hw-rule); }
.sheet__head {
  font-size: var(--hw-text-caption); font-weight: var(--hw-weight-label); letter-spacing: 0.06em;
  color: var(--hw-ink-muted); background: var(--hw-sunken); overflow: hidden; text-overflow: ellipsis;
}
.sheet__week { display: grid; justify-items: center; gap: 2px; line-height: 1.2; min-width: 0; }
.sheet__week b { color: var(--hw-ink); font-weight: var(--hw-weight-emphasis); }
.sheet__week small { font-size: var(--hw-text-caption); letter-spacing: 0; font-weight: var(--hw-weight-body); }
.sheet__headrows { position: sticky; top: 0; z-index: 3; }
.sheet__headrows .sheet__row:last-child > * { border-block-end: var(--hw-rule-width-strong) solid var(--hw-rule-strong); }
/* The row under the pointer, so a long row can be followed across twelve weeks without a ruler. */
.sheet__row[data-r]:hover > .sheet__cell:not([data-current]):not([data-open]) { background: var(--hw-sunken); }
/* A class still taking attendance: its column is marked, and a box in it fills in as students scan. */
/* Its own mark, not only the tint: the current week is tinted the same, and the class taking
   attendance is usually in it. A rule down each side, in the accent, sets the one column apart. */
[data-open] { background: var(--hw-accent-soft); box-shadow: inset 2px 0 0 var(--hw-accent), inset -2px 0 0 var(--hw-accent); }
.sheet__headrows .sheet__row:first-child [data-open] { box-shadow: none; }
.sheet__head[data-open] { color: var(--hw-accent); }
.sheet__week small[data-now] { color: var(--hw-accent); font-weight: var(--hw-weight-emphasis); }
.sheet__totals { position: sticky; bottom: 0; z-index: 3; border-block-start: var(--hw-rule-width-strong) solid var(--hw-rule-strong); }
.sheet__totals .sheet__cell { background: var(--hw-sunken); font-weight: var(--hw-weight-label); }
.sheet__frozen { position: sticky; z-index: 2; justify-content: flex-start; padding-inline: var(--hw-space-4); }
.sheet__totals .sheet__frozen[data-col="2"] { letter-spacing: 0.06em; font-size: var(--hw-text-caption); color: var(--hw-ink-muted); }
/* A student's matric number and name open their details, so they look like something to press. */
.sheet__row[data-r] > .sheet__frozen:is([data-col="1"], [data-col="2"]) { cursor: pointer; }
.sheet__row[data-r] > .sheet__frozen:is([data-col="1"], [data-col="2"]):hover { text-decoration: underline; text-underline-offset: 3px; }
/* A direct-entry student with no matric number yet reads DE, the lecturer's own mark (2026-09-23): muted,
   so it still reads as a number to fill in rather than as one. */
.sheet__nomatric { color: var(--hw-ink-muted); font-variant-numeric: normal; }
.sheet__headrows .sheet__frozen, .sheet__totals .sheet__frozen { z-index: 4; }
.sheet__frozen[data-col="0"] { left: 0; justify-content: flex-end; }
.sheet__frozen[data-col="1"] { left: var(--sheet-sn); }
.sheet__frozen[data-col="2"] {
  left: calc(var(--sheet-sn) + var(--sheet-matric));
  border-inline-end: var(--hw-rule-width-strong) solid var(--hw-rule-strong);
  overflow: hidden; text-overflow: ellipsis;
}
.sheet__section .sheet__frozen[data-col="0"] {
  justify-content: flex-start; grid-column: 1 / 4; font-weight: var(--hw-weight-emphasis);
  letter-spacing: 0.12em; background: var(--hw-sunken);
  border-inline-end: var(--hw-rule-width-strong) solid var(--hw-rule-strong);
}
.sheet__section .sheet__fill { grid-column: 4 / -1; background: var(--hw-sunken); border-block-end: var(--hw-rule-width) solid var(--hw-rule); }
.sheet__box { font-size: var(--hw-text-lead); cursor: pointer; position: relative; }
.sheet__box:hover { outline: var(--hw-rule-width) solid var(--hw-rule-strong); outline-offset: -3px; }
.sheet__box:focus-visible, .sheet__box:focus { outline: var(--hw-focus-width) solid var(--hw-focus); outline-offset: -3px; z-index: 1; }
.sheet__box[data-state="absent"], .sheet__box[data-state="marked_absent"] { color: var(--hw-absent); }
.sheet__box[data-state="excused"] { color: var(--hw-excused); font-size: var(--hw-text-table); font-weight: var(--hw-weight-emphasis); }
.sheet__box[aria-readonly="true"] { cursor: default; }
.sheet__row > [tabindex]:focus { outline: var(--hw-focus-width) solid var(--hw-focus); outline-offset: -3px; z-index: 5; }
hw-sheet[density="compact"] { --sheet-row: var(--hw-row-compact); }
/* Narrow windows, including 200% zoom on a 1366 laptop: only the name stays frozen, and the native
   horizontal scrollbar returns because the frozen edge is no longer fixed (WCAG 1.4.10 exempts the grid
   itself, not the sticky parts around it). */
@media (max-width: 900px) {
  hw-sheet { --sheet-name: 200px; --sheet-frozen: var(--sheet-name); }
  .sheet__frozen[data-col="0"], .sheet__frozen[data-col="1"] { position: static; }
  .sheet__frozen[data-col="2"] { left: 0; }
  .sheet__scroller::-webkit-scrollbar { height: 12px; }
  .sheet__hbar { display: none; }
}
/* 400% zoom leaves about 320 px: a 200 px name would cover the box that has focus (WCAG 2.4.11). */
@media (max-width: 600px) {
  hw-sheet { --sheet-name: 128px; }
}
/* Short windows, including 400% zoom: sticky totals would leave no room for rows, so they scroll with
   the sheet, and the sheet may use the whole window height. */
@media (max-height: 560px) {
  .sheet__totals { position: static; }
  .sheet__scroller { max-height: calc(100vh - var(--hw-space-4)); scroll-padding-bottom: 0; }
}
/* A corrected mark carries a note marker in the corner, so correction is never colour alone. */
.sheet__box[data-state^="marked_"]::after {
  content: ""; position: absolute; top: 4px; right: 4px; border: 4px solid transparent;
  border-top-color: currentColor; border-right-color: currentColor;
}
[data-current] { background: var(--hw-accent-soft); }
.sheet__head[data-current] { color: var(--hw-ink); }
[data-notheld] { background: var(--hw-sunken); color: var(--hw-ink-muted); }
/* Not theirs: in another group that day. Shaded, and one diagonal drawn on a layer of its own so the
   row's hover colour cannot take it away. */
.sheet__box[data-state="elsewhere"] { background: var(--hw-sunken); cursor: default; }
.sheet__box[data-state="elsewhere"]::before, .sheet__swatch::before {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(to top right, transparent calc(50% - 0.75px), var(--hw-rule-strong) calc(50% - 0.75px),
    var(--hw-rule-strong) calc(50% + 0.75px), transparent calc(50% + 0.75px));
}
.sheet__swatch {
  position: relative; display: inline-block; inline-size: 1.1em; block-size: 1.1em; vertical-align: -0.2em;
  background: var(--hw-sunken); border: var(--hw-rule-width) solid var(--hw-rule-strong);
}
/* Dimmed by colour, not opacity: 262 rows with their own opacity made the first filter keystrokes take
   520 to 784 ms to paint, colour 112 to 152 ms (scripts/measure_sheet.mjs, 2026-09-19). Muted ink keeps
   4.5:1, because a dimmed row is still content someone can focus and read. */
.sheet__row[data-dimmed] { color: var(--hw-ink-muted); }
.sheet__row[data-dimmed] > .sheet__box { color: inherit; }
/* Muted ink alone is a quiet difference, so matches are also marked: few rows, so few style changes. */
.sheet__row[data-match] > .sheet__frozen { background: var(--hw-accent-soft); }
.sheet__row[data-match] > .sheet__frozen[data-col="2"] { font-weight: var(--hw-weight-emphasis); }
.sheet__hbar {
  overflow-x: auto; overflow-y: hidden; margin-inline-start: var(--sheet-frozen);
  border-block-start: var(--hw-rule-width) solid var(--hw-rule);
}
.sheet__hbar > div { height: 1px; }
.sheet__help { margin-block: var(--hw-space-3) var(--hw-space-2); color: var(--hw-ink-muted); font-size: var(--hw-text-body); }
.sheet__legend { display: flex; flex-wrap: wrap; gap: var(--hw-space-6); color: var(--hw-ink-muted); font-size: var(--hw-text-body); margin: 0; padding: 0; list-style: none; }
.sheet__legend b { color: var(--hw-ink); margin-inline-end: var(--hw-space-2); font-weight: var(--hw-weight-emphasis); }
.sheet__legend li:nth-child(2) b { color: var(--hw-absent); }
.sheet__legend li:nth-child(3) b { color: var(--hw-excused); }
.sheet__skeleton { height: 12px; width: 60%; border-radius: var(--hw-radius-control); background: var(--hw-sunken); }
.sheet__empty { display: grid; justify-items: start; gap: var(--hw-space-3); padding: var(--hw-space-12) var(--hw-space-8); }
.sheet__empty h2 { margin: 0; font-size: var(--hw-text-section); font-weight: var(--hw-weight-emphasis); }
.sheet__empty p { margin: 0; max-width: 60ch; color: var(--hw-ink-muted); }
.sheet__icon { font-size: var(--hw-text-title); color: var(--hw-ink-muted); line-height: 1; }
.sheet__button {
  display: inline-flex; align-items: center; min-height: var(--hw-target-min); padding: var(--hw-space-2) var(--hw-space-4);
  border-radius: var(--hw-radius-control); border: var(--hw-rule-width) solid var(--hw-rule-strong);
  background: var(--hw-surface); color: var(--hw-ink); font: inherit; font-weight: var(--hw-weight-label);
  text-decoration: none; cursor: pointer;
}
.sheet__button--primary { background: var(--hw-accent); color: var(--hw-on-accent); border-color: var(--hw-accent); }
.sheet__button--primary:hover { background: var(--hw-accent-hover); }
`;

let styled = false;
function adoptStyles() {
  if (styled) return;
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(CSS);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  styled = true;
}

// Accents dropped and case folded, as rollcall/names.py fold() does: "olabisi" finds "Ọlábísí".
function fold(text) {
  return String(text ?? "").normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
}

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function time(iso) {
  return iso ? iso.slice(11, 16) : "";
}

function longDate(iso) {
  if (!iso) return "";
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}

function shortDay(iso) {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function weekName(week) {
  return week.label === `WK ${week.week_number}` ? `week ${week.week_number}` : week.label;
}

function stateWords(cell) {
  switch (cell.state) {
    case "present": return cell.first_scan ? `present, first scan ${time(cell.first_scan)}` : "present";
    case "marked_present": return "present, corrected";
    case "absent": return "absent";
    case "marked_absent": return "absent, corrected";
    case "excused": return cell.excusal_category ? `excused, ${cell.excusal_category}` : "excused";
    case "not_held": return "class not held";
    case "waiting": return "not scanned yet, the class is still taking attendance";
    case "elsewhere": return "not theirs, in another group that day";
    default: return "not yet held";
  }
}

export class HwSheet extends HTMLElement {
  constructor() {
    super();
    this._data = null;
    this._columns = [];        // one per box: {week, slot}
    this._rows = [];           // student row elements, in contract order
    this._focus = { r: 0, c: FROZEN };  // c is the cell's index in its row, frozen cells included
    this._filter = "";
    this._onKey = this.handleKeydown.bind(this);
    this._onClick = this.handleClick.bind(this);
    this._onFilter = this.handleFilterInput.bind(this);
    this._onFilterKey = this.handleFilterKeydown.bind(this);
    this._onRetry = this.handleRetry.bind(this);
  }

  connectedCallback() {
    adoptStyles();
    if (!this._data && !this.hasChildNodes()) this.showLoading();
  }

  disconnectedCallback() {
    this._resize?.disconnect();
    clearTimeout(this._filterTimer);
  }

  get data() { return this._data; }

  /** Controls the screen around the sheet puts at the end of its toolbar: density, setup, exports. */
  set tools(nodes) {
    this._tools = nodes;
    this.querySelector(".sheet__tools")?.append(...nodes);
  }

  /**
   * Size the matric and name columns to what is in them, measured in the font they are drawn in.
   * Fixed at 128px and 332px they cut "25/DUMMY01/001" to "25/DUMMY01/00" and a 51-letter name in
   * half (reported 2026-09-23). The name is capped, so one long name cannot push the weeks off the
   * screen; the whole name is in its tooltip and in the row header a screen reader announces.
   * Measured with a canvas, not the DOM, so it costs no layout: 2.5 ms for 259 students on this
   * machine (2026-09-23), against 24 to 37 ms for the whole render.
   */
  fitColumns(students) {
    const probe = document.createElement("canvas").getContext("2d");
    const style = getComputedStyle(this);
    probe.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    const widest = (texts) => texts.reduce((w, t) => Math.max(w, probe.measureText(String(t ?? "")).width), 0);
    const pad = 2 * 16 + 4;   // the cells' padding either side, and a little air
    const matric = Math.ceil(widest(students.map((s) => s.matric_no || "DE")) * 1.04 + pad);
    const name = Math.ceil(widest(students.map((s) => s.full_name)) + pad);
    this.style.setProperty("--sheet-matric-fit", `${Math.min(Math.max(matric, 104), 220)}px`);
    this.style.setProperty("--sheet-name-fit", `${Math.min(Math.max(name, 220), 420)}px`);
  }

  set data(sheet) {
    this._data = sheet;
    this.render();
  }

  // Fetch the contract and render it, with the loading and error states in between.
  async load(url) {
    this._url = url;
    this.showLoading();
    try {
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) throw new Error(String(response.status));
      this.data = await response.json();
    } catch {
      this.showError();
    }
  }

  showLoading() {
    adoptStyles();
    this.setAttribute("aria-busy", "true");
    const rows = Array.from({ length: 10 }, () =>
      `<div class="sheet__row" style="--sheet-cols: var(--sheet-sn) var(--sheet-matric) var(--sheet-name) 1fr">
        <div class="sheet__cell"></div><div class="sheet__cell"><span class="sheet__skeleton"></span></div>
        <div class="sheet__cell"><span class="sheet__skeleton"></span></div><div class="sheet__cell"></div></div>`).join("");
    this.innerHTML = `<p class="hw-visually-hidden" role="status">Loading the sheet</p>
      <div class="sheet__frame"><div class="sheet__row" style="--sheet-cols: var(--sheet-sn) var(--sheet-matric) var(--sheet-name) 1fr">
        <div class="sheet__head">S/N</div><div class="sheet__head">MATRIC NO.</div><div class="sheet__head">FULL NAME</div><div class="sheet__head"></div>
      </div>${rows}</div>`;
  }

  showError() {
    adoptStyles();
    this.removeAttribute("aria-busy");
    this.innerHTML = `<div class="sheet__frame"><div class="sheet__empty" role="alert">
        <span class="sheet__icon" aria-hidden="true">⚠</span>
        <h2>The sheet did not load.</h2>
        <p>Herewise may have stopped. Check its window is still open, then try again.</p>
        <button type="button" class="sheet__button" data-action="retry">Try again</button>
      </div></div>`;
    this.querySelector("[data-action=retry]").addEventListener("click", this._onRetry);
  }

  handleRetry() {
    if (this._url) this.load(this._url);
    else this.dispatchEvent(new CustomEvent("hw-sheet-retry", { bubbles: true }));
  }

  render() {
    const d = this._data;
    this.removeAttribute("aria-busy");
    this._resize?.disconnect();
    if (!d) return this.showLoading();

    const warnings = this.renderWarnings(d);
    if (!d.students.length && d.groups) {
      // One group's sheet with nobody on it: the course has students, this group has none yet.
      const href = this.getAttribute("groups-href");
      this.innerHTML = `${warnings}<div class="sheet__frame"><div class="sheet__empty">
          <span class="sheet__icon" aria-hidden="true">☰</span>
          <h2>Nobody in ${esc(d.group ? d.group.name : "this sheet")} yet</h2>
          <p>Put students in the group from the Groups tab. Its sheet lists everybody who has been in it.</p>
          ${href ? `<a class="sheet__button sheet__button--primary" href="${esc(href)}">Open Groups</a>` : ""}
        </div></div>`;
      return;
    }
    if (!d.students.length) {
      const href = this.getAttribute("add-students-href");
      this.innerHTML = `${warnings}<div class="sheet__frame"><div class="sheet__empty">
          <span class="sheet__icon" aria-hidden="true">☰</span>
          <h2>No students on this course yet</h2>
          <p>Import the level's roster or add carry-over students. They appear here in the order of the paper sheet.</p>
          ${href ? `<a class="sheet__button sheet__button--primary" href="${esc(href)}">Add students</a>` : ""}
        </div></div>`;
      return;
    }

    this._columns = [];
    for (const w of d.weeks) for (const s of w.slots) this._columns.push({ week: w, slot: s });
    const multi = d.weeks.some((w) => w.slots.length > 1);
    const headRows = multi ? 2 : 1;
    const boxes = this._columns.length;
    // The course's plan when it has one, the figure the header above quotes; its boxes otherwise.
    const planned = d.planned_classes ?? d.weeks.reduce((n, w) => n + w.classes, 0);
    this.style.setProperty("--sheet-cols", `var(--sheet-sn) var(--sheet-matric) var(--sheet-name) repeat(${boxes}, minmax(var(--sheet-box), 1fr))`);
    this.fitColumns(d.students);
    this.style.setProperty("--sheet-width", `calc(var(--sheet-frozen) + ${boxes} * var(--sheet-box))`);
    this.style.setProperty("--sheet-head-rows", String(headRows));

    // Rows keep their index in the contract, so a box is always students[r].cells[c].
    const indexed = d.students.map((s, r) => [s, r]);
    const home = indexed.filter(([s]) => s.kind !== "carry_over");
    const carry = indexed.filter(([s]) => s.kind === "carry_over");
    const colCount = FROZEN + boxes;
    const groups = [];
    const addGroups = (students) => {
      for (let i = 0; i < students.length; i += GROUP) {
        const chunk = students.slice(i, i + GROUP);
        groups.push(`<div class="sheet__group" role="rowgroup" style="--rows: ${chunk.length}">${
          chunk.map(([s, r]) => this.renderRow(s, r)).join("")}</div>`);
      }
    };
    addGroups(home);
    if (carry.length) {
      groups.push(`<div role="rowgroup"><div class="sheet__row sheet__section" role="row">
        <div class="sheet__cell sheet__frozen" data-col="0" role="rowheader" aria-colspan="${colCount}">CARRY-OVER STUDENTS</div>
        <div class="sheet__fill" aria-hidden="true"></div></div></div>`);
      addGroups(carry);
    }

    // A course with groups has a sheet per group, and the grid says whose it is.
    const whose = d.groups ? (d.group ? `, ${d.group.name}` : ", students in no group") : "";
    const title = `${d.template.course_code} ${d.template.course_title}`.trim() + whose;
    const noClasses = d.classes_held === 0 && !d.warnings.length
      ? `<p class="sheet__notice"><span class="sheet__glyph" aria-hidden="true">ℹ</span>No classes held yet. They appear here after you get attendance from the device.</p>` : "";
    this.innerHTML = `${warnings}${noClasses}
      <div class="sheet__toolbar">
        <label class="hw-visually-hidden" for="sheet-filter-${this.uid()}">Find a student in this sheet</label>
        <input class="sheet__filter" id="sheet-filter-${this.uid()}" type="search" autocomplete="off"
          placeholder="Find a student in this sheet" value="${esc(this._filter)}">
        <p class="sheet__summary" style="margin: 0">
          <span class="sheet__count" role="status"></span>
          <span class="sheet__orientation hw-num">${d.classes_held} of ${planned} classes held</span>
        </p>
        <div class="sheet__tools"></div>
      </div>
      <div class="sheet__frame">
        <div class="sheet__scroller">
          <div class="sheet__grid" role="grid" aria-label="Attendance sheet, ${esc(title)}">
            <div class="sheet__headrows" role="rowgroup">${this.renderHeaders(d, multi)}</div>
            ${groups.join("")}
            <div class="sheet__totals" role="rowgroup">${this.renderTotals()}</div>
          </div>
        </div>
        <div class="sheet__hbar" aria-hidden="true"><div></div></div>
      </div>
      <p class="sheet__help">Select any box to correct it, or move between boxes with the arrow keys. Corrections are recorded with a note and never overwrite a scan. Select a student's name or matric number to correct it, or to add a matric number a direct-entry student has been given.</p>
      <ul class="sheet__legend" aria-label="Key">
        <li><b aria-hidden="true">✓</b>Present</li><li><b aria-hidden="true">✕</b>Absent</li>
        <li><b aria-hidden="true">E</b>Excused</li><li><b aria-hidden="true">–</b>Class not held</li>
        <li><b aria-hidden="true">◥</b>Corrected</li>${d.groups ? `
        <li><b aria-hidden="true" class="sheet__swatch"></b>Not theirs: in another group that day</li>` : ""}
      </ul>
      <p class="hw-visually-hidden" role="status" data-live></p>`;

    // The same nodes each time, moved rather than rebuilt, so a button keeps its state and listeners.
    this.querySelector(".sheet__tools").append(...(this._tools || []));
    this._grid = this.querySelector(".sheet__grid");
    this._scroller = this.querySelector(".sheet__scroller");
    this._hbar = this.querySelector(".sheet__hbar");
    this._live = this.querySelector("[data-live]");
    this._rows = [];
    for (const row of this.querySelectorAll(".sheet__row[data-r]")) this._rows[Number(row.dataset.r)] = row;
    // The totals rows follow the students: every data cell is reachable, as the APG data grid requires.
    this._rows.push(...this.querySelectorAll(".sheet__totals .sheet__row"));
    this._grid.addEventListener("keydown", this._onKey);
    this._grid.addEventListener("click", this._onClick);
    const filter = this.querySelector(".sheet__filter");
    filter.addEventListener("input", this._onFilter);
    filter.addEventListener("keydown", this._onFilterKey);
    this.wireScrollbar();
    this._focus = { r: Math.min(this._focus.r, this._rows.length - 1), c: Math.min(this._focus.c, colCount - 1) };
    this.box(this._focus.r, this._focus.c)?.setAttribute("tabindex", "0");
    this.applyFilter();
  }

  uid() {
    if (!this._uid) this._uid = Math.random().toString(36).slice(2, 8);
    return this._uid;
  }

  renderWarnings(d) {
    const href = this.getAttribute("setup-href");
    return d.warnings.length ? `<div class="sheet__warnings">${d.warnings.map((w) =>
      `<p class="sheet__warning" role="alert"><span class="sheet__glyph" aria-hidden="true">⚠</span><span>${esc(w)}</span>${
        href ? `<a href="${esc(href)}">Change the weeks</a>` : ""}</p>`).join("")}</div>` : "";
  }

  renderHeaders(d, multi) {
    let col = FROZEN;
    const top = d.weeks.filter((w) => w.slots.length).map((w) => {
      const span = w.slots.length;
      const open = w.slots.some((s) => s.state === "open");
      // The week's first day under its label, so a lecturer finds "the week of the 6th" without
      // counting columns. For a week holding a class that is taking attendance, "now" instead.
      const second = open ? `<small data-now>now</small>`
        : w.starts_on ? `<small>${esc(shortDay(w.starts_on))}</small>` : "";
      // A week of one box has no second header row, so on a group's sheet its header names whose
      // class it was; with two or more boxes, each box's own header does.
      const named = d.groups && span === 1 && w.slots[0].session_id
        ? ` aria-label="${esc(this.columnName({ week: w, slot: w.slots[0] }))}"` : "";
      const cells = `<div class="sheet__head" role="columnheader" aria-colspan="${span}"${named} data-weekend
        style="grid-column: span ${span}" ${w.current ? "data-current" : ""} ${open ? "data-open" : ""}
        title="${esc(w.label)}${w.starts_on ? `, from ${esc(longDate(w.starts_on))}` : ""}"><span class="sheet__week"><b>${esc(w.label)}</b>${second}</span></div>`;
      col += span;
      return cells;
    }).join("");
    const frozen = (row) => ["S/N", "MATRIC NO.", "FULL NAME"].map((t, i) =>
      `<div class="sheet__head sheet__frozen" data-col="${i}" role="columnheader">${row === 1 ? t : ""}</div>`).join("");
    let html = `<div class="sheet__row" role="row">${frozen(1)}${top}</div>`;
    if (multi) {
      const second = this._columns.map((c, i) => {
        const label = c.week.slots.length > 1 ? String(c.slot.slot) : "";
        return `<div class="sheet__head" role="columnheader" data-c="${i}"
          aria-label="${esc(this.columnName(c))}" ${this.columnAttrs(c)}>${label}</div>`;
      }).join("");
      html += `<div class="sheet__row" role="row">${frozen(2)}${second}</div>`;
    }
    return html;
  }

  // The column's name, announced by screen readers as focus changes column. Counts live in the totals.
  columnName(c) {
    const where = c.week.slots.length > 1 ? `${weekName(c.week)}, class ${c.slot.slot}` : weekName(c.week);
    if (c.slot.state === "not_held") return `${where}, class not held`;
    if (c.slot.state === "upcoming") return `${where}, not yet held`;
    // On a group's sheet a class is either the group's own or one for everybody on the course.
    const whose = this._data?.groups ? (c.slot.group ? `, ${c.slot.group}'s class` : ", a class for everybody") : "";
    if (c.slot.state === "open") return `${where}${whose}, taking attendance now, since ${c.slot.start_time}`;
    return `${where}${whose}, ${longDate(c.slot.date)} ${c.slot.start_time}`;
  }

  columnAttrs(c) {
    // The last class of a week carries the rule that separates it from the next week.
    const weekend = c.slot.slot === c.week.slots.length;
    return `${c.week.current ? "data-current" : ""} ${c.slot.state === "not_held" ? "data-notheld" : ""}`
      + `${c.slot.state === "open" ? " data-open" : ""}${weekend ? " data-weekend" : ""}`;
  }

  renderRow(s, r) {
    const cells = s.cells.map((cell, c) => this.renderBox(s, cell, c)).join("");
    return `<div class="sheet__row" role="row" data-r="${r}" data-person="${s.person_id}">
      <div class="sheet__cell sheet__frozen hw-num" data-col="0" role="gridcell" tabindex="-1">${s.sn}</div>
      <div class="sheet__cell sheet__frozen hw-num" data-col="1" role="gridcell" tabindex="-1"
        title="${s.matric_no ? "Select to edit" : "Direct entry, no matric number yet. Select to add it"}">${s.matric_no
          ? esc(s.matric_no) : `<span class="sheet__nomatric">DE</span>`}</div>
      <div class="sheet__cell sheet__frozen" data-col="2" role="rowheader" tabindex="-1" title="${esc(s.full_name)}. Select to edit">${esc(s.full_name)}</div>
      ${cells}</div>`;
  }

  renderBox(s, cell, c) {
    const col = this._columns[c];
    // Status words only: screen readers announce the row header (the student) and the column header
    // (week and class) as focus changes row or column, so repeating them here would be heard twice.
    const readonly = NOT_OPENABLE.has(cell.state) ? ` aria-readonly="true"` : "";
    return `<div class="sheet__cell sheet__box" role="gridcell" tabindex="-1" data-c="${c}"
      data-state="${cell.state}" aria-label="${esc(stateWords(cell))}"${readonly} ${this.columnAttrs(col)}>${GLYPH[cell.state] ?? ""}</div>`;
  }

  renderTotals() {
    // An open class has a present count that grows, and no absent count until it is ended.
    const figure = (c, key) => c.slot.state === "held" ? String(c.slot[key])
      : c.slot.state === "open" ? (key === "present" ? String(c.slot.present) : "")
        : c.slot.state === "not_held" ? "\u2013" : "";
    const name = (c, key) => c.slot.state === "not_held" ? ` aria-label="class not held"`
      : c.slot.state === "upcoming" ? ` aria-label="not yet held"`
        : c.slot.state === "open" && key === "absent" ? ` aria-label="still taking attendance"` : "";
    const row = (label, key) => `<div class="sheet__row" role="row">
      <div class="sheet__cell sheet__frozen" data-col="0" role="gridcell" tabindex="-1"></div>
      <div class="sheet__cell sheet__frozen" data-col="1" role="gridcell" tabindex="-1"></div>
      <div class="sheet__cell sheet__frozen" data-col="2" role="rowheader" tabindex="-1">${label}</div>
      ${this._columns.map((c, i) => `<div class="sheet__cell hw-num" role="gridcell" tabindex="-1"
        data-total="${key}" data-c="${i}"${name(c, key)} ${this.columnAttrs(c)}>${figure(c, key)}</div>`).join("")}</div>`;
    return row("PRESENT", "present") + row("ABSENT", "absent");
  }

  // The native horizontal bar is hidden; this one sits under the week columns only and mirrors it.
  wireScrollbar() {
    const spacer = this._hbar.firstElementChild;
    const size = () => {
      const frozen = this._grid.querySelector(".sheet__frozen[data-col='2']");
      const frozenEdge = frozen ? frozen.offsetLeft + frozen.offsetWidth : 0;
      spacer.style.width = `${this._scroller.scrollWidth - frozenEdge}px`;
      this._hbar.style.width = `${this._scroller.clientWidth - frozenEdge}px`;
      this._hbar.hidden = this._scroller.scrollWidth <= this._scroller.clientWidth;
    };
    // Compare, rather than flag the echo: when the other side is already in place no echo event
    // comes, and a flag left set would swallow the next real scroll.
    const mirror = (from, to) => () => {
      if (to.scrollLeft !== from.scrollLeft) to.scrollLeft = from.scrollLeft;
    };
    this._scroller.addEventListener("scroll", mirror(this._scroller, this._hbar), { passive: true });
    this._hbar.addEventListener("scroll", mirror(this._hbar, this._scroller), { passive: true });
    this._resize = new ResizeObserver(size);
    this._resize.observe(this._scroller);
    size();
  }

  box(r, c) {
    return this._rows[r]?.children[c] ?? null;
  }

  moveTo(r, c) {
    const old = this.box(this._focus.r, this._focus.c);
    const next = this.box(r, c);
    if (!next) return;
    old?.setAttribute("tabindex", "-1");
    next.setAttribute("tabindex", "0");
    this._focus = { r, c };
    next.focus();
  }

  // Rows the arrow keys stop on: every row, or only matching rows while a filter is set.
  navigable(r) {
    return !this._rows[r].hasAttribute("data-dimmed");
  }

  step(from, delta) {
    let r = from;
    for (let moved = 0; moved < Math.abs(delta);) {
      const next = r + Math.sign(delta);
      if (next < 0 || next >= this._rows.length) break;
      r = next;
      if (this.navigable(r)) moved += 1;
    }
    return this.navigable(r) ? r : from;
  }

  edgeRow(first) {
    const order = first ? this._rows.keys() : [...this._rows.keys()].reverse();
    for (const r of order) if (this.navigable(r)) return r;
    return this._focus.r;
  }

  handleKeydown(event) {
    if (!event.target.closest(".sheet__row > [tabindex]")) return;
    const { r, c } = this._focus;
    const last = FROZEN + this._columns.length - 1;
    const page = Math.max(1, Math.floor(this._scroller.clientHeight / this._rows[0].offsetHeight) - 3);
    const ctrl = event.ctrlKey || event.metaKey;
    const moves = {
      ArrowRight: () => [r, Math.min(c + 1, last)],
      ArrowLeft: () => [r, Math.max(c - 1, 0)],
      ArrowDown: () => [this.step(r, 1), c],
      ArrowUp: () => [this.step(r, -1), c],
      PageDown: () => [this.step(r, page), c],
      PageUp: () => [this.step(r, -page), c],
      Home: () => (ctrl ? [this.edgeRow(true), 0] : [r, 0]),
      End: () => (ctrl ? [this.edgeRow(false), last] : [r, last]),
    };
    if (moves[event.key]) {
      event.preventDefault();
      this.moveTo(...moves[event.key]());
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      this.open(r, c);
    }
  }

  handleClick(event) {
    const target = event.target.closest(".sheet__row > [tabindex]");
    if (!target) return;
    const r = this._rows.indexOf(target.parentElement);
    const c = [...target.parentElement.children].indexOf(target);
    this.moveTo(r, c);
    this.open(r, c);
  }

  // A box opens its correction; a student's name or matric number opens their details, so a name
  // can be corrected and a direct-entry student given the matric number they did not have
  // (asked for on 2026-09-23). The serial number and the totals are there to be read.
  open(r, cellIndex) {
    if (r >= this._data.students.length) return;
    if (cellIndex === 1 || cellIndex === 2) {
      const student = this._data.students[r];
      this.dispatchEvent(new CustomEvent("hw-sheet-edit-student", { bubbles: true, detail: {
        person_id: student.person_id, surname: student.surname, other_names: student.other_names,
        full_name: student.full_name, matric_no: student.matric_no, level: student.level } }));
      return;
    }
    if (cellIndex < FROZEN) return;
    const c = cellIndex - FROZEN;
    const student = this._data.students[r];
    const cell = student.cells[c];
    const col = this._columns[c];
    if (cell.state === "not_held") return this.say(`No class was held in ${weekName(col.week)}${col.week.slots.length > 1 ? `, class ${col.slot.slot}` : ""}.`);
    // A correction there would be refused: the class was another group's for this student that day.
    if (cell.state === "elsewhere") return this.say(`${student.full_name} was not in ${this._data.group?.name || "this group"} on ${longDate(col.slot.date)}, so that class was not theirs and counts neither way.`);
    if (cell.state === "upcoming") return this.say(`${weekName(col.week)[0].toUpperCase()}${weekName(col.week).slice(1)}${col.week.slots.length > 1 ? `, class ${col.slot.slot}` : ""} has not happened yet.`);
    this.dispatchEvent(new CustomEvent("hw-sheet-open", {
      bubbles: true,
      detail: { person_id: student.person_id, session_id: col.slot.session_id, week: cell.week, slot: cell.slot,
        state: cell.state, full_name: student.full_name, matric_no: student.matric_no },
    }));
  }

  // Focus goes back to the box the drawer was opened from, never to the top of the sheet.
  restoreFocus() {
    this.box(this._focus.r, this._focus.c)?.focus();
  }

  say(text) {
    // Cleared first so the same sentence twice is announced twice. A timer, not an animation frame,
    // because frames stop in a hidden window and the sentence would never arrive.
    this._live.textContent = "";
    setTimeout(() => { this._live.textContent = text; }, 50);
  }

  // The typed letter paints first; the rows are dimmed in a later task once typing pauses, so a
  // keystroke never waits for 270 rows to repaint (web.dev, "Optimize Interaction to Next Paint").
  handleFilterInput(event) {
    this._filter = event.target.value;
    clearTimeout(this._filterTimer);
    this._filterTimer = setTimeout(() => this.applyFilter(), FILTER_PAUSE);
  }

  handleFilterKeydown(event) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    clearTimeout(this._filterTimer);
    this.applyFilter();
    const r = this._rows.findIndex((row, i) => this.navigable(i));
    if (r >= 0) this.moveTo(r, this._focus.c);
  }

  applyFilter() {
    const q = fold(this._filter.trim());
    const total = this._data.students.length;
    let shown = 0;
    this._data.students.forEach((s, r) => {
      const match = !q || fold(s.full_name).includes(q) || fold(s.matric_no || "DE").includes(q)
        || String(s.device_user_id).includes(q);
      this._rows[r].toggleAttribute("data-dimmed", !match);
      this._rows[r].toggleAttribute("data-match", Boolean(q) && match);
      shown += match ? 1 : 0;
    });
    // Said only while a search is narrowing the sheet: unfiltered, "259 students" repeated the figure
    // the course header shows directly above, and took the room the toolbar needed at 1366 wide.
    const count = this.querySelector(".sheet__count");
    count.textContent = !q ? ""
      : shown ? `${shown} of ${total} shown` : `No student matches "${this._filter.trim()}"`;
    count.hidden = !q;
  }

  // Replace one class's boxes and totals from GET /api/sessions/{id}/register, after a correction.
  // Nothing is re-rendered and focus does not move.
  replaceClass(sessionId, register) {
    const c = this._columns.findIndex((col) => col.slot.session_id === sessionId);
    if (c < 0) return;
    const byPerson = new Map(register.students.map((s) => [s.person_id, s]));
    this._data.students.forEach((student, r) => {
      const entry = byPerson.get(student.person_id);
      if (!entry) return;
      const cell = student.cells[c];
      Object.assign(cell, { state: entry.status, ticked: entry.present, first_scan: entry.first_scan,
        excusal_category: entry.excusal ? entry.excusal.category : null });
      // Updated in place, not replaced, so a focused box keeps focus.
      const el = this.box(r, FROZEN + c);
      const fresh = document.createElement("template");
      fresh.innerHTML = this.renderBox(student, cell, c);
      const model = fresh.content.firstElementChild;
      for (const name of ["data-state", "aria-label"]) el.setAttribute(name, model.getAttribute(name));
      el.toggleAttribute("aria-readonly", model.hasAttribute("aria-readonly"));
      el.textContent = model.textContent;
    });
    // The totals are this sheet's rows, counted, not the register's: on a group's sheet a class for
    // everybody holds the whole course, and its register totals would put every group's absences
    // under this group's column. For a course without groups the two are the same number.
    const states = this._data.students.map((student) => student.cells[c].state);
    const count = (...wanted) => states.filter((state) => wanted.includes(state)).length;
    const totals = { present: count("present", "marked_present"), absent: count("absent", "marked_absent"),
      excused: count("excused") };
    Object.assign(this._columns[c].slot, totals);
    for (const el of this.querySelectorAll(`[data-total][data-c="${c}"]`)) {
      // A class still taking attendance has nobody absent yet, so its absent total stays blank.
      el.textContent = register.open && el.dataset.total === "absent" ? "" : String(totals[el.dataset.total]);
    }
    this.querySelector(`.sheet__headrows [data-c="${c}"]`)
      ?.setAttribute("aria-label", this.columnName(this._columns[c]));
  }
}

customElements.define("hw-sheet", HwSheet);
