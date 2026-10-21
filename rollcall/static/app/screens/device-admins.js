// Screen 29: Super Admins, and screen 3, the reminder that brings people here.
// Mockups: SuperAdmins.png, SuperAdminsdone.png, SuperAdminsstudentchosen.png,
// SuperAdminsterminalnotanswering.png, TodaySetaSuperAdmin.png, TodayChooseasecondSuperAdmin.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "29 Super Admins" and "3 Super Admin reminder".
//
// Kept from the mockup: every disabled control carries its own reason, and the reason differs by
// cause ("Enter a keypad password first.", "Tick the box to confirm.", "Needs the device.").
//
// Fixed from the mockup:
//   a filled seat carries a tick, not a coloured dot, which is the only thing marking it as held;
//   a person's details are written once, under the name, not twice;
//   removing the last Super Admin states the consequence and asks to confirm before anything is
//     sent, because it opens the menu to anyone at the keypad;
//   the seats sit side by side here and on screen 31, one component, one layout;
//   someone saved as Super Admin but not yet on the terminal fills no seat: they sit beneath with a
//     hollow circle, "Saved, not yet on the device", and their own Send action.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  invalid, announce, button, dialog, field, fill, h, loadingCards, page, plural, section, setBusy, toast,
} from "../ui.js";

export default {
  id: "device-admins",
  nav: "device",
  title: "Super Admins",
  permission: "device.manage",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Super Admins", children: [loadingCards(2)] }));
    const reload = () => this.render(fill(view), ctx);

    const devices = await api.get("/api/devices");
    const device = devices.find((d) => d.is_default) || devices[0];
    const [candidates, live] = await Promise.all([
      api.get(`/api/devices/${device.id}/admin-candidates`),
      api.get(`/api/devices/${device.id}/status`).then(() => true).catch(() => false),
    ]);
    ctx.shell.setDevice(live ? "connected" : "unreachable");
    draw(host, device, candidates, live, reload);
  },
};

function draw(host, device, data, live, reload) {
  const admins = data.people.filter((p) => p.is_super_admin);
  const waiting = data.people.filter((p) => p.awaiting_push);
  const why = live ? "" : "Needs the device. A Super Admin only counts once the terminal has them.";

  fill(host, page({
    title: "Super Admins",
    subtitle: `Who can open the menu on ${device.name}`,
    children: [
      h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-6)" } },
        "Until someone is Super Admin, anyone at the keypad can open the device menu and delete every "
        + "user and every scan. Two people, so one absence or one cut finger cannot lock you out. "
        + "Every Super Admin needs a keypad password, because a finger alone is not enough at the menu."),
      section("The two seats", seats(admins, device, live, why, reload)),
      waiting.length ? section("Saved here, not yet on the device",
        h("div", { class: "hw-stack" }, ...waiting.map((p) => awaitingRow(p, device, live, why, reload))))
        : null,
      section("Choose someone", chooser(data, device, live, why, reload)),
    ],
  }));
}

function seats(admins, device, live, why, reload) {
  const cells = [0, 1].map((index) => {
    const person = admins[index];
    if (!person) {
      return h("div", { class: "hw-seat", dataset: { state: "empty" } },
        h("p", { class: "hw-seat__mark", "aria-hidden": "true" }, "○"),
        h("p", { class: "hw-seat__name" }, "None set"),
        h("p", { class: "hw-muted", style: { margin: 0 } },
          index === 0 ? "Anyone at the keypad can open the menu."
            : "One absence would lock the menu."));
    }
    return h("div", { class: "hw-seat", dataset: { state: "filled" } },
      h("p", { class: "hw-seat__mark", "aria-hidden": "true" }, "✓"),
      h("p", { class: "hw-seat__name" }, `${person.surname} ${person.other_names}`.trim()),
      // Once, under the name. The mockup wrote every detail twice.
      h("p", { class: "hw-muted", style: { margin: 0 } },
        `ID ${person.device_user_id} · ${plural(person.fingers, "finger")} · `
        + `${person.has_password ? "keypad password set" : "keypad password not set"}`),
      h("p", { class: "hw-card__foot" },
        button({ label: "Remove", variant: "destructive", reason: why,
          onClick: () => askToRemove(person, admins.length, device, reload) })));
  });
  return h("div", { class: "hw-seats" }, ...cells);
}

function awaitingRow(person, device, live, why, reload) {
  const send = button({ label: "Send to the device", primary: true, reason: why, busyLabel: "Sending",
    onClick: async () => {
      setBusy(send, true);
      try {
        await api.post(`/api/devices/${device.id}/push`, { person_ids: [person.id] });
        toast(`${person.surname} is on the device and counts now.`);
        await reload();
      } catch (error) {
        setBusy(send, false);
        toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
      }
    } });
  return h("div", { class: "hw-card hw-row hw-row--between" },
    h("div", { class: "hw-row", style: { gap: "var(--hw-space-3)" } },
      h("span", { "aria-hidden": "true", style: { color: "var(--hw-rule-strong)" } }, "○"),
      h("div", {},
        h("p", { style: { margin: 0, fontWeight: "var(--hw-weight-emphasis)" } },
          `${person.surname} ${person.other_names}`.trim()),
        h("p", { class: "hw-muted", style: { margin: 0 } },
          `ID ${person.device_user_id} · Saved, not yet on ${device.name}. `
          + "They fill no seat and count towards nothing until the device has them."))),
    send);
}

function chooser(data, device, live, why, reload) {
  const staff = data.people.filter((p) => p.role === "staff" && !p.is_super_admin);
  const students = data.people.filter((p) => p.role === "student" && !p.is_super_admin);
  const state = { personId: staff[0]?.id ?? students[0]?.id ?? null, confirmed: false };

  const password = field({ label: "Keypad password", type: "password", name: "device_password",
    inputmode: "numeric",
    help: "1 to 8 digits, typed at the device's own keypad. Every Super Admin needs one.",
    validate: (v) => (/^\d{1,8}$/.test(v) ? "" : "The keypad password is 1 to 8 digits."),
    onInput: () => update() });

  const confirm = h("input", { type: "checkbox" });
  const warning = h("div", { hidden: true });
  confirm.addEventListener("change", () => { state.confirmed = confirm.checked; update(); });

  const list = h("div", { class: "hw-stack hw-stack--tight", role: "radiogroup",
    "aria-label": "Who should be Super Admin" });
  const row = (person) => {
    const input = h("input", { type: "radio", name: "admin-candidate", value: person.id,
      checked: person.id === state.personId || null });
    input.addEventListener("change", () => { state.personId = person.id; update(); });
    return h("label", { class: "hw-choice" }, input,
      h("span", {},
        h("span", { class: "hw-choice__label" }, `${person.surname} ${person.other_names}`.trim()),
        h("span", { class: "hw-choice__help" },
          ` ID ${person.device_user_id}`
          + (person.matric_no ? ` · ${person.matric_no}` : "")
          + ` · ${plural(person.fingers, "finger")}`
          + (person.on_device ? "" : " · not on the device yet"))));
  };

  // Every person on the device is a candidate, so a department of 258 made this screen 15,910px of
  // radio buttons and nobody was going to scroll it (measured 2026-09-22). Staff first, because a
  // Super Admin is usually staff, then the shortest list that answers the question: search for the
  // person you already have in mind, and the rest is one press away.
  const ordered = [...staff, ...students];
  const search = h("input", { class: "hw-input", type: "search",
    placeholder: "Find the person by name, matric number or device ID", autocomplete: "off",
    "aria-label": "Find the person by name, matric number or device ID" });
  const shown = h("p", { class: "hw-muted", role: "status", style: { margin: 0 } });
  const SHOW = 12;
  let showAll = false;

  function paint() {
    const q = search.value.trim().toLowerCase();
    const found = q
      ? ordered.filter((person) => `${person.surname} ${person.other_names} ${person.matric_no || ""}`
        .concat(` ${person.device_user_id}`).toLowerCase().includes(q))
      : ordered;
    const visible = showAll || found.length <= SHOW ? found : found.slice(0, SHOW);
    fill(list, ...visible.map(row));
    if (!found.length) {
      list.append(h("p", { class: "hw-muted" },
        `Nobody on the device matches "${search.value.trim()}".`));
    }
    if (visible.length < found.length) {
      const more = button({ label: `Show the other ${plural(found.length - visible.length, "person", "people")}` });
      more.addEventListener("click", () => { showAll = true; paint(); });
      list.append(more);
    }
    shown.textContent = found.length === ordered.length
      ? `${plural(ordered.length, "person", "people")} on the device`
      : `${plural(found.length, "match", "matches")} of ${ordered.length}`;
  }
  search.addEventListener("input", () => { showAll = false; paint(); });
  paint();

  const save = button({ label: "Make Super Admin", primary: true, busyLabel: "Sending" });
  const saveButton = save.matches("button") ? save : save.querySelector("button");
  const reason = h("p", { class: "hw-reason" });

  function chosen() {
    return data.people.find((p) => p.id === state.personId) || null;
  }

  function update() {
    const person = chosen();
    const isStudent = person && person.role === "student";
    warning.hidden = !isStudent;
    fill(warning, isStudent
      ? h("div", { class: "hw-panel", dataset: { tone: "review" } },
        h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "?"),
        h("div", {},
          h("p", { class: "hw-panel__title" }, "This person is a student"),
          h("p", { class: "hw-panel__body" }, person.warning),
          h("label", { class: "hw-choice", style: { marginBlockStart: "var(--hw-space-3)" } },
            confirm, h("span", { class: "hw-choice__label" },
              "I understand, and I still want them to be Super Admin"))))
      : null);

    let stop = why;
    if (!stop && !person) stop = "Choose someone first.";
    else if (!stop && !/^\d{1,8}$/.test(password.value())) stop = "Enter a keypad password first.";
    else if (!stop && isStudent && !state.confirmed) stop = "Tick the box to confirm.";
    saveButton.disabled = Boolean(stop);
    reason.textContent = stop;
    reason.hidden = !stop;
  }

  saveButton.addEventListener("click", async () => {
    const person = chosen();
    if (!person || invalid(password)) return;
    setBusy(save, true);
    try {
      const result = await api.post(`/api/people/${person.id}/device-role`, {
        super_admin: true, password: password.value(),
        confirm_student: person.role === "student" });
      toast(`${person.surname} can open the device menu now.`);
      announce(result.warning || "Super Admin set.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });

  const card = h("div", { class: "hw-card hw-stack" },
    h("div", { class: "hw-row hw-row--between", style: { marginBlockEnd: "var(--hw-space-3)" } },
      h("div", { style: { flex: "1 1 22rem", maxWidth: "26rem" } }, search), shown),
    list, warning, password,
    h("div", { class: "hw-cardfoot" },
      h("span", { class: "hw-cardfoot__end hw-control hw-control--end" }, save, reason)));
  update();
  return card;
}

// Removing the last Super Admin opens the menu to anyone at the keypad, so it is guarded.
function askToRemove(person, count, device, reload) {
  const last = count <= 1;
  const go = button({ label: "Remove them", variant: "destructive", busyLabel: "Sending" });
  const box = dialog({
    title: `Remove ${`${person.surname} ${person.other_names}`.trim()}?`,
    body: h("div", { class: "hw-stack" },
      last
        ? h("div", { class: "hw-panel", dataset: { tone: "failure" } },
          h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "✕"),
          h("div", {},
            h("p", { class: "hw-panel__title" }, "This is the only Super Admin"),
            h("p", { class: "hw-panel__body" },
              `Once they are removed, anyone standing at ${device.name} can open its menu and delete `
              + "every user and every scan on it. Choose a replacement first if you can.")))
        : h("p", { style: { margin: 0 } },
          "They become an ordinary user on the device and can no longer open its menu. Their "
          + "fingerprints and their attendance are untouched."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "Their keypad password is kept, so making them Super Admin again does not need a new one.")),
    actions: [button({ label: "Keep them", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      const result = await api.post(`/api/people/${person.id}/device-role`, { super_admin: false });
      box.close();
      toast(result.warning || "They are an ordinary user on the device now.",
        result.super_admins_on_device ? "success" : "failure");
      await reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}

/** Screen 3: the reminder, opened from Today or from the banner. */
export function reminderDialog(reminder, { onDone } = {}) {
  const later = button({ label: "Remind me later", busyLabel: "Saving",
    onClick: async () => { await act(`/api/reminders/${encodeURIComponent(reminder.key)}/remind-later`); } });
  const choose = button({ label: "Choose someone", primary: true,
    href: href("device/admins"), onClick: () => box.close() });
  const cancel = reminder.can_cancel
    ? button({ label: "Cancel this reminder", variant: "quiet",
        onClick: async () => { await act(`/api/reminders/${encodeURIComponent(reminder.key)}/cancel`); } })
    : button({ label: "Cancel this reminder", variant: "quiet",
        // The backend's own refusal, word for word.
        reason: "You cannot cancel this one while the device has no Super Admin." });

  const box = dialog({
    title: reminder.title,
    body: h("div", { class: "hw-stack" }, h("p", { style: { margin: 0 } }, reminder.message)),
    actions: [later, h("span", { class: "hw-cardfoot__end" }, choose)],
    // The cancel link and its line go on their own row beneath the buttons, full width: in the
    // mockup they were squeezed into a column beside the buttons and wrapped onto seven lines.
    aside: h("div", { class: "hw-dialog__aside" }, cancel),
  });

  async function act(path) {
    try {
      await api.post(path, {});
      box.close();
      onDone?.();
    } catch (error) {
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  }
  return box;
}
