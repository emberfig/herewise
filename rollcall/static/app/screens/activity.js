// Screen 38: Activity log. Mockups: Activitylog.png, Activitylogoneperson.png,
// Activitylognothinginrange.png, Activitylogexportready.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "38 Activity log". Backend: rollcall/audit.py, known gap 17.
//
// Before today this screen could not exist: GET /api/audit took only a limit, and its detail was
// raw text, for example str(body) for a settings change. An audit log nobody can narrow, and whose
// rows read like a Python repr, is decoration rather than a record.
//
// Every row is a sentence made when it is read. Nothing in the table is rewritten: the log is
// append-only and a database trigger enforces it.

import { ApiError, api, download } from "../api.js";
import {
  announce, button, dateAndTime, emptyState, fill, h, loadingTable, page, plural, saveFile,
  section, table,
} from "../ui.js";

export default {
  id: "activity",
  nav: "settings",
  title: "Activity log",
  permission: "audit.read",

  async render(view) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Activity log",
      children: [loadingTable(["When", "Who", "What happened"])] }));
    const data = await api.get("/api/audit?limit=500");
    draw(host, data);
  },
};

function draw(host, first) {
  const state = { from: "", to: "", actor: "", group: "", data: first };
  const list = h("div");

  const query = () => {
    const q = new URLSearchParams({ limit: "500" });
    if (state.from) q.set("date_from", state.from);
    if (state.to) q.set("date_to", state.to);
    if (state.actor) q.set("account_id", state.actor);
    if (state.group) q.set("group", state.group);
    return q;
  };

  async function run() {
    try {
      state.data = await api.get(`/api/audit?${query()}`);
    } catch (error) {
      return fill(list, h("p", { class: "hw-field__error" },
        h("span", { "aria-hidden": "true" }, "✕"),
        h("span", {}, error instanceof ApiError ? error.message : "That did not load.")));
    }
    paint();
  }

  const from = dateBox("From", (value) => { state.from = value; run(); });
  const to = dateBox("To", (value) => { state.to = value; run(); });

  const actor = h("select", { class: "hw-select", "aria-label": "Who did it" });
  actor.append(h("option", { value: "" }, "Anyone"));
  for (const person of first.actors) {
    actor.append(h("option", { value: person.id },
      `${person.display_name} · ${plural(person.entries, "entry", "entries")}`));
  }
  actor.addEventListener("change", () => { state.actor = actor.value; run(); });

  const group = h("select", { class: "hw-select", "aria-label": "What kind of thing" });
  group.append(h("option", { value: "" }, "Everything"));
  for (const name of first.groups) group.append(h("option", { value: name }, name));
  group.addEventListener("change", () => { state.group = group.value; run(); });

  const exportCsv = button({ label: "Export what is shown", glyph: "↓",
    busyLabel: "Writing the file",
    onClick: () => {
      const q = query();
      q.delete("limit");
      return saveFile(exportCsv, `/api/audit/export?${q}`, "The activity log");
    } });

  function paint() {
    const rows = state.data.entries;
    const narrowed = state.from || state.to || state.actor || state.group;
    fill(list,
      h("p", { class: "hw-muted", role: "status", style: { marginBlock: "var(--hw-space-3)" } },
        narrowed
          ? `${plural(rows.length, "entry", "entries")} in this range`
          : `The last ${plural(rows.length, "entry", "entries")}`),
      rows.length
        ? table({
          caption: "Who did what",
          density: "compact",
          rows,
          columns: [
            { label: "When", className: "hw-nowrap", render: (r) =>
              h("span", { class: "hw-tnum hw-nowrap" }, dateAndTime(r.at)) },
            { label: "Who", render: (r) => h("span", {}, r.by,
              r.role ? h("span", { class: "hw-muted" }, `, ${r.role}`) : null) },
            { label: "What happened", render: (r) => r.sentence },
            { label: "Kind", align: "end", render: (r) =>
              h("span", { class: "hw-tag" }, r.group) },
          ],
        })
        : h("div", { class: "hw-table-frame" }, emptyState({
          icon: "⌕",
          heading: "Nothing in that range",
          body: "Nobody did anything matching these filters. Widen the dates, or choose Anyone.",
          action: button({ label: "Clear the filters", onClick: () => {
            state.from = ""; state.to = ""; state.actor = ""; state.group = "";
            from.control.value = ""; to.control.value = ""; actor.value = ""; group.value = "";
            run();
          } }),
        })));
  }

  fill(host, page({
    title: "Activity log",
    subtitle: "Who did what, in the order it happened",
    actions: [exportCsv],
    wide: true,
    children: [
      h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-4)" } },
        "Every entry is written as it happens and none can be changed or deleted afterwards, which "
        + "a database trigger enforces. This is what answers "
        + "“who changed that, and when”."),
      h("div", { class: "hw-row", style: { alignItems: "flex-end", marginBlockEnd: "var(--hw-space-2)" } },
        h("div", { style: { flex: "0 1 180px" } }, from),
        h("div", { style: { flex: "0 1 180px" } }, to),
        h("div", { class: "hw-field", style: { flex: "0 1 260px" } },
          h("label", { class: "hw-field__label" }, "Who"), actor),
        h("div", { class: "hw-field", style: { flex: "0 1 220px" } },
          h("label", { class: "hw-field__label" }, "Kind"), group)),
      list,
    ],
  }));
  paint();
}

function dateBox(label, onChange) {
  const input = h("input", { class: "hw-input hw-ids", type: "date", "aria-label": label });
  input.addEventListener("change", () => onChange(input.value));
  const wrap = h("div", { class: "hw-field" },
    h("label", { class: "hw-field__label" }, label), input);
  wrap.control = input;
  return wrap;
}
