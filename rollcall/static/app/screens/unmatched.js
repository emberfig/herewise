// Screen 33: Unmatched scans. Mockups: Unmatchedscans.png, Unmatchedscansnothingunmatched.png,
// Unmatchedscans2259opened.png, UnmatchedscansstaffID17opened.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "33 Unmatched scans".
//
// A question mark marks every unknown here, which is exactly the rule's meaning: no verdict can be
// given until somebody says who the ID belongs to.
//
// Each explanation comes from the ID's own range, because that is all Herewise knows: an ID inside
// a level's block is a student who was never imported, and one outside every block came from the
// terminal's keypad.

import { api } from "../api.js";
import { href } from "../router.js";
import {
  dateAndTime, emptyState, fill, h, loadingTable, page, plural, section, table,
} from "../ui.js";

export default {
  id: "unmatched",
  nav: "device",
  title: "Unmatched scans",
  permission: "register.read",

  async render(view) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Unmatched scans",
      children: [loadingTable(["Device ID", "Scans", "First", "Last", "What it probably is"])] }));
    const [rows, levels] = await Promise.all([
      api.get("/api/punches/unmatched"),
      api.get("/api/levels").catch(() => []),
    ]);
    draw(host, rows, levels);
  },
};

function draw(host, rows, levels) {
  const scans = rows.reduce((n, r) => n + r.scans, 0);
  fill(host, page({
    title: "Unmatched scans",
    subtitle: rows.length
      ? `${plural(scans, "scan")} from ${plural(rows.length, "device ID")} nobody in the roster has`
      : "No unmatched scans",
    children: [
      rows.length
        ? h("div", {},
          h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-6)" } },
            "These scans are stored and count towards nothing. If the person is imported later with "
            + "the same device ID, their scans attach themselves and their attendance appears."),
          table({
            caption: "Device IDs nobody in the roster has",
            rows,
            columns: [
              { label: "Device ID", render: (r) => h("span", { class: "hw-ids" },
                h("span", { "aria-hidden": "true", style: { color: "var(--hw-review)" } }, "? "),
                r.device_user_id) },
              { label: "Scans", align: "end", render: (r) =>
                h("span", { class: "hw-tnum" }, String(r.scans)) },
              { label: "First", render: (r) => h("span", { class: "hw-tnum" }, dateAndTime(r.first_scan)) },
              { label: "Last", render: (r) => h("span", { class: "hw-tnum" }, dateAndTime(r.last_scan)) },
              { label: "What it probably is", render: (r) => explain(r.device_user_id, levels) },
            ],
          }))
        : h("div", { class: "hw-table-frame" }, emptyState({
          icon: "✓",
          heading: "No unmatched scans",
          body: "Every scan on this computer belongs to someone in the roster.",
        })),
    ],
  }));
}

/** From the ID's range alone, because that is all Herewise can know about a stranger's scan. */
function explain(deviceId, levels) {
  const id = Number(deviceId);
  if (!Number.isInteger(id)) {
    return h("span", {}, "Not a whole number, so the terminal sent something unexpected.");
  }
  const level = levels.find((l) => id >= l.id_block_start && id <= l.id_block_end);
  if (level) {
    return h("span", {},
      `Inside the block for ${level.name}, so probably a student who has not been imported. `,
      h("a", { class: "hw-link", href: href(`levels/${level.id}/import`) }, "Import that level"),
      ". No new student will be given this ID.");
  }
  if (id >= 1 && id <= 999) {
    return h("span", {}, "In the staff range, so probably someone added at the terminal's keypad.");
  }
  return h("span", {}, "Outside every level's block, so it was almost certainly typed at the terminal.");
}
