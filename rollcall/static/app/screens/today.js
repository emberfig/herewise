// Screen 4: Today. Mockups: Today.png, TodayEmpty.png, TodayLoading.png, TodayError.png,
// TodayNoPermission.png, TodayCourserepview.png. Fix list: docs/DESIGN-DEVIATIONS.md, "4 Today".
// Contract: GET /api/today (rollcall/today.py), one shape, so nothing here works out a count.
//
// Kept from the mockup: the helper line under the table, skeleton rows with the header row real,
// and the error state's glyph, heading, remedy and Try again.
//
// Fixed from the mockup: the signed-in person is whoever is signed in, and a gated control names
// the permission rather than a job title; the search field fits its own placeholder (app.css); the
// loading button takes --hw-accent-hover, which setBusy does for every button in the app.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import { ago, announce, button, clear, dayAndMonth, emptyState, errorState, fill, h,
  loadingTable, page, pill, plural, section, setBusy, table, toast, withProgress }
  from "../ui.js";

const CLASS_STATE = {
  complete: { tone: "present", glyph: "✓", word: "Complete" },
  running: { tone: "accent", glyph: "◔", word: "Running now" },
  taking: { tone: "accent", glyph: "◔", word: "Taking attendance" },
  upcoming: { tone: "neutral", glyph: "○", word: "Upcoming" },
  no_scans: { tone: "review", glyph: "?", word: "No scans" },
  cancelled: { tone: "neutral", glyph: "✕", word: "Cancelled" },
};

export default {
  id: "today",
  title: "Today",
  permission: "register.read",
  // Today lists the unassigned classes, the waiting requests and the reminders under "Needs
  // attention", so the same sentences in a banner above them would be read twice.
  suppressBanners: ["unassigned", "reminders"],

  async render(view, { shell }) {
    const host = h("div");
    view.append(host);
    fill(host, page({
      title: "Today",
      subtitle: dayAndMonth(new Date().toISOString().slice(0, 10)),
      children: [section("Today's classes", loadingTable(["Course", "Time", "Present", "Status"]))],
    }));

    let data;
    try {
      data = await api.get("/api/today");
    } catch (error) {
      if (error instanceof ApiError && error.signedOut) throw error;
      fill(host, page({
        title: "Today",
        subtitle: dayAndMonth(new Date().toISOString().slice(0, 10)),
        children: [errorState({
          heading: "Today did not load.",
          body: error instanceof ApiError ? error.message : undefined,
          onRetry: () => this.render(view, { shell }),
        })],
      }));
      return;
    }

    draw(host, data, view, shell, this);
  },
};

function draw(host, data, view, shell, screen) {
  const pullNote = h("p", { class: "hw-reason", style: { textAlign: "end" } },
    data.last_pull
      ? `Last pulled ${ago(data.last_pull.at)}, ${plural(data.last_pull.new_count, "scan")}.`
      : "Never pulled. Pull to get started.");

  const pull = button({
    label: "Get attendance",
    primary: true,
    permission: "register.pull",
    glyph: "↓",
    busyLabel: "Getting attendance",
    align: "end",
    onClick: () => getAttendance(pull, host, view, shell, screen),
  });

  // Where the bar goes while attendance is being read. Empty until then, so the screen is not
  // carrying a placeholder for something that is not happening.
  const working = h("div");

  fill(host, page({
    title: "Today",
    subtitle: dayAndMonth(data.date),
    actions: [pull, session.can("register.pull") ? pullNote : null],
    children: [working, attention(data), classes(data)],
  }));
  host.__working = working;
}

// -- needs attention ---------------------------------------------------------------------------

function attention(data) {
  const cards = [];
  const w = data.waiting;

  if (w.unassigned_classes) {
    cards.push(card({
      title: plural(w.unassigned_classes, "unassigned class", "unassigned classes"),
      body: "Two courses share students, so these could not be matched automatically.",
      action: "Assign classes",
      path: "unassigned",
      permission: "class.manage",
    }));
  }
  if (w.correction_requests) {
    cards.push(card({
      title: plural(w.correction_requests, "correction request"),
      body: "Raised by someone whose role cannot apply a correction, waiting for a decision.",
      action: "Review",
      path: "corrections",
      permission: "register.approve",
    }));
  }
  for (const reminder of session.reminders) {
    cards.push(card({
      title: reminder.title,
      body: reminder.message,
      action: "Choose someone",
      path: "device/admins",
      permission: "device.manage",
    }));
  }
  if (!cards.length) return null;
  return section("Needs attention", h("div", { class: "hw-grid" }, ...cards));
}

function card({ title, body, action, path, permission }) {
  const link = session.can(permission)
    ? h("a", { class: "hw-link", href: href(path) }, action)
    : h("p", { class: "hw-reason" }, session.denial(permission));
  return h("article", { class: "hw-card" },
    h("h3", { class: "hw-card__title" }, title),
    h("p", { class: "hw-card__body" }, body),
    h("p", { class: "hw-card__foot" }, link));
}

// -- today's classes ---------------------------------------------------------------------------

function classes(data) {
  if (!data.classes.length) {
    // "Nothing today" and "never pulled" are different states, and the empty state says which.
    const never = !data.last_pull;
    return section("Today's classes", h("div", { class: "hw-table-frame" }, emptyState({
      icon: "☰",
      heading: never ? "Nothing has been read from the device yet" : "No classes today",
      body: never
        ? "Classes appear here after you get attendance from the device. Herewise works out each class from the scans."
        : "Nothing was timetabled and nothing has been detected for today. Classes appear here as soon as scans come in.",
      // Not a second accent button: one accent-coloured primary action per view
      // (docs/DESIGN-BRIEF.md), and Get attendance is already in the header.
      action: never && session.can("register.pull")
        ? button({ label: "Get attendance", onClick: () =>
            document.querySelector('[data-action="Get attendance"]')?.click() })
        : null,
    })));
  }

  return section("Today's classes",
    table({
      caption: "Classes today",
      columns: [
        { label: "Course", render: (c) => c.course_code
          ? h("span", {}, h("b", { class: "hw-table__code" }, c.course_code),
            // A class for one group of a course split into groups names it.
            c.group ? h("span", { class: "hw-tag" }, c.group) : null, " ",
            h("span", { class: "hw-muted" }, c.course_title || ""))
          : h("span", { class: "hw-muted" }, "Not on a course yet") },
        { label: "Time", render: (c) => c.state === "taking" ? `from ${c.start_time}`
          : `${c.start_time} to ${c.end_time}` },
        { label: "Present", align: "end", render: (c) => c.state === "upcoming"
          ? h("span", { class: "hw-muted" }, "not yet")
          : h("span", { class: "hw-ids" }, `${c.present} of ${c.registered}`) },
        { label: "Status", align: "end", render: (c) => {
          const spec = CLASS_STATE[c.state] || CLASS_STATE.upcoming;
          return pill(c.state, spec);
        } },
      ],
      rows: data.classes,
      rowHref: (c) => href(`classes/${c.session_id}`),
    }),
    h("p", { class: "hw-section__help" },
      "Select a row to open the class register. Figures update after each pull."));
}

// -- getting attendance ------------------------------------------------------------------------

async function getAttendance(control, host, view, shell, screen) {
  setBusy(control, true);
  const working = host.__working || h("div");
  try {
    const devices = await api.get("/api/devices");
    const device = devices.find((d) => d.is_default) || devices[0];
    if (!device) throw new ApiError(400, { error: "No device is set up. Add one from Device." });
    // How long a pull takes is the terminal's decision, and the count is not known until it has
    // been read, so the bar has no total until the scans arrive and then it has a real one.
    const result = await withProgress(working,
      api.post(`/api/devices/${device.id}/pull`, {}),
      { whileWaiting: "Reading the scans on the terminal",
        done: (answer) => `${plural(answer.new_count, "new scan")} read.` });
    shell.setDevice("connected");
    sessionStorage.setItem("hw-pull-result", JSON.stringify(result));
    announce(`${plural(result.new_count, "new scan")} read from the device.`);
    location.hash = href("pull");
  } catch (error) {
    setBusy(control, false);
    fill(working);
    const message = error instanceof ApiError ? error.message : "The device did not answer.";
    shell.setDevice(error instanceof ApiError && error.code === "wrong_device" ? "wrong" : "unreachable");
    toast(message, "failure");
    announce(message);
  }
}
