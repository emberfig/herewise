// Screen 6: Unassigned classes. Mockups: Unassignedclasses.png, UnassignedAmbiguous.png,
// UnassignedNothingwaiting.png. Fix list: docs/DESIGN-DEVIATIONS.md, "6 Unassigned classes".
//
// Kept from the mockup: the course chooser's evidence column, "201 of 204 (98%)", which is the most
// readable thing on the card and the reason this screen can be trusted.
//
// Fixed from the mockup:
//   the count in the subtitle is the length of the list it describes, so an empty screen can never
//     say three classes are waiting (the standing rule: displayed state is derived, never written);
//   a card that warns it may not have been a class offers the discard the warning implies;
//   the evidence figures are on every card, not only some;
//   one time separator across the app: "15:02 to 16:47".

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import { invalid, announce, button, clear, dialog, emptyState, field, fill, h, loadingCards, longDate, page, plural, setBusy, toast } from "../ui.js";

export default {
  id: "unassigned",
  nav: "today",
  title: "Unassigned classes",
  permission: "register.read",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Unassigned classes", children: [loadingCards(2)] }));
    const reload = () => this.render(clear(view), ctx);
    const rows = await api.get("/api/sessions/unassigned");
    draw(host, rows, reload);
  },
};

function draw(host, rows, reload) {
  fill(host, page({
    title: "Unassigned classes",
    // Derived from the list itself, never written.
    subtitle: rows.length
      ? `${plural(rows.length, "class", "classes")} could not be matched to a course`
      : "",
    children: rows.length
      ? [h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-6)" } },
          "Herewise works out a class from a burst of scans, but when two courses share the same "
          + "students it cannot tell which one they were in. Choose the course, and the register, "
          + "the sheet and the percentages all follow."),
        h("div", { class: "hw-stack" },
          ...rows.map((row) => card(row, reload)))]
      : [h("div", { class: "hw-table-frame" }, emptyState({
          icon: "✓",
          heading: "Nothing waiting",
          body: "Every class found on this device is on a course.",
          action: button({ label: "Go to Today", href: href("today") }),
        }))],
  }));
}

function card(row, reload) {
  const candidates = row.candidates || [];
  const thin = row.students !== undefined && row.students !== null && row.students < 50;
  const chosen = { id: candidates[0]?.course_id ?? null };

  const list = h("div", { class: "hw-chooser", role: "radiogroup", "aria-label": "Which course was this?" });
  for (const course of candidates) {
    const input = h("input", { type: "radio", name: `course-${row.id}`, value: course.course_id,
      checked: course.course_id === chosen.id || null });
    input.addEventListener("change", () => { chosen.id = course.course_id; assign.disabled = false; });
    list.append(h("label", { class: "hw-choice hw-chooser__row" }, input,
      h("span", { class: "hw-chooser__name" },
        h("b", {}, course.code),
        // On a course split into groups, the group its scans point at: the class goes to that group,
        // said before it is chosen rather than after.
        course.group ? h("span", { class: "hw-tag" }, course.group) : null, " ",
        h("span", { class: "hw-muted" }, course.title || "")),
      // The evidence column: how many of the people who actually scanned are on this course.
      h("span", { class: "hw-chooser__evidence hw-ids" },
        `${course.scanners_on_it} of ${course.students}`,
        h("span", { class: "hw-muted" }, ` (${course.percent}%)`))));
  }

  const assign = h("button", { class: "hw-button hw-button--primary", type: "button",
    dataset: { action: "assign" } }, "Assign");
  const control = session.can("class.manage")
    ? h("span", { class: "hw-control hw-control--end" }, assign)
    : h("span", { class: "hw-control hw-control--end" },
      h("button", { class: "hw-button hw-button--primary", type: "button", disabled: true,
        dataset: { action: "assign" } }, "Assign"),
      h("p", { class: "hw-reason" }, session.denial("class.manage")));
  if (!candidates.length) {
    assign.disabled = true;
  }
  assign.addEventListener("click", async () => {
    if (!chosen.id) return;
    setBusy(assign, true);
    try {
      await api.post(`/api/sessions/${row.id}/course`, { course_id: chosen.id });
      toast("The class is on that course, and its register is ready.");
      await reload();
    } catch (error) {
      setBusy(assign, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });

  const discard = session.can("class.manage")
    ? h("button", { class: "hw-button hw-button--quiet", type: "button",
        dataset: { action: "discard" } }, "Not a class, discard it")
    : null;
  discard?.addEventListener("click", () => askToDiscard(row, reload));

  return h("article", { class: "hw-card hw-stack" },
    h("div", { class: "hw-row hw-row--between" },
      h("div", {},
        h("h3", { style: { margin: 0, fontSize: "var(--hw-text-lead)" } }, longDate(row.date)),
        h("p", { class: "hw-muted hw-ids", style: { margin: "var(--hw-space-1) 0 0" } },
          `${row.start_time} to ${row.end_time} · ${row.level_name}`
          + (row.students ? ` · ${plural(row.students, "student")} scanned` : ""))),
      h("a", { class: "hw-link", href: href(`classes/${row.id}`) }, "See the scans")),
    // The warning implies the discard, so the card that carries it carries the action too.
    thin ? h("div", { class: "hw-panel", dataset: { tone: "review" } },
      h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "?"),
      h("p", { class: "hw-panel__body" },
        `Only ${plural(row.students, "person", "people")} scanned. This may have been a test rather `
        + "than a class.")) : null,
    candidates.length
      ? list
      : h("p", { class: "hw-muted", style: { margin: 0 } },
        `No course exists for ${row.level_name} this session, so there is nothing to put it on yet.`),
    h("div", { class: "hw-row hw-row--between" }, discard, control));
}

function askToDiscard(row, reload) {
  const note = field({ label: "Why is this not a class?", name: "note", rows: 3,
    help: "Kept with the record. The scans themselves are never deleted.",
    validate: (v) => (v.trim() ? "" : "Say why this was not a class.") });
  const save = button({ label: "Discard it", variant: "destructive", busyLabel: "Discarding" });
  const box = dialog({
    title: "This was not a class",
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        `Discarding marks ${longDate(row.date)}, ${row.start_time} to ${row.end_time}, as cancelled, `
        + "so it counts towards nothing. The scans behind it are kept, and it can be restored."),
      note),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(note)) return;
    setBusy(save, true);
    try {
      await api.post(`/api/sessions/${row.id}/cancel`, { note: note.value().trim() });
      box.close();
      announce("The class is discarded.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      note.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}
