// Reopening a class taken live, for the students who had not scanned. Asked for on 2026-10-22: a
// lecturer who ended attendance and then found people missed can open it again so they can scan.
//
// Shared by the two places a lecturer looks once a class is over: the "Attendance taken" page the
// End button leads to, and the class register. Backend: POST /api/live/{id}/reopen, and the
// register's `reopen` field, which is null for a class that cannot be reopened at all and otherwise
// carries the reason it cannot be reopened now (another day, another class open).

import { ApiError, api } from "../api.js";
import { button, clockTime, dialog, h, plural, setBusy, toast } from "../ui.js";

/** "09:00 to 10:00, reopened 10:40 to 11:05": every window a class counted scans in. */
export function windowsText(register) {
  const spans = register.windows || [];
  if (spans.length < 2) return null;
  return spans.map((w, i) => `${i ? "reopened " : ""}${clockTime(w.from)} to ${clockTime(w.to)}`).join(", ");
}

/** The button, or nothing for a class that can never be reopened. */
export function reopenButton(register, go) {
  if (!register.reopen) return null;
  return button({
    label: "Reopen attendance", permission: "register.correct", reason: register.reopen.reason || "",
    onClick: () => askToReopen(register, go),
  });
}

function askToReopen(register, go) {
  const s = register.session;
  const t = register.totals;
  const who = `${s.course_code || "this class"}${register.group ? ` ${register.group.name}` : ""}`;
  const go_ = button({ label: "Reopen attendance", primary: true, busyLabel: "Reopening" });
  const box = dialog({
    title: `Reopen attendance for ${who}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" },
      h("p", { style: { margin: 0 } },
        `${t.present} present, ${t.absent} absent. `
        + (t.absent ? `The ${plural(t.absent, "student")} without a scan can scan now. ` : "")
        + "Everyone present stays present, and corrections and excused absences stay as they are."),
      h("p", { style: { margin: 0 } },
        "Until you end it again, nobody is absent and the class counts towards nothing. Ending it "
        + "marks whoever still has not scanned absent again."),
      h("p", { class: "hw-muted", style: { margin: 0 } },
        `A scan made since it ended at ${clockTime(s.closed_at)} does not count: anyone who scanned `
        + "after that scans again once it is open.")),
    actions: [button({ label: "Keep it ended", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go_)],
  });
  go_.addEventListener("click", async () => {
    setBusy(go_, true);
    try {
      await api.post(`/api/live/${s.id}/reopen`, {});
      box.close();
      toast("Attendance is open again.");
      go("live");
    } catch (error) {
      setBusy(go_, false);
      toast(error instanceof ApiError ? error.message : "The class was not reopened.", "failure");
    }
  });
}
