// Taking attendance: a class taken live. The lecturer presses Start on the course, the queue scans
// at the terminal, and the lecturer presses End when it is done. Asked for on 2026-09-22.
//
// Read from a step away while the queue moves, so the count is the largest thing on the screen and
// the newest scan is at the top of its list. Nobody is shown as absent here: absent is decided when
// the class ends, and until then a student is only "not yet" (rollcall/live.py).
//
// The screen asks the backend to look at the terminal every two seconds, and updates its parts in
// place rather than drawing itself again, so somebody typing in the search box is not interrupted.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import {
  matricText,
  announce, button, chip, clockTime, dialog, emptyState, errorState, field, fill, h, loadingCards,
  page, panel, plural, section, setBusy, toast,
} from "../ui.js";

const EVERY_MS = 2000;

// The sheet the class is on: for a class for one group, that group's sheet rather than the first's.
function sheetOf(open) {
  return `courses/${open.course_id}/sheet${open.group_id ? `?group=${open.group_id}` : ""}`;
}

export default {
  id: "live",
  nav: "courses",
  title: "Taking attendance",
  permission: "register.pull",
  suppressBanners: ["live"],

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Taking attendance", children: [loadingCards(2)] }));
    let status;
    try {
      status = await api.get("/api/live");
    } catch {
      fill(host, page({ title: "Taking attendance",
        children: [errorState({ onRetry: () => ctx.go("live") })] }));
      return;
    }
    if (!status.open) {
      fill(host, page({ title: "Taking attendance", children: [emptyState({
        icon: "◔", heading: "No class is taking attendance",
        body: "Open a course and press Start taking attendance when the class is ready to scan.",
        action: button({ label: "Go to Courses", href: href("courses"), primary: true }),
      })] }));
      return;
    }
    const screen = new Live(host, status.open, ctx);
    view.addEventListener("hw-screen-left", () => screen.stop(), { once: true });
    await screen.start();
  },
};

class Live {
  constructor(host, open, ctx) {
    this.host = host;
    this.open = open;
    this.ctx = ctx;
    this.timer = null;
    this.stopped = false;
    this.seen = new Set();
    this.query = "";
    this.build();
  }

  build() {
    const o = this.open;
    this.count = h("p", { class: "hw-live__count hw-num", "aria-live": "polite" });
    this.of = h("p", { class: "hw-live__of" });
    this.gauge = h("span", { class: "hw-gauge__fill" });
    this.terminal = h("div", { class: "hw-live__terminal" });
    this.scannedList = h("ol", { class: "hw-live__list", "aria-label": "Scanned, newest first" });
    this.waitingList = h("ul", { class: "hw-live__list", "aria-label": "Not scanned yet" });
    this.scannedTitle = h("h2", { class: "hw-section__title" }, "Scanned");
    this.waitingTitle = h("h2", { class: "hw-section__title" }, "Not yet");
    this.clock = h("span");

    const search = h("input", { class: "hw-input", type: "search", autocomplete: "off",
      placeholder: "Find a student", "aria-label": "Find a student who has not scanned" });
    search.addEventListener("input", () => { this.query = search.value; this.drawLists(); });

    this.endButton = button({ label: "End attendance", primary: true, busyLabel: "Ending",
      onClick: () => this.confirmEnd() });

    fill(this.host, page({
      title: "Taking attendance",
      // A class for one group says so wherever it is named: its register is that group's alone.
      subtitle: h("span", {}, `${o.code}${o.group ? ` ${o.group}` : ""}${o.week ? ` · ${o.week}, class ${o.position}` : ""}`
        + ` · started ${clockTime(o.opened_at)}`, this.clock),
      crumbs: [h("a", { class: "hw-link", href: href(sheetOf(o)) },
        h("span", { "aria-hidden": "true" }, "← "), o.code)],
      actions: [this.endButton],
      children: [
        this.terminal,
        h("div", { class: "hw-live__figure" },
          h("div", {}, this.count, this.of),
          h("div", { class: "hw-gauge hw-live__gauge", role: "presentation" }, this.gauge)),
        h("p", { class: "hw-muted", style: { margin: "0 0 var(--hw-space-6)" } },
          "Each student scans once at the terminal and appears here within a couple of seconds. "
          + "Nobody is marked absent until you end attendance."),
        h("div", { class: "hw-live__columns" },
          h("section", { class: "hw-section hw-live__column" }, this.scannedTitle, this.scannedList),
          h("section", { class: "hw-section hw-live__column" }, this.waitingTitle,
            h("p", { style: { margin: "0 0 var(--hw-space-3)" } }, search), this.waitingList)),
      ],
    }));
  }

  async start() {
    await this.tick();
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
  }

  async tick() {
    if (this.stopped) return;
    try {
      const answer = await api.post(`/api/live/${this.open.class_id}/refresh`, {});
      this.draw(answer);
      if (!answer.register.open) {
        // Ended somewhere else: another window, or somebody else signed in.
        this.stop();
        this.showEnded(answer.register, null);
        return;
      }
    } catch (error) {
      this.drawTerminal({ state: "unreachable",
        detail: error instanceof ApiError ? error.message : "Herewise did not answer." });
    }
    if (!this.stopped) this.timer = setTimeout(() => this.tick(), EVERY_MS);
  }

  draw({ register, terminal }) {
    this.register = register;
    const t = register.totals;
    this.count.textContent = `${t.present} present`;
    this.of.textContent = `of ${plural(t.students, "student")} · ${t.waiting} not yet`
      + (t.excused ? ` · ${t.excused} excused` : "");
    this.gauge.style.width = `${t.students ? Math.round((100 * t.present) / t.students) : 0}%`;
    const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(this.open.opened_at)) / 60000));
    this.clock.textContent = ` · ${minutes ? plural(minutes, "minute") + " ago" : "just now"}`;
    this.drawTerminal(terminal);
    this.announceNew(register);
    this.drawLists();
  }

  drawTerminal(terminal) {
    if (!terminal || terminal.state === "connected" || terminal.state === "closed") {
      fill(this.terminal, h("p", { class: "hw-live__line" },
        chip("connected", "Terminal answering", terminal?.checked_at || null)));
      this.ctx.shell.setDevice("connected");
      return;
    }
    if (terminal.state === "busy") {
      fill(this.terminal, panel({ tone: "info", title: "The terminal is busy",
        body: `${terminal.detail || "Something else is using it."} Scans made meanwhile are kept on `
          + "the terminal and come in as soon as it is free." }));
      this.ctx.shell.setDevice("busy");
      return;
    }
    fill(this.terminal, panel({ tone: "failure", role: "alert", title: "The terminal is not answering",
      body: `${terminal.detail || ""} Students can keep scanning: the terminal keeps every scan, `
        + "and they come in here as soon as it answers again. The class stays open.",
      children: [h("p", { style: { margin: "var(--hw-space-2) 0 0" } },
        h("a", { class: "hw-link", href: href("device/connection") }, "Run the connection check"))] }));
    this.ctx.shell.setDevice("unreachable");
  }

  announceNew(register) {
    const fresh = register.students.filter((s) => s.present && !this.seen.has(s.person_id));
    for (const s of register.students) if (s.present) this.seen.add(s.person_id);
    if (!this.first) {
      this.first = true;   // what was already there when the screen opened is not news
      return;
    }
    if (fresh.length === 1) announce(`${fresh[0].surname} ${fresh[0].other_names} scanned.`);
    else if (fresh.length > 1) announce(`${fresh.length} more scanned.`);
  }

  drawLists() {
    const r = this.register;
    if (!r) return;
    const name = (s) => `${s.surname} ${s.other_names}`.trim();
    const scanned = r.students.filter((s) => s.present)
      .sort((a, b) => String(b.first_scan || "").localeCompare(String(a.first_scan || "")));
    const waiting = r.students.filter((s) => s.status === "waiting");
    this.scannedTitle.textContent = `Scanned ${scanned.length}`;
    this.waitingTitle.textContent = `Not yet ${waiting.length}`;

    fill(this.scannedList, ...(scanned.length ? scanned.map((s) => h("li", { class: "hw-live__item" },
      h("span", { class: "hw-live__mark", "aria-hidden": "true" }, "✓"),
      h("span", { class: "hw-live__who" }, h("span", { class: "hw-live__name" }, name(s)),
        h("span", { class: "hw-live__matric hw-ids" }, matricText(s.matric_no))),
      h("span", { class: "hw-live__time hw-num" },
        s.first_scan ? clockTime(s.first_scan) : "corrected")))
      : [h("li", { class: "hw-live__empty" }, "Nobody yet. The first scan appears here.")]));

    const q = this.query.trim().toLowerCase();
    const shown = q ? waiting.filter((s) => `${name(s)} ${matricText(s.matric_no)}`.toLowerCase().includes(q)) : waiting;
    fill(this.waitingList, ...(shown.length ? shown.map((s) => h("li", { class: "hw-live__item" },
      h("span", { class: "hw-live__mark hw-live__mark--waiting", "aria-hidden": "true" }, "○"),
      h("span", { class: "hw-live__who" }, h("span", { class: "hw-live__name" }, name(s)),
        h("span", { class: "hw-live__matric hw-ids" }, matricText(s.matric_no)))))
      : [h("li", { class: "hw-live__empty" },
        waiting.length ? "Nobody who has not scanned matches that." : "Everybody has scanned.")]));
  }

  confirmEnd() {
    const t = this.register?.totals || { present: 0, waiting: 0 };
    const now = new Date();
    const hhmm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    const when = field({ label: "Ended at", name: "ended_at", type: "time", value: hhmm, width: "short",
      help: "Change this only if the class finished earlier and you are ending it late." });
    const go = button({ label: "End attendance", primary: true, busyLabel: "Ending" });
    const box = dialog({
      title: `End attendance for ${this.open.code}${this.open.group ? ` ${this.open.group}` : ""}?`,
      body: h("div", { class: "hw-stack hw-stack--tight" },
        h("p", { style: { margin: 0 } },
          `${t.present} present. `
          + (t.waiting ? `The ${plural(t.waiting, "student")} who have not scanned will be marked absent.`
            : "Everybody has scanned.")),
        h("p", { class: "hw-muted", style: { margin: 0 } },
          "Herewise reads the terminal once more first, so a scan made in the last seconds still "
          + "counts. A scan made after the class has ended does not."),
        when),
      actions: [button({ label: "Keep taking attendance", onClick: () => box.close() }),
        h("span", { class: "hw-cardfoot__end" }, go)],
    });
    go.addEventListener("click", async () => {
      const input = when.querySelector("input");
      // Only a time somebody changed is sent. The default is now to the minute, and sending it
      // would end the class at the start of this minute and drop whoever scanned in it.
      const changed = input && input.value && input.value !== hhmm;
      setBusy(go, true);
      try {
        this.stop();
        const ended = await api.post(`/api/live/${this.open.class_id}/end`,
          changed ? { ended_at: input.value } : {});
        box.close();
        this.showEnded(ended, ended.sheet);
        announce(`Attendance taken. ${ended.totals.present} present, ${ended.totals.absent} absent.`);
      } catch (error) {
        setBusy(go, false);
        toast(error instanceof ApiError ? error.message : "The class did not end.", "failure");
        this.stopped = false;
        this.tick();
      }
    });
  }

  showEnded(register, sheet) {
    const t = register.totals;
    const o = this.open;
    this.ctx.shell.refresh?.();
    const ordinal = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh"][(sheet?.position || 1) - 1];
    const where = sheet?.week ? `It is ${sheet.week}'s ${ordinal || ""} class on the sheet.`.replace("  ", " ")
      : sheet?.outside ? "It falls outside the weeks on the sheet: change the weeks in Sheet setup to show it."
        : "";
    fill(this.host, page({
      title: "Attendance taken",
      subtitle: `${o.code}${o.group ? ` ${o.group}` : ""} · ${clockTime(register.session.opened_at)} to `
        + `${clockTime(register.session.closed_at)}`,
      crumbs: [h("a", { class: "hw-link", href: href(sheetOf(o)) },
        h("span", { "aria-hidden": "true" }, "← "), o.code)],
      children: [
        panel({ tone: "success", role: "status", title: `${t.present} present, ${t.absent} absent`
          + (t.excused ? `, ${t.excused} excused` : ""),
        body: `Everybody who did not scan is marked absent. ${where}`.trim() }),
        h("p", { class: "hw-row", style: { marginBlockStart: "var(--hw-space-6)" } },
          button({ label: "Open the sheet", primary: true, href: href(sheetOf(o)) }),
          button({ label: "See who was absent", href: href(`classes/${register.session.id}`) })),
      ],
    }));
  }
}
