// Screen 24 Enrolment session, with screen 25 Consent confirmation and screen 26 Keypad password
// instead. Mockups: Enrollinglivecapture.png, Enrollingtimedout.png, Enrollinglevelcomplete.png,
// Enrollingdevicebusy.png, Enrollmentconsent*.png, Enrollmentkeypadpassword.png, Keypadpassword*.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "24", "25" and "26".
//
// This screen is read from two metres away, standing at the terminal, and driven from the keyboard.
// Kept from the mockup: two large finger slots, the keyboard legend always visible, the queue.
//
// Fixed from the mockups:
//   when enrolment finishes, nothing still describes it running: the banner clears, the chip returns
//     to connected and the queue empties. The mockup's completion frame said "0 to go" beside a
//     panel listing the next five students;
//   the captured slot carries a large tick and the waiting slot a distinct outline, so the pair
//     never relies on green against blue, which is what two metres away costs;
//   the running banner does not use a question mark: a question mark means review or unknown, and a
//     running process is neither;
//   the consent scrim covers the whole window, not only the content;
//   "Not now" gets the text-button treatment, because declining must be as easy as agreeing;
//   a disabled field is empty, and a disabled control is --hw-sunken with muted ink, never a pale
//     tint of the enabled colour.
//
// Rebuilt on 2026-09-21 after the first real enrolment, which found four things at once. The screen
// and the backend had never agreed on their words: the backend enrols ZKTeco's finger 6 and 7 while
// this screen named 6 and 7 but was handed 0 and 1, so pressing Enrol started the terminal and then
// threw on a name it could not find, and said "The capture did not start" while it plainly had; and
// it watched for job states called "waiting" and "capturing" that the backend never sends, so a
// capture read as finished the moment it began. Beyond that, a lecturer could not choose who to
// enrol, could not see who was already done, could not take off a finger captured by mistake, and
// could not stop a capture. All four are here now.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  panel, invalid, matricText,
  announce, button, dialog, emptyState, field, fill, h, loadingCards, longDate, page, pill, plural, section,
  setBusy, table, toast, withProgress,
} from "../ui.js";

// ZKTeco numbers the fingers from the left little finger. The backend enrols 6 and 7, and any
// other index can still turn up: a student enrolled at the keypad, or by an older version.
const FINGERS = {
  0: "Left little finger", 1: "Left ring finger", 2: "Left middle finger", 3: "Left index finger",
  4: "Left thumb", 5: "Right thumb", 6: "Right index finger", 7: "Right middle finger",
  8: "Right ring finger", 9: "Right little finger",
};
const EXPECTED = [6, 7];
const RUNNING = ["pushing", "waiting_for_finger"];
const POLL_MS = 700;

function fingerName(index) {
  return FINGERS[index] || `Finger ${index}`;
}

function fullName(student) {
  return `${student.surname} ${student.other_names}`.trim();
}

export default {
  id: "enrolment",
  title: "Enrolment",
  permission: "enrollment.run",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Enrolment", children: [loadingCards(2)] }));

    const levels = await api.get("/api/levels");
    const level = levels.find((l) => l.students) || levels[0];
    // Which terminal to read back from when a capture produces nothing. Not fatal if it cannot be
    // read: without it the screen simply does not offer the way round.
    const devices = await api.get("/api/devices").catch(() => []);
    const device = devices.find((d) => d.is_default) || devices[0] || null;
    const state = { levelId: level?.id ?? null, job: null, timer: null, chosenId: null, query: "",
      deviceId: device?.id ?? null, restartHost: null };
    const reload = async () => {
      const progress = await api.get(`/api/levels/${state.levelId}/students`);
      draw(host, levels, state, progress, reload, ctx);
    };
    await reload();
    view.addEventListener("hw-screen-left", () => clearTimeout(state.timer), { once: true });
  },
};

function draw(host, levels, state, progress, reload, ctx) {
  const level = levels.find((l) => l.id === state.levelId);
  const running = state.job && RUNNING.includes(state.job.state);
  // Whoever was chosen from the list, otherwise the first student who still needs something.
  const chosen = state.chosenId && progress.students.find((s) => s.id === state.chosenId);
  const current = chosen || progress.students.find((s) => !s.complete) || null;

  // A level with nobody on it has nothing to enrol, which is not the same as being enrolled. It said
  // "100 Level is enrolled ... Every student on this level has two fingers" over an empty list, and
  // the list said No student matches "" (reported 2026-09-24).
  if (level && !progress.total) {
    fill(host, page({
      title: "Enrolment",
      subtitle: `${level.name} · nobody on it yet`,
      actions: [levelPicker(levels, state, reload)],
      children: [
        running ? runningBanner(state, reload, ctx) : null,
        emptyState({
          icon: "○",
          heading: `Nobody on ${level.name} yet`,
          body: "Import the level's roster first, then send it to the terminal. The students come "
            + "here to be enrolled, one after another.",
          action: session.can("roster.manage")
            ? h("a", { class: "hw-button hw-button--primary", href: href(`levels/${level.id}/import`) },
              "Import roster")
            : null,
        }),
      ],
    }));
    return;
  }

  fill(host, page({
    title: "Enrolment",
    subtitle: level
      ? `${level.name} · ${progress.complete} of ${progress.total} done`
      : "No level has students yet",
    actions: [levelPicker(levels, state, reload)],
    children: [
      running ? runningBanner(state, reload, ctx) : null,
      state.restartHost,
      progressBar(progress),
      current
        ? capture(current, state, reload, ctx, Boolean(chosen))
        : h("div", { class: "hw-panel", dataset: { tone: "success" }, role: "status" },
          h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✓"),
          h("div", {},
            h("p", { class: "hw-panel__title" },
              level ? `${level.name} is enrolled` : "Nothing to enrol"),
            h("p", { class: "hw-panel__body" },
              "Every student on this level has two fingers or a keypad password. The device is free "
              + "for attendance again. Anybody can still be picked from the list below, to take a "
              + "finger off or add another."))),
      everyone(progress, state, reload),
      keyboardLegend(),
    ],
  }));
}

function levelPicker(levels, state, reload) {
  const select = h("select", { class: "hw-select", "aria-label": "Level",
    style: { minWidth: "220px" } });
  for (const level of levels) {
    const option = h("option", { value: level.id },
      level.students ? `${level.name} · ${plural(level.students, "student")}` : `${level.name} · no students yet`);
    if (level.id === state.levelId) option.selected = true;
    select.append(option);
  }
  select.addEventListener("change", () => {
    state.levelId = Number(select.value);
    state.chosenId = null;
    reload();
  });
  return select;
}

function progressBar(progress) {
  const percent = progress.total ? Math.round((progress.complete / progress.total) * 100) : 0;
  return h("div", { class: "hw-stack hw-stack--tight", style: { marginBlockEnd: "var(--hw-space-6)" } },
    h("div", { class: "hw-gauge", role: "img",
      "aria-label": `${progress.complete} of ${progress.total} students done` },
      h("span", { class: "hw-gauge__fill", style: { width: `${percent}%` } })),
    h("p", { class: "hw-muted", style: { margin: 0 } },
      `${progress.two_fingers} with two fingers · ${progress.one_finger} with one · `
      + `${progress.password_only} on keypad passwords · `
      + `${progress.total - progress.complete} to go · ${progress.total} in this level`));
}

function runningBanner(state, reload, ctx) {
  ctx.shell.setDevice("busy");
  const stop = button({ label: "Stop the capture", variant: "destructive", busyLabel: "Stopping",
    onClick: async () => {
      setBusy(stop, true);
      try {
        await api.post("/api/enrollment/cancel", {});
        toast("The capture is stopped. The terminal is free again.");
        announce("The capture is stopped.");
      } catch (error) {
        toast(error instanceof ApiError ? error.message : "That did not stop.", "failure");
      } finally {
        setBusy(stop, false);
        state.job = null;
        await reload();
      }
    } });
  const waiting = state.job.state === "waiting_for_finger";
  const left = secondsLeft(state.job);
  const restart = waiting ? restartButton(state, reload, ctx) : null;
  return h("div", { class: "hw-panel", dataset: { tone: "info" }, role: "status",
    style: { marginBlockEnd: "var(--hw-space-6)" } },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "i"),
    h("div", {},
      h("p", { class: "hw-panel__title" },
        waiting
          ? (left === null ? "Waiting for the finger"
            : `Waiting for the finger · ${plural(left, "second")} left`)
          : "Sending the student to the terminal"),
      h("p", { class: "hw-panel__body" },
        "The device is held by this enrolment, so attendance cannot be read from it until the "
        + "capture finishes, times out, or is stopped."),
      // A lecturer standing at the terminal is the only one who can tell a terminal that is
      // waiting from a terminal that took the command and did nothing, and on 2026-09-22 a K40
      // did exactly that: it answered the enrol command with OK and never changed its screen.
      // Saying what the terminal ought to be showing turns a silent minute into a fact.
      waiting
        ? h("p", { class: "hw-panel__body" },
          "The terminal itself should be asking for a finger now. If its own screen has not "
          + "changed, it did not take the command. Restart it from here, which takes about 35 "
          + "seconds and keeps everyone and every fingerprint on it, then press Enrol again.")
        : null,
      h("p", { class: "hw-row", style: { margin: "var(--hw-space-3) 0 0" } }, stop, restart)));
}

// A capture that produced nothing leaves the lecturer standing at the terminal with nowhere to go,
// and the way round was on another screen entirely: enrol the finger at the terminal's own menu,
// then read the terminal back. That is the documented answer when remote capture does not work on
// a firmware, so it belongs at the moment it is needed rather than three clicks away.
function otherWay(state, reload) {
  const read = button({ label: "Read the fingerprints off the terminal", permission: "device.manage",
    busyLabel: "Reading the terminal",
    disabled: state.deviceId === null,
    reason: state.deviceId === null ? "No terminal is set up to read." : "",
    onClick: async () => {
      setBusy(read, true);
      try {
        const found = await api.post(`/api/devices/${state.deviceId}/sync-fingers`, {});
        toast(`The terminal holds ${plural(found.device_users, "person", "people")} and `
          + `${plural(found.templates, "fingerprint")}. This register now says the same.`);
        announce("The register now matches the terminal.");
        state.job = null;
        await reload();
      } catch (error) {
        toast(error instanceof ApiError ? error.message : "The terminal did not answer.", "failure");
      } finally {
        setBusy(read, false);
      }
    } });
  return h("div", { class: "hw-stack hw-stack--tight", style: { marginBlockStart: "var(--hw-space-3)" } },
    h("p", { class: "hw-panel__body", style: { margin: 0 } },
      "If the terminal never asked for a finger, restart it from here and try again: that is what "
      + "brought a terminal back that had stopped taking captures. Or enrol the finger at the "
      + "terminal itself, under Menu, User Manage, then read the terminal back here. A fingerprint "
      + "enrolled at the keypad counts exactly the same."),
    h("p", { class: "hw-row", style: { margin: 0 } }, restartButton(state, reload), read));
}

// A terminal can get into a state where it answers the enrol command with OK and never asks for a
// finger. On 2026-09-22 the K40 did that for over an hour: nothing sent to it changed it, and a
// restart did, after which it asked twice in a row. What puts it there is not known yet; a capture
// that succeeds, one that is stopped and one that times out were each tested and do not. So the cure
// is offered where the fault is noticed, beside the capture, rather than on the Device screen.
function restartButton(state, reload, ctx) {
  const go = button({ label: "Restart the terminal", permission: "device.manage",
    busyLabel: "Restarting",
    disabled: state.deviceId === null,
    reason: state.deviceId === null ? "No terminal is set up to restart." : "",
    onClick: async () => {
      setBusy(go, true);
      state.restartHost = h("div", { style: { marginBlockEnd: "var(--hw-space-6)" } });
      try {
        if (state.job && RUNNING.includes(state.job.state)) {
          await api.post("/api/enrollment/cancel", {});
        }
        clearTimeout(state.timer);
        state.job = null;
        await reload();
        ctx?.shell.setDevice("busy");
        await withProgress(state.restartHost,
          api.post(`/api/devices/${state.deviceId}/restart`, {}),
          { whileWaiting: "Restarting the terminal",
            done: (answer) => `The terminal is back after ${answer.back_after_seconds} seconds. `
              + "Press Enrol to try again." });
        ctx?.shell.setDevice("connected");
        announce("The terminal is back. Press Enrol to try again.");
      } catch (error) {
        state.restartHost = null;
        toast(error instanceof ApiError ? error.message : "The terminal did not restart.", "failure");
        await reload();
      } finally {
        setBusy(go, false);
      }
    } });
  return go;
}

function secondsLeft(job) {
  if (!job.waiting_since || !job.waits_for_seconds) return null;
  const since = Date.parse(job.waiting_since);
  if (Number.isNaN(since)) return null;
  const gone = Math.floor((Date.now() - since) / 1000);
  return Math.max(0, job.waits_for_seconds - gone);
}

// -- the capture card ----------------------------------------------------------------------------

function capture(student, state, reload, ctx, chosen) {
  const done = student.fingers || [];
  const waitingFor = state.job && state.job.state === "waiting_for_finger"
    && state.job.person_id === student.id ? state.job.finger_index : null;
  // The two this app asks for, plus any other finger the student turns out to have.
  const shown = [...EXPECTED, ...done.filter((f) => !EXPECTED.includes(f))];

  const slots = h("div", { class: "hw-slots" }, ...shown.map((index) => {
    const captured = done.includes(index);
    const active = !captured && index === waitingFor;
    return h("div", { class: "hw-slot",
      dataset: { state: captured ? "done" : active ? "waiting" : "todo" } },
      h("p", { class: "hw-slot__mark", "aria-hidden": "true" }, captured ? "✓" : active ? "◎" : "○"),
      h("p", { class: "hw-slot__name" }, fingerName(index)),
      h("p", { class: "hw-slot__note" },
        captured ? "Captured" : active ? "Put the finger on the reader" : "Waiting"),
      captured
        ? h("p", { style: { margin: "var(--hw-space-2) 0 0" } },
          button({ label: "Remove", variant: "destructive",
            onClick: () => removeFingerDialog(student, index, reload) }))
        : null);
  }));

  const next = student.next_finger ?? EXPECTED.find((f) => !done.includes(f)) ?? null;
  const start = button({ label: next === null ? "Both fingers are in" : `Enrol ${fingerName(next).toLowerCase()}`,
    primary: true, glyph: "↵", busyLabel: "Waiting for the finger",
    disabled: next === null,
    reason: next === null ? "This student has both fingers on the terminal already." : "",
    onClick: () => begin(student, next, state, reload, ctx) });

  const skip = button({ label: "Use a keypad password instead", permission: "device.manage",
    onClick: () => keypadDialog(student, reload) });

  const failed = state.job && state.job.outcome && state.job.outcome !== "captured"
    && state.job.outcome !== "cancelled" && !RUNNING.includes(state.job.state);
  const message = state.job && state.job.detail && !RUNNING.includes(state.job.state)
    ? h("div", { class: "hw-panel",
        dataset: { tone: state.job.outcome === "captured" ? "success" : "failure" }, role: "status" },
      h("span", { class: "hw-panel__glyph", "aria-hidden": "true" },
        state.job.outcome === "captured" ? "✓" : "✕"),
      h("div", {},
        h("p", { class: "hw-panel__body" }, state.job.detail),
        failed ? otherWay(state, reload) : null))
    : null;

  return section(chosen ? "Chosen student" : "Next student",
    h("div", { class: `hw-card hw-stack${chosen ? " hw-card--sticky" : ""}` },
      h("div", { class: "hw-row hw-row--between" },
        h("div", {},
          h("p", { class: "hw-slot__who" }, fullName(student)),
          h("p", { class: "hw-muted hw-ids", style: { margin: 0 } },
            `${matricText(student.matric_no)} · device ID ${student.device_user_id}`
            + (student.consent_recorded_at
              ? ` · consent recorded ${longDate(student.consent_recorded_at)}` : ""))),
        chosen
          ? button({ label: "Back to the queue",
            onClick: () => { state.chosenId = null; reload(); } })
          : null),
      student.has_password
        ? h("p", { class: "hw-muted", style: { margin: 0 } },
          `On a keypad password instead of a fingerprint${student.password_reason
            ? `: ${student.password_reason}` : "."}`)
        : null,
      slots,
      message,
      h("div", { class: "hw-row hw-row--between" }, skip, start)));
}

// -- everyone on this level ----------------------------------------------------------------------

function statusOf(student) {
  const fingers = student.fingers || [];
  if (fingers.length >= 2) return { tone: "present", glyph: "✓", word: "Two fingers" };
  if (fingers.length === 1) return { tone: "review", glyph: "◑", word: "One finger" };
  if (student.has_password) return { tone: "excused", glyph: "#", word: "Keypad password" };
  return { tone: "neutral", glyph: "○", word: "Not started" };
}

function everyone(progress, state, reload) {
  const search = h("input", { class: "hw-input", type: "search", value: state.query,
    placeholder: "Find a student on this level", autocomplete: "off",
    "aria-label": "Find a student on this level" });
  const list = h("div");
  const shown = h("span", { class: "hw-muted", role: "status" });

  const paint = () => {
    const q = state.query.trim().toLowerCase();
    const rows = q
      ? progress.students.filter((s) => `${fullName(s)} ${matricText(s.matric_no)} ${s.device_user_id}`
        .toLowerCase().includes(q))
      : progress.students;
    shown.textContent = rows.length === progress.students.length
      ? `Showing all ${plural(progress.students.length, "student")}`
      : `Showing ${rows.length} of ${progress.students.length}`;
    fill(list, rows.length
      ? table({
        caption: "Everyone on this level and what they have given",
        rows,
        limit: 25,
        what: "student",
        columns: [
          { label: "Matric no.", render: (s) => h("span", { class: "hw-ids" }, matricText(s.matric_no)) },
          { label: "Name", render: (s) => fullName(s) },
          { label: "Device ID", align: "end", render: (s) =>
            h("span", { class: "hw-ids" }, String(s.device_user_id)) },
          { label: "Fingers", render: (s) => (s.fingers || []).length
            ? (s.fingers || []).map((f) => fingerName(f).replace(/^(\w+) (\w+).*/, "$1 $2")).join(", ")
            : h("span", { class: "hw-muted" }, "–") },
          { label: "State", render: (s) => {
            const how = statusOf(s);
            return pill(how.word, { word: how.word, glyph: how.glyph, tone: how.tone });
          } },
          { label: "", align: "end", render: (s) => button({
            label: state.chosenId === s.id ? "Chosen" : "Choose",
            disabled: state.chosenId === s.id,
            reason: state.chosenId === s.id ? "This student is on the card above." : "",
            onClick: () => {
              // Your place in the list is kept. It used to scroll back to the top, which is where
              // the card is, and a lecturer picking somebody out of turn lost the row they were
              // reading and had to find it again (reported on a second run, 2026-09-22). The card
              // sticks to the top of the window instead, so the capture is always one press away
              // without the page moving underneath anybody.
              const where = window.scrollY;
              state.chosenId = s.id;
              reload();
              requestAnimationFrame(() => window.scrollTo({ top: where }));
            } }) },
        ],
      })
      : h("div", { class: "hw-table-frame" }, h("div", { class: "hw-state" },
        h("span", { class: "hw-state__icon", "aria-hidden": "true" }, "⌕"),
        h("h2", { class: "hw-state__heading" }, `No student matches "${state.query.trim()}"`),
        h("p", { class: "hw-state__body" }, "Check the spelling, or try the matric number."))));
  };

  search.addEventListener("input", () => { state.query = search.value; paint(); });
  paint();

  return section("Everyone on this level",
    h("div", { class: "hw-row hw-row--between", style: { marginBlockEnd: "var(--hw-space-4)" } },
      h("div", { style: { flex: "0 1 380px" } }, search), shown),
    list,
    h("p", { class: "hw-section__help" },
      "Choose anybody to enrol them out of order, or to take a finger off one that was captured by "
      + "mistake. The queue itself always offers whoever still needs something."));
}

function keyboardLegend() {
  return h("p", { class: "hw-legend" },
    h("kbd", {}, "Enter"), " starts the capture for the student on screen. ",
    h("kbd", {}, "Esc"), " stops waiting. The queue moves on by itself once two fingers are in.");
}

// -- running one capture ---------------------------------------------------------------------

async function begin(student, fingerIndex, state, reload, ctx) {
  if (fingerIndex === null || fingerIndex === undefined) {
    toast("This student has both fingers on the terminal already.", "failure");
    return;
  }
  if (!student.consent_recorded_at) {
    const agreed = await consentDialog(student);
    if (!agreed) return;
  }
  state.restartHost = null;
  try {
    state.job = await api.post("/api/enrollment/start", { person_id: student.id,
      finger_index: fingerIndex, consent_confirmed: true });
    announce(`Waiting for the ${fingerName(fingerIndex).toLowerCase()}.`);
    await reload();
    poll(state, reload, ctx);
  } catch (error) {
    toast(error instanceof ApiError ? error.message : "The capture did not start.", "failure");
  }
}

function poll(state, reload, ctx) {
  clearTimeout(state.timer);
  state.timer = setTimeout(async () => {
    try {
      state.job = await api.get("/api/enrollment/status");
    } catch {
      state.job = null;
    }
    if (state.job && RUNNING.includes(state.job.state)) {
      poll(state, reload, ctx);
      await reload();
      return;
    }
    // Finished: nothing on the screen still describes it running.
    ctx.shell.setDevice("connected");
    const job = state.job;
    if (job && job.outcome === "captured") {
      toast("The finger is captured.");
      announce("Captured.");
    } else if (job && job.outcome === "cancelled") {
      announce("The capture was stopped.");
    } else if (job && job.detail) {
      toast(job.detail, "failure");
    }
    await reload();
  }, POLL_MS);
}

// -- taking a finger off again ---------------------------------------------------------------

function removeFingerDialog(student, index, reload) {
  const go = button({ label: "Take it off the terminal", variant: "destructive",
    busyLabel: "Taking it off" });
  const box = dialog({
    title: `Remove the ${fingerName(index).toLowerCase()}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        `${fullName(student)} has this finger on the terminal. Taking it off deletes the template `
        + "from the terminal itself, so they cannot scan with it until it is enrolled again."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "Scans already stored keep counting: this changes what the terminal can recognise from now "
        + "on, not the register behind it.")),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      await api.del(`/api/people/${student.id}/fingers/${index}`);
      box.close();
      toast(`The ${fingerName(index).toLowerCase()} is off the terminal.`);
      announce("The finger is removed.");
      await reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}

// -- screen 25: consent --------------------------------------------------------------------------

function consentDialog(student) {
  return new Promise((resolve) => {
    let answered = false;
    const tick = h("input", { type: "checkbox" });
    const go = button({ label: "Confirm and start", primary: true, disabled: true });
    const goButton = go.matches("button") ? go : go.querySelector("button");
    const reason = h("p", { class: "hw-reason" }, "Tick the box to confirm.");
    tick.addEventListener("change", () => {
      goButton.disabled = !tick.checked;
      reason.hidden = tick.checked;
    });

    const box = dialog({
      title: "Before the first fingerprint",
      body: h("div", { class: "hw-stack" },
        h("p", { style: { margin: 0 } },
          `${fullName(student)} has not given consent yet. `
          + "Fingerprints are sensitive personal data under the Nigeria Data Protection Act 2023."),
        // Statements, not statuses, so they are plain bullets with no ticks.
        h("ul", { class: "hw-stack hw-stack--tight", style: { paddingInlineStart: "var(--hw-space-6)" } },
          h("li", {}, "The reader keeps a template, not a picture of the finger."),
          h("li", {}, "It is used to mark attendance for this course and nothing else."),
          h("li", {}, "It stays on this computer and on the terminal, and goes nowhere online."),
          h("li", {}, "Anyone who would rather not give one can use a keypad password instead.")),
        h("label", { class: "hw-choice" }, tick,
          h("span", { class: "hw-choice__label" },
            "I have told this student how their fingerprint is used, and they have agreed"))),
      actions: [
        // Declining is as easy as agreeing: a real control, not muted text.
        button({ label: "Not now", onClick: () => { answered = true; box.close(); resolve(false); } }),
        h("span", { class: "hw-cardfoot__end hw-control hw-control--end" }, go, reason),
      ],
      onClose: () => { if (!answered) resolve(false); },
    });
    goButton.addEventListener("click", () => { answered = true; box.close(); resolve(true); });
  });
}

// -- screen 26: a keypad password instead ---------------------------------------------------------

export function keypadDialog(student, reload) {
  const password = field({ label: "Keypad password", type: "password", inputmode: "numeric",
    help: "1 to 8 digits, typed at the device's own keypad instead of a fingerprint.",
    validate: (v) => (/^\d{1,8}$/.test(v) ? "" : "The keypad password is 1 to 8 digits.") });
  // Stays a text area whatever it holds: the mockup's shrank to one line once it had text.
  const reason = field({ label: "Why a password instead of a fingerprint?", rows: 3,
    help: "Kept with the student's record. Nobody is asked why again.",
    validate: (v) => (v.trim() ? "" : "Record why this student needs a password instead of a fingerprint.") });
  const save = button({ label: "Save and send to the device", primary: true, busyLabel: "Sending" });
  const failure = h("div");

  const box = dialog({
    title: `A keypad password for ${fullName(student)}`,
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        "They type this at the terminal instead of scanning. Nothing is captured, and no fingerprint "
        + "is recorded for this student."),
      password, reason, failure),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });

  save.addEventListener("click", async () => {
    if (invalid(password, reason)) return;
    setBusy(save, true);
    fill(failure);
    try {
      await api.post(`/api/people/${student.id}/fallback-password`, {
        password: password.value(), reason: reason.value().trim() });
      box.close();
      toast("The password is saved and the device has it.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      // The password is only recorded once the device has it, so a failure says nothing was saved.
      // In a panel, not on the password field: the digits were checked before sending, and a terminal
      // that did not answer read as a wrong password (audit, 2026-09-24).
      fill(failure, panel({ tone: "failure", title: "Nothing was saved", role: "alert",
        body: error instanceof ApiError ? [error.message, error.hint].filter(Boolean).join(" ")
          : "That did not save." }));
    }
  });
  return box;
}
