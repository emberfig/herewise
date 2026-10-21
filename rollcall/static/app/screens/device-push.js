// Screen 30: Send to device. Mockups: Sendtodevicesending.png, Sendtodevicefinished.png,
// Sendtodevicenotenoughspace.png, Sendtodevicecablepulled.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "30 Send to device".
//
// The rule this screen is the best example of: when the operation ends, nothing on the screen still
// describes the state before it. The chip returns to connected, the progress card becomes a result,
// the reassurance panel goes, and the subtitle gains what changed.
//
// Pushing 258 people takes 45 to 87 seconds on this K40 and blocks the request (known gap 13), so
// the waiting state says so plainly rather than pretending to be quick.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import {
  announce, button, fill, h, loadingCards, page, plural, section, setBusy, table, withProgress,
} from "../ui.js";

export default {
  id: "device-push",
  nav: "device",
  title: "Send to device",
  permission: "device.manage",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Send to the device", children: [loadingCards(2)] }));

    const devices = await api.get("/api/devices");
    const device = devices.find((d) => d.is_default) || devices[0];
    const [levels, courses, status] = await Promise.all([
      api.get("/api/levels"),
      api.get("/api/courses"),
      api.get(`/api/devices/${device.id}/status`).catch(() => null),
    ]);
    ctx.shell.setDevice(status ? "connected" : "unreachable");
    draw(host, device, levels, courses, status, ctx);
  },
};

function draw(host, device, levels, courses, status, ctx) {
  const state = { what: "level", levelId: levels.find((l) => l.students)?.id ?? levels[0]?.id, courseId: courses[0]?.id };
  const result = h("div");
  const live = Boolean(status);
  const why = live ? "" : "Needs the device. It is not answering at the moment.";

  const segments = h("div", { class: "hw-toggle", role: "group", "aria-label": "What to send" });
  for (const [value, label] of [["level", "A whole level"], ["course", "One course"]]) {
    const btn = h("button", { class: "hw-toggle__button", type: "button",
      dataset: { action: `send-${value}` }, "aria-pressed": String(state.what === value) }, label);
    btn.addEventListener("click", () => {
      state.what = value;
      for (const other of segments.children) other.setAttribute("aria-pressed", String(other === btn));
      paint();
    });
    segments.append(btn);
  }

  const pick = h("div");
  const consequence = h("p", { class: "hw-muted" });

  function chosenCount() {
    if (state.what === "level") {
      return levels.find((l) => l.id === Number(state.levelId))?.students ?? 0;
    }
    const course = courses.find((c) => c.id === Number(state.courseId));
    return course ? course.level_students + course.carry_over_students : 0;
  }

  function paint() {
    const select = h("select", { class: "hw-select", "aria-label": state.what === "level" ? "Level" : "Course" });
    const rows = state.what === "level"
      ? levels.map((l) => ({ value: l.id, label: `${l.name} · ${plural(l.students, "student")}` }))
      : courses.map((c) => ({ value: c.id,
          label: `${c.code}${c.title ? ` ${c.title}` : ""} · `
            + `${plural(c.level_students + c.carry_over_students, "student")}` }));
    for (const row of rows) {
      const option = h("option", { value: row.value }, row.label);
      if (String(row.value) === String(state.what === "level" ? state.levelId : state.courseId)) {
        option.selected = true;
      }
      select.append(option);
    }
    select.addEventListener("change", () => {
      if (state.what === "level") state.levelId = Number(select.value);
      else state.courseId = Number(select.value);
      paint();
    });
    fill(pick, h("div", { class: "hw-field" },
      h("label", { class: "hw-field__label" }, state.what === "level" ? "Level" : "Course"), select));

    const count = chosenCount();
    const room = status ? status.users.capacity - status.users.used : null;
    consequence.textContent = status
      ? `${plural(count, "person", "people")} will be written to ${device.name}. `
        + `It holds ${status.users.used.toLocaleString("en-GB")} of `
        + `${status.users.capacity.toLocaleString("en-GB")}, so there is room for `
        + `${room.toLocaleString("en-GB")} more.`
      : `${plural(count, "person", "people")} would be written to ${device.name}.`;
  }

  const send = button({ label: "Send", primary: true, reason: why, busyLabel: "Sending",
    onClick: async () => {
      setBusy(send, true);
      try {
        const body = state.what === "level"
          ? { level_id: Number(state.levelId) } : { course_id: Number(state.courseId) };
        // The bar counts people the terminal has actually taken, read from the backend's own
        // report: a level is about thirty seconds and a button saying "Sending" says nothing
        // about how much is left.
        const pushed = await withProgress(result,
          api.post(`/api/devices/${device.id}/push`, body),
          { whileWaiting: `Writing ${plural(chosenCount(), "person", "people")} to ${device.name}`,
            done: (answer) => `${plural(answer.pushed, "person", "people")} written to ${device.name}.` });
        // The sentence the old waiting panel carried, kept: it is the one that stops somebody
        // unplugging the cable half way through.
        ctx.shell.setDevice("connected");
        fill(result, finished(pushed, device));
        announce(`${plural(pushed.pushed, "person", "people")} written to the device.`);
      } catch (error) {
        ctx.shell.setDevice(error instanceof ApiError && error.code === "wrong_device" ? "wrong" : "unreachable");
        // Nothing on the screen still describes the sending state.
        fill(result, failed(error));
      } finally {
        setBusy(send, false);
      }
    } });

  fill(host, page({
    title: "Send to the device",
    subtitle: status
      ? `${device.name} holds ${status.users.used.toLocaleString("en-GB")} of `
        + `${status.users.capacity.toLocaleString("en-GB")} people`
      : `${device.name} is not answering`,
    actions: [send],
    children: [
      section("What to send", h("div", { class: "hw-card hw-stack" }, segments, pick, consequence)),
      result,
      h("p", { class: "hw-section__help" },
        "Sending writes each person's ID, name and privilege onto the terminal. It never deletes "
        + "anyone, and it never touches the scans already on it."),
    ],
  }));
  paint();
}

function finished(pushed, device) {
  const missing = pushed.without_fingers ?? null;
  return h("div", { class: "hw-stack" },
    h("div", { class: "hw-panel", dataset: { tone: "success" }, role: "status" },
      h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✓"),
      h("div", {},
        h("p", { class: "hw-panel__title" },
          `${plural(pushed.pushed, "person", "people")} written to ${device.name}`),
        h("p", { class: "hw-panel__body" },
          missing
            ? `${plural(missing, "of them has", "of them have")} no fingerprint yet, so they cannot `
              + "scan until they are enrolled."
            : "Everyone sent can scan now."))),
    missing && missing > 0
      ? h("p", {}, h("a", { class: "hw-link", href: href("enrolment") }, "Enrol the ones without fingerprints"))
      : null);
}

function failed(error) {
  const message = error instanceof ApiError ? error.message : "The device did not answer.";
  return h("div", { class: "hw-panel", dataset: { tone: "failure" }, role: "alert" },
    h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✕"),
    h("div", {},
      h("p", { class: "hw-panel__title" }, message),
      h("p", { class: "hw-panel__body" },
        (error instanceof ApiError && error.hint ? `${error.hint} ` : "")
        + "Nothing was changed here. Whoever was already on the device is still on it."),
      h("p", { style: { margin: "var(--hw-space-2) 0 0" } },
        h("a", { class: "hw-link", href: href("device/connection") }, "Run the connection check"))));
}
