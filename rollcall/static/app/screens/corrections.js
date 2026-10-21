// Screen 41: Correction requests. Mockups: Correctionrequests.png, Onlyyourown.png,
// Nothingwaiting.png, Classsincecancelled.png, Newscansarrived.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "41 Correction requests".
//
// Kept from the mockup: the change line, a cross pill and a tick pill either side of an arrow on a
// sunken panel, which reads as the decision being made without reading the prose around it; and
// "Asked by Chidi Umeh, Course rep", which names a real role someone holds. That is data an
// approver needs, not the instructional copy the no-job-title rule is about.
//
// Fixed from the mockup: the tabs own the region beneath them, so "Recently decided" is its own
// section under its own heading rather than a card inside the Waiting tab; and when Approve is
// disabled on a cancelled class, its rationale line goes with it instead of sitting beside a line
// that is no longer true.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import { invalid, matricText, announce, button, clear, dateAndTime, dialog, emptyState, field, fill, h, loadingCards, longDate, page, pill, section, setBusy, STATUS, toast } from "../ui.js";

export default {
  id: "corrections",
  nav: "today",
  title: "Correction requests",
  permission: "register.request",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Correction requests", children: [loadingCards(2)] }));
    const reload = () => this.render(clear(view), ctx);
    const rows = await api.get("/api/correction-requests");
    draw(host, rows, reload);
  },
};

function draw(host, rows, reload) {
  const waiting = rows.filter((r) => r.state === "pending");
  const decided = rows.filter((r) => r.state !== "pending");
  const approver = session.can("register.approve");

  fill(host, page({
    title: "Correction requests",
    subtitle: approver
      ? "Every request raised, and what happened to it"
      : "The requests you have raised, and what happened to them",
    children: [
      approver ? null : h("div", { class: "hw-panel", dataset: { tone: "info" },
        style: { marginBlockEnd: "var(--hw-space-6)" } },
        h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "i"),
        h("p", { class: "hw-panel__body" },
          `${session.denial("register.approve")} You see your own requests here and what was decided.`)),
      section(`Waiting${waiting.length ? ` (${waiting.length})` : ""}`,
        waiting.length
          ? h("div", { class: "hw-stack" }, ...waiting.map((r) => card(r, reload, approver)))
          : h("div", { class: "hw-table-frame" }, emptyState({
              icon: "✓",
              heading: "Nothing waiting",
              body: approver
                ? "No one has asked for a correction. Requests appear here the moment they are raised."
                : "You have not asked for any corrections. Open a class register and choose a student "
                  + "to ask for one.",
              action: button({ label: "Go to Today", href: href("today") }),
            }))),
      // Its own section beneath the tabs, not a card inside the Waiting one.
      decided.length
        ? section(`Recently decided (${decided.length})`,
          h("div", { class: "hw-stack" }, ...decided.slice(0, 10).map((r) => card(r, reload, approver))))
        : null,
    ],
  }));
}

function card(request, reload, approver) {
  const cancelled = Boolean(request.cancelled_at);
  const mine = request.requested_by === session.account?.id;
  const decided = request.state !== "pending";
  const self = session.isSelf(request.person_id);

  // Nobody decides their own request. Enforced in the backend too, and separate from the permission.
  let why = "";
  if (decided) why = "";
  else if (mine) why = "You raised this request, so you cannot decide it. Someone else has to.";
  else if (!approver) why = session.denial("register.approve");

  const approve = button({ label: "Approve", primary: true, busyLabel: "Approving",
    reason: why || (cancelled ? "This class has been cancelled, so a correction would count towards nothing." : ""),
    onClick: () => decide(request, true, reload) });
  const reject = button({ label: "Reject", busyLabel: "Rejecting",
    reason: why, onClick: () => decide(request, false, reload) });

  return h("article", { class: "hw-card hw-stack", dataset: decided ? { dimmed: "true" } : null },
    h("div", { class: "hw-row hw-row--between" },
      h("div", {},
        h("h3", { style: { margin: 0, fontSize: "var(--hw-text-lead)" } },
          `${request.surname} ${request.other_names}`.trim()),
        h("p", { class: "hw-muted hw-ids", style: { margin: "var(--hw-space-1) 0 0" } },
          `${matricText(request.matric_no)} · ${request.course_code || "No course"} · `
          + `${longDate(request.date)}, ${request.start_time} to ${request.end_time}`)),
      h("a", { class: "hw-link", href: href(`classes/${request.class_session_id}`) }, "Open the register")),

    // The change, read at a glance: what it is now, an arrow, what it would become. Once a request
    // is decided the arrow would point from a box its own approval changed, which says nothing, so
    // a decided card states what was asked for instead.
    changeLine(request, decided),

    h("p", { style: { margin: 0 } },
      h("span", { class: "hw-muted" }, "Asked by "),
      `${request.requested_by_name}`,
      request.requested_by_role ? h("span", { class: "hw-muted" }, `, ${request.requested_by_role}`) : null,
      h("span", { class: "hw-muted" }, ` · ${dateAndTime(request.requested_at)}`)),
    h("p", { class: "hw-well", style: { margin: 0 } }, request.note),

    cancelled && !decided ? h("div", { class: "hw-panel", dataset: { tone: "failure" } },
      h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "⚠"),
      h("p", { class: "hw-panel__body" },
        "This class has been cancelled since the request was raised, so it counts towards nothing. "
        + "Reject it, or restore the class first.")) : null,

    decided
      ? h("p", { style: { margin: 0 } },
        pill(request.state === "approved" ? "present" : "absent",
          { word: request.state === "approved" ? "Approved" : "Rejected",
            glyph: request.state === "approved" ? "✓" : "✕" }),
        h("span", { class: "hw-muted" },
          ` by ${request.decided_by_name || "someone"} · ${dateAndTime(request.decided_at)}`),
        request.decision_note
          ? h("span", { class: "hw-drawer__note" }, request.decision_note) : null)
      : h("div", { class: "hw-row" }, approve, reject,
        // The rationale sits with the action it belongs to, and only while that action is live.
        why || cancelled ? null : h("p", { class: "hw-reason" },
          "Approving records the correction under your name, not the name of whoever asked.")));
}

function changeLine(request, decided) {
  const asked = STATUS[request.status] || STATUS.present;
  if (decided) {
    return h("div", { class: "hw-change" },
      h("span", { class: "hw-muted" }, "Asked for"), pill(request.status));
  }
  const now = STATUS[request.current_status] || STATUS.absent;
  return h("div", { class: "hw-change" },
    pill(request.current_status || "absent"),
    h("span", { class: "hw-change__arrow", "aria-hidden": "true" }, "→"),
    pill(request.status),
    h("span", { class: "hw-visually-hidden" },
      `Change from ${now.word.toLowerCase()} to ${asked.word.toLowerCase()}.`));
}

function decide(request, approve, reload) {
  const note = field({ label: approve ? "Anything to add?" : "Why are you rejecting it?", rows: 3,
    help: approve ? "Optional. Kept with the decision." : "Kept with the decision and shown to whoever asked.",
    validate: approve ? null : (v) => (v.trim() ? "" : "Say why the request is rejected.") });
  const save = button({ label: approve ? "Approve the correction" : "Reject the request",
    primary: approve, variant: approve ? "" : "destructive",
    busyLabel: approve ? "Approving" : "Rejecting" });
  const box = dialog({
    title: approve ? "Approve this correction" : "Reject this request",
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } }, approve
        ? `${request.surname} ${request.other_names}`.trim()
          + ` will be marked ${request.status}, signed with your name.`
        : "Nothing on the register changes. Whoever asked can see the reason."),
      note),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(note)) return;
    setBusy(save, true);
    try {
      await api.post(`/api/correction-requests/${request.id}/decide`,
        { approve, note: note.value().trim() });
      box.close();
      toast(approve ? "The correction is recorded under your name." : "The request is rejected.");
      announce(approve ? "Approved." : "Rejected.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      note.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}
