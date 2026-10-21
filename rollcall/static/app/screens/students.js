// Screen 20: Student search. Mockups: StudentsSearchoko.png, StudentsATooshort.png,
// StudentsBNomatch.png, StudentsCDeviceIDmatch.png. Fix list: docs/DESIGN-DEVIATIONS.md, "20".
//
// Kept from the mockup: searching a device ID moves the highlight to the ID rather than the name,
// and says so in one line.
//
// Fixed from the mockup:
//   one search field, not two. The top bar routes here and this screen's own field owns the query;
//   when results share a surname, the part that tells them apart is the part that stands out.
//     OKONKWO Daniel and OKONKWO Deborah differ by forename, so the forename carries the weight and
//     the highlight, not the surname they have in common.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { matricText, announce, button, emptyState, fill, h, page, plural, section, table } from "../ui.js";

export default {
  id: "students",
  title: "Students",
  permission: "students.read",

  async render(view, { query }) {
    const host = h("div");
    view.append(host);
    const state = { q: query.get("q") || "", rows: null, error: "" };

    const input = h("input", { class: "hw-input", type: "search", value: state.q,
      placeholder: "Name, matric number or device ID", autocomplete: "off",
      "aria-label": "Find a student" });
    let pending = null;
    const run = async () => {
      const q = input.value.trim();
      state.q = q;
      if (q.length < 2) {
        state.rows = null;
        state.error = q ? "Type at least 2 characters: part of a name, a matric number or a device ID." : "";
        return paint();
      }
      try {
        state.rows = await api.get(`/api/students/search?q=${encodeURIComponent(q)}`);
        state.error = "";
      } catch (error) {
        state.rows = [];
        state.error = error instanceof ApiError ? error.message : "That search did not work.";
      }
      paint();
    };
    input.addEventListener("input", () => { clearTimeout(pending); pending = setTimeout(run, 200); });

    const body = h("div");
    function paint() {
      fill(body, results(state));
      history.replaceState(null, "",
        state.q ? `#/students?q=${encodeURIComponent(state.q)}` : "#/students");
    }

    fill(host, page({
      title: "Students",
      subtitle: "Find a student, then open everything behind their attendance",
      children: [
        h("div", { style: { maxWidth: "520px", marginBlockEnd: "var(--hw-space-6)" } }, input),
        body,
      ],
    }));
    paint();
    if (state.q) await run();
    input.focus();
  },
};

function results(state) {
  if (state.error) {
    return h("div", { class: "hw-table-frame" }, emptyState({
      icon: "⌕", heading: "Not enough to search on", body: state.error }));
  }
  if (state.rows === null) {
    return h("div", { class: "hw-table-frame" }, emptyState({
      icon: "⌕",
      heading: "Search for a student",
      body: "Part of a name, a matric number, or the device ID the terminal knows them by. "
        + "Accents and capitals do not matter: olabisi finds Ọlábísí.",
    }));
  }
  if (!state.rows.length) {
    return h("div", { class: "hw-table-frame" }, emptyState({
      icon: "⌕",
      heading: `No student matches "${state.q}"`,
      body: "Check the spelling, or try the matric number. A student who has never been imported "
        + "will not be here even if their scans are.",
    }));
  }

  const byDeviceId = state.rows.some((r) => String(r.device_user_id) === state.q);
  // When results share a surname, the forename is what tells them apart.
  const surnames = new Map();
  for (const row of state.rows) surnames.set(row.surname, (surnames.get(row.surname) || 0) + 1);

  return section("",
    byDeviceId
      ? h("div", { class: "hw-panel", dataset: { tone: "info" },
          style: { marginBlockEnd: "var(--hw-space-4)" } },
        h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "i"),
        h("p", { class: "hw-panel__body" },
          `${state.q} is a device ID, so this is the student the terminal knows by that number.`))
      : null,
    h("p", { class: "hw-muted", role: "status", style: { marginBlockEnd: "var(--hw-space-3)" } },
      `${plural(state.rows.length, "student")} found`),
    table({
      caption: "Students matching the search",
      rows: state.rows,
      limit: 25,
      what: "student",
      rowHref: (r) => href(`students/${r.id}`),
      columns: [
        { label: "Name", render: (r) => nameCell(r, state.q, surnames.get(r.surname) > 1) },
        { label: "Matric no.", render: (r) => mark(matricText(r.matric_no), state.q, "hw-ids") },
        { label: "Level", render: (r) => r.level || h("span", { class: "hw-muted" }, "–") },
        { label: "Device ID", align: "end", render: (r) =>
          mark(String(r.device_user_id), state.q, "hw-ids") },
        { label: "", align: "end", render: (r) => r.active
          ? null
          : h("span", { class: "hw-pill", dataset: { tone: "neutral" } },
            h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "○"), "Inactive") },
      ],
    }));
}

function nameCell(row, query, sharedSurname) {
  // The distinguishing part outweighs the shared part.
  const surname = sharedSurname
    ? h("span", { class: "hw-muted" }, row.surname)
    : h("b", {}, mark(row.surname, query));
  const others = sharedSurname
    ? h("b", {}, mark(row.other_names, query))
    : h("span", {}, mark(row.other_names, query));
  return h("span", {}, surname, " ", others);
}

/** The matched run, marked. Case and accents are folded the way the backend folds them. */
function mark(text, query, className = "") {
  const value = String(text ?? "");
  const fold = (s) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
  const at = fold(value).indexOf(fold(query.trim()));
  if (!query.trim() || at < 0) return h("span", { class: className || null }, value);
  return h("span", { class: className || null },
    value.slice(0, at),
    h("mark", { class: "hw-mark" }, value.slice(at, at + query.trim().length)),
    value.slice(at + query.trim().length));
}
