# Living sheet (`<hw-sheet>`)

Hero signature 1 of 3. Pipeline: `docs/COMPONENT-GUIDE.md`. Mockup: `design/mockups/AttendancesheetPCT201.png`.
Fixes the mockup needs: `docs/DESIGN-DEVIATIONS.md`, "12 Attendance sheet" and "8 Correction drawer".

| Step | State | Artefact |
|---|---|---|
| 1 Evidence card | Done 2026-09-19 | this file |
| 2 Spec | Done 2026-09-19 | this file |
| 3 Gallery | Done 2026-09-19, visual pass in light, dark and projection | `rollcall/static/gallery/sheet.html` |
| 4 Measure | Done 2026-09-19 on this machine; a lecturer's laptop still to do | "Measurements" below, `scripts/measure_sheet.mjs` |
| 5 Accessibility | Research applied 2026-09-19; axe-core (needs a download) and NVDA still to do | vault `50-Research/Living sheet grid, zoom and speed research 2026-09-19.md` |
| 6 Test with a person | Not started | |
| 7 Publish | Not started | |

## Redesign, 2026-09-23

Reported: "the ui for the sheet is too compact and isn't clean and professional", with a screenshot
of a 120-student course. What it showed, and what changed:

| Seen | Now |
|---|---|
| Matric numbers cut to "25/DUMMY01/00", long names cut in half, by fixed 128 px and 332 px columns | Both measured from their contents in the font they are drawn in (`fitColumns`, a canvas, 2.5 ms for 259 students); the name is capped at 420 px with the whole name in its tooltip and row header |
| Week columns 44 px, "WK 10" touching "WK 11", and the grid stopping two thirds across a wide window | Weeks are `minmax(52px, 1fr)`: at least 52 px, sharing whatever width is left |
| A box drawn round every one of about 3,000 cells | Lines between rows and between weeks only; a row under the pointer is shaded so it can be followed across the weeks |
| A tab row of actions, a lone "Compact rows" link on a line of its own, and Export PDF as a second blue button | One toolbar above the grid: the search and "7 of 12 classes held" on the left; row height as a two-way toggle, Sheet setup and both exports as plain buttons on the right (`sheet.tools`). The one primary action on a course is Start taking attendance |
| The week header was its label only | The label, and the week's first day under it ("WK 3", "31 Aug"); "now" for the week holding a class taking attendance |
| 13 px text in 40 px rows | 14 px text in 44 px rows; the compact toggle still gives 32 px |
| "7 of 13 classes held" under a header saying "7 of 12" | The sheet quotes the course's planned classes from the same place as the header (`planned_classes` in the contract), and its own boxes only when no plan is saved |
| "Showing all 259 students" beside a header saying "Students 259" | The count appears only while a search is narrowing the sheet |

Kept deliberately: ticks in ink and only absences in the absent colour, the capitals that match the
PDF, the frozen block with its strong rule, the sticky totals, and every keyboard and screen reader
behaviour below. Measured after it: the whole render and layout 24 to 37 ms; axe-core clean in both
themes; `check_layout.mjs` 0 findings at four widths.

**Editing a student, 2026-09-23.** A student's matric number and name are pressable: they open a
dialog to correct the name or matric number, or to add the number a direct-entry student did not
have (event `hw-sheet-edit-student`, handled by the screen, `PUT /api/people/{id}`). A missing
number reads "DE", for direct entry (changed from "no matric yet" on 2026-09-23, the lecturer's own mark). The S/N and the totals stay read-only.

**A class taking attendance** (`state: "open"` on a slot, `waiting` on a box): the column is tinted
and ruled in the accent down both sides, because the current week's tint alone is the same colour;
its boxes are blank until a student scans, then ticked; its present total grows and its absent total
stays blank until the class is ended; it is counted in nothing. `rollcall/live.py`.

## 1 Evidence card

**Need.** A lecturer sees the whole course's attendance as their own paper sheet, finds any student's
box in seconds, and opens it to correct it.

**Screens.** 12 Attendance sheet; 11 Course overview (Sheet tab). `docs/SCREENS.md`.

**Useful.** Journey 3, "Week to week" (Courses, Attendance sheet, Export PDF), runs through it, and so
does every correction started from the sheet, because clicking a box opens the correction drawer. The
PDF and Excel exports are the same data (`rollcall/sheet_export.py`), so what the lecturer checks on
screen is what they sign and hand in.

**Unique.** No other component shows every student against every class at once. The class register
(screen 7) is one class; the evidence timeline (21) is one student; the eligibility ledger (18) is one
decision per student. A generic data table cannot do this job: it would put 258 by 30 boxes in the tab
order, and it would not match the paper layout the lecturer already knows.

## 2 Spec

### Anatomy

1. **Warnings**, above everything, one per string in `warnings`, verbatim, each with the warning glyph.
2. **Toolbar**: the filter box ("Find a student in this sheet"), the match count, and on the right the
   orientation line ("18 of 30 classes held").
3. **Grid**, in one scroll container:
   - **Header row 1**: S/N, MATRIC NO., FULL NAME, then one header per week spanning its classes. The
     label is the week's `label` ("WK 1", "REVISION"), on one line.
   - **Header row 2**: class numbers, shown only under weeks with two or more classes.
   - **Frozen block**: S/N, MATRIC NO., FULL NAME, sticky on the left, with a 2 px `--hw-rule-strong`
     rule on its right edge. No shadow.
   - **Student rows**, home students first, then the **CARRY-OVER STUDENTS** section row, then carry-over
     students (the order `courses.members` returns).
   - **Totals**: PRESENT and ABSENT rows, pinned to the bottom of the scroll container above a 2 px rule.
   - **Horizontal scrollbar** spanning only the week columns, so the frozen block never appears to move.
     The container's own horizontal scrollbar is hidden and a separate bar under the week columns drives
     it; the two are kept in step both ways.
4. **Helper line** under the grid: "Select any box to correct it, or move between boxes with the arrow
   keys. Corrections are recorded with a note and never overwrite a scan." The arrow keys are named
   because keyboard users do not find them otherwise (Adrian Roselli's grid testing).
5. **Legend**: ✓ Present, ✕ Absent, E Excused, – Class not held (kept from the mockup), and ◥ Corrected,
   for the note marker a corrected box carries in its corner.

### Data contract

`GET /api/templates/{template_id}/sheet` (`templates.grid`), permission `register.read`. Nothing else.

| Field | Used for |
|---|---|
| `template.course_code`, `template.course_title` | the grid's accessible name |
| `weeks[].week_number`, `label`, `current`, `starts_on`, `ends_on` | week headers, current week tint |
| `weeks[].slots[].slot`, `state`, `session_id`, `date`, `start_time`, `present`, `absent` | class headers, column state, totals |
| `students[].sn`, `person_id`, `device_user_id`, `matric_no`, `full_name`, `kind` | frozen block, filter, section row |
| `students[].cells[].week`, `slot`, `state`, `first_scan`, `excusal_category` | each box |
| `total_registered`, `carry_over`, `classes_held` | match count, orientation line |
| `warnings` | warnings |

The orientation line's "of 30" is the sum of `weeks[].classes`, read from the contract, not stored.
`current`, the slot `state` and `excusal_category` were added on 2026-09-19 so that nothing is derived
on the page (`tests/test_templates.py`, `test_the_sheet_states_each_box_and_the_current_week_itself`).

The component computes no attendance. After a correction it takes the new cell and the class's new
totals from `GET /api/sessions/{id}/register` and replaces them; it never adds or subtracts.

### Cell states

| `state` | Glyph | Colour | Accessible word |
|---|---|---|---|
| `present` | ✓ | `--hw-ink` | present, first scan 10:51 |
| `marked_present` | ✓ with note marker | `--hw-ink` | present, corrected |
| `absent` | ✕ | `--hw-absent` | absent |
| `marked_absent` | ✕ with note marker | `--hw-absent` | absent, corrected |
| `excused` | E | `--hw-excused` | excused, medical (the category) |
| `not_held` | – | `--hw-ink-muted` on `--hw-sunken` | class not held |
| `upcoming` | blank | none | not yet held |
| `waiting` | blank, in a column ruled in the accent | none | not scanned yet, the class is still taking attendance |

Tick in ink and cross in `--hw-absent` is the settled rule (DESIGN-DEVIATIONS, screen 12): the normal
case stays quiet and absences are spotted, not read. **Not held is a property of the column**: the whole
column, its class header and its totals are greyed, and its totals show "–" (one character everywhere).
An upcoming column's totals are blank, like its boxes, so it never looks like a class that was missed.
A single not-held box among ticks cannot occur, because the contract states it once per slot.

The current week's column, both header rows included, is tinted `--hw-accent-soft`.

### Component states

| State | What shows | Copy |
|---|---|---|
| Loading | Header rows real, 10 skeleton rows, `aria-busy="true"` | (announced) "Loading the sheet" |
| Error | Glyph, heading, remedy, Try again | "The sheet did not load." / "Herewise may have stopped. Check its window is still open, then try again." |
| No students | Empty state: icon, heading, description, action | "No students on this course yet" / "Import the level's roster or add carry-over students. They appear here in the order of the paper sheet." / Add students |
| No start date | The grid, every box blank, and the contract's warning | the backend's warning, verbatim |
| No classes yet | The grid, every box blank or –, and a line above it | "No classes held yet. They appear here after you get attendance from the device." |
| Extra classes | The grid, and the contract's warning with a link to Sheet setup | the backend's warning, verbatim; link "Change the weeks" |
| Data | as specified | |
| Filtering | Non-matching rows dimmed, never removed; totals unchanged | "14 of 258 shown" / "Showing all 258 students" / "No student matches "okafor"" |
| Viewer | Identical. Boxes still open; the drawer carries the refusal | (drawer) |
| Gated | None of its own. While a pull runs the screen, not the sheet, says so | |

Viewer: the sheet is the same for everyone with `register.read`. What a box does when opened depends on
`register.correct`, `register.request` or neither, and that is the drawer's job, so the sheet never
hides or disables boxes by permission.

### Behaviour: WAI-ARIA grid

Interactive cells mean `grid` (`docs/COMPONENT-GUIDE.md`). Built from `div`s with ARIA roles, not a
`<table>`: `content-visibility` needs containment, which does not apply to table row groups.

- `role="grid"` on the sheet, labelled "Attendance sheet, PCT 201 Pharmaceutics". **No `aria-rowcount`,
  `aria-colcount`, `aria-rowindex` or `aria-colindex`:** every row is in the DOM, so the browser counts
  them, and APG warns that missing or inconsistent values can stop screen reader table reading.
  `content-visibility` does not remove rows from the accessibility tree.
- Header cells `role="columnheader"`; FULL NAME and the totals labels `role="rowheader"`; everything else
  `role="gridcell"`.
- **Every data cell is focusable**, S/N, matric, name and both totals rows included. APG requires it:
  screen readers in application mode read only what can take focus. The section row is skipped.
- **Roving tabindex, one tab stop.** The focused cell has `tabindex="0"`, every other `-1`. Tabbing back
  into the sheet returns to the last focused cell.
- **A box is named by its status alone**: "present, first scan 10:51", "excused, medical", "class not
  held". Screen readers announce the row header (the student) when focus changes row and the column
  header ("week 4, class 2, Tuesday 6 October 09:00") when it changes column, as the APG data grid
  examples rely on; repeating them in every label was heard twice. Column headers carry no counts,
  because the totals can be reached. **To confirm with NVDA**, including how two header rows with
  `aria-colspan` are read.
- Upcoming and not-held boxes are `aria-readonly="true"`, not `aria-disabled`: read-only means "not
  editable but otherwise operable" and stays focusable, while disabled means not operable. They say why
  when opened ("No class was held in week 3." / "Week 9 has not happened yet.") in a polite live region.

| Key | Action |
|---|---|
| Arrow keys | Move one cell. Up and Down skip the section row and, while filtering, dimmed rows |
| Home / End | First / last cell in the row (S/N / the last box) |
| Ctrl+Home / Ctrl+End | First cell of the first row / last cell of the ABSENT row |
| Page Up / Page Down | One screenful of rows |
| Enter / Space | On a box: open the correction drawer, or announce why it cannot be corrected. Elsewhere: nothing |
| Escape (drawer open) | Close the drawer; focus returns to the box it was opened from |
| Enter in the filter box | Apply any pending filter, then focus the first matching row in the current column |

Click moves focus to the clicked cell and, on a box, does what Enter does.

**Events.** Opening a box dispatches `hw-sheet-open` (bubbles) with `{person_id, session_id, week,
slot, state}`. The drawer is a separate component; the sheet does not know which drawer variant opens.
**Method.** `sheet.replaceClass(session_id, register)` takes a `GET /api/sessions/{id}/register`
response and updates that column's boxes and totals in place, without re-rendering or moving focus.

**Filter.** Matches `full_name`, `matric_no` and `device_user_id`, case-insensitive, as typed. Rows that
do not match get `data-dimmed` and muted ink, their status colours included; they stay in the DOM and in
the accessibility tree, and the totals keep describing the whole course. Matching rows get `data-match`:
the selection tint on their frozen block and a heavier name. The typed letter paints first and the rows
update 120 ms after typing pauses. **Not opacity:** per-row opacity made the first letters take 520 to
784 ms to paint on this machine; colour takes 32 to 72 ms. Muted ink also keeps 4.5:1, where 35% opacity
did not, and a dimmed row is still content someone can focus and read.

**Narrow and short windows.** WCAG 1.4.10 exempts the grid itself from reflow, not the sticky parts
around it, and 2.4.11 fails if the focused cell is hidden under them.
- 900 px wide or less (200% zoom on a 1366 laptop): only the name stays frozen, at 200 px, and the
  native horizontal scrollbar returns. About 8 boxes show beside it, against about 3 with all three
  columns frozen.
- 600 px or less (400% zoom): the name is 128 px. At 200 px it covered the focused box.
- 560 px tall or less: the totals scroll with the sheet instead of sticking, and the sheet may use the
  window's height.

**Density.** `density="compact"` gives 32 px rows (`docs/DESIGN-BRIEF.md`). The screen owns the toggle.

### Copy

All strings are in the tables above. Headings in capitals match the PDF: S/N, MATRIC NO., FULL NAME,
CARRY-OVER STUDENTS, PRESENT, ABSENT. British English, no em dashes, no exclamation marks. Names are
shown as the contract gives them, never re-cased.

**Backend copy to fix (not done):** the extra-classes warning ends "or cancel the extra session."
Every screen says "class" (known gap 15 records the same word in the cancel refusal).

### Tokens

Colour: `--hw-paper`, `--hw-surface`, `--hw-sunken`, `--hw-rule`, `--hw-rule-strong`, `--hw-ink`,
`--hw-ink-muted`, `--hw-accent-soft`, `--hw-absent`, `--hw-absent-soft`, `--hw-excused`, `--hw-focus`,
from `rollcall/static/css/tokens.css` (generated by `design/palette.py`).

Size, space, radius and row height: `rollcall/static/css/base.css`, which states the scale in
`docs/DESIGN-BRIEF.md` as `--hw-` properties. Not generated, because nothing derives them.

### Open points

- **Excused counts: the owner's decision.** Like the PDF, the totals show PRESENT and ABSENT only, so a
  column with excused students sums to less than the course (week 1 class 1: 238 + 31 of 270). No
  outside practice settles this; it is the lecturer's own paper layout. The column headers no longer
  carry the excused count, so for now it is not on the sheet at all.
- **Which laptop is the target?** The sheet meets the budget up to 4x slowdown of this i5-8365U. The
  lecturer's own machine, or one run of `scripts/measure_sheet.mjs` on it, confirms the margin.
- **Screen reader and axe passes.** The labelling rests on APG and a second source, not on a test with
  NVDA. axe-core is MPL-2.0 and runs from a local file, but it is not on this machine: bundling it needs
  a download.

**Projection** (`projection` attribute): 48 px rows, 52 px boxes, bold marks at 20 px, absent and
excused boxes on their soft fills, ticks unfilled, and no muted ink anywhere, per the brief.

## Measurements

2026-09-19. **Method:** `scripts/measure_sheet.mjs`, headless Chrome 145 (Playwright's cached build)
over the DevTools protocol, 1366 by 768, real key presses 150 ms apart and real typing 250 ms apart.
Latency is the Event Timing API's duration, the span INP measures (input delay, handlers and the next
frame painted), plus long animation frames while typing so deferred work cannot hide. Three rounds of
20 presses per run, on a quiet machine.

**Older laptops.** The lecturer's laptop may be older than this one (Intel Core i5-8365U, 2019), so the
sheet is measured at 1x, 2x, 3x and 4x CPU slowdown, the higher settings standing for older Core i3 and
Celeron machines. Benchmark sites disagree on exact ratios between processors, so no single multiplier
is claimed to be "the" old laptop. Runs from 2026-09-19 evening, one after another, CPU load recorded:

| `sheet-30` (9,344 elements) | Arrow median | Arrow 90th pct | Arrow worst | Filter keystroke worst | Longest frame while typing | First render |
|---|---|---|---|---|---|---|
| 1x | 24 ms | 32 ms | 48 ms | 32 ms | none over 50 ms | 81 to 159 ms |
| 2x | 24 ms | 32 ms | 48 ms | 32 ms | none over 50 ms | 214 to 352 ms |
| 3x | 32 ms | 48 ms | 64 ms | 32 to 64 ms | 82 ms | 420 to 713 ms (976 cold) |
| 4x, twice (load 30 to 33%) | 48 ms | 64 ms | 80 to 88 ms | 88 to 104 ms | 154 ms | 602 to 1,234 ms |

The 24-box and 40-student sheets were measured at 2x and 3x as well and are faster. Budget: under
200 ms. Met at every setting.

**Correction.** Earlier the same day a 40-student control sheet failed at 4x (arrow median 288 ms), and
this file concluded that 4x on this machine measured the harness, not the component. The same test
under the conditions above passes at 4x. The earlier runs were most likely taken under background
load that was not recorded; the filter was also slower before it was changed to dim by colour. The
harness now records CPU load before and after every run.

**What was learned getting here**, in the order found:
- Timing by script alone missed the cost: it was all in style, layout and paint after the handlers
  (2 to 3 ms).
- A stray file search left running from earlier in the session had been loading the CPU; every number
  before it was stopped is void. Check the machine's load before believing a slow result.
- Running two large sheets one after another in one browser produced a repeatable 670 ms stall in frame
  production, absent when each ran alone. Measure one fixture per browser.
- A window moved off screen is throttled as hidden, even with the flags meant to stop it, so the
  GPU-painted comparison could not be made this way.
- `content-visibility: auto` halves the arrow-key cost and cuts first render by about three quarters;
  it stays. Freezing fewer columns and dropping `z-index` on focus made no measurable difference.

DOM size: over the guide's 1,400 target (a Lighthouse figure), with `content-visibility` doing the job
the guide expected of it. Virtualisation was not needed, and would cost what this sheet is for:
screen readers hear only the rows drawn, and find-in-page cannot reach the rest.

**Still to measure:** a lecturer's actual laptop, once known; the drawer opening, when it exists.

Checked by script in the gallery, not yet by a person:

- One tab stop; every data cell reachable, totals included; Home reaches S/N; only boxes open the drawer.
- Enter on a not-held or upcoming box announces why. Down from the last home student skips the section row.
- Scrolled 300 px right and 400 px down: names, header and totals did not move; boxes moved 300 px.
- The bar under the weeks starts at the frozen edge (508 px) and has the same range as the sheet (341 px).
- At 400% zoom the focused cell was fully visible in four positions, far right and last row included.
- The name column fits a real 40 character name (296 px at 13 px, 362 px projected).
