// Screen 40: About. Mockups: AboutHerewise.png, Aboutlicenceopened.png, Aboutvieweraccess.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "40 About". Contract: GET /api/about.
//
// The version and every licence are read from the running code and the installed packages, never
// from a list written here that would go stale the first time something is upgraded.
//
// pyzk is GPL-2.0, and that is stated on this screen rather than only in a document nobody opens:
// handing a copy of Herewise to somebody else generally makes the whole of it GPL as well.
//
// Fixed from the mockup: the footer telling people to ask before changing anything is dropped,
// because nothing on this screen can be changed.

import { api } from "../api.js";
import { mark } from "../icons.js";
import { fill, h, loadingCards, page, section, studioLink, table } from "../ui.js";

// These are read from the terminal the first time it answers. A dash would leave a screen reader
// saying "en dash" and a person guessing whether the value was empty or unknown.
const NOT_READ = "Not read from the terminal yet";

export default {
  id: "about",
  nav: "settings",
  title: "About",
  permission: null,

  async render(view) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "About", children: [loadingCards(2)] }));
    const data = await api.get("/api/about");
    draw(host, data);
  },
};

function draw(host, data) {
  fill(host, page({
    title: `${data.name} ${data.version}`,
    subtitle: ["Made by ", studioLink()],
    children: [
      h("div", { class: "hw-card hw-row", style: { gap: "var(--hw-space-6)", alignItems: "center",
        marginBlockEnd: "var(--hw-space-8)" } },
        mark({ size: 64 }),
        h("div", { style: { flex: "1 1 320px" } },
          h("p", { style: { margin: 0, maxWidth: "62ch" } },
            "Lecture attendance from a ZKTeco fingerprint terminal, kept on this computer. It works "
            + "with no internet, nothing is sent anywhere, and every scan, correction and decision "
            + "stays in one file you can copy."),
          h("p", { class: "hw-muted hw-ids", style: { margin: "var(--hw-space-3) 0 0" } },
            `Register kept in ${data.data_folder}`))),

      data.device ? section("The terminal this copy talks to",
        h("dl", { class: "hw-facts hw-ids" },
          h("dt", {}, "Name"), h("dd", {}, data.device.name),
          h("dt", {}, "Address"), h("dd", {}, `${data.device.ip}:${data.device.port}`),
          h("dt", {}, "Serial"), h("dd", {}, data.device.serial || NOT_READ),
          h("dt", {}, "Firmware"), h("dd", {}, data.device.firmware || NOT_READ),
          h("dt", {}, "Platform"), h("dd", {}, data.device.platform || NOT_READ))) : null,

      section("Licences",
        h("div", { class: "hw-panel", dataset: { tone: "info" },
          style: { marginBlockEnd: "var(--hw-space-4)" } },
          h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "i"),
          h("div", {},
            h("p", { class: "hw-panel__title" }, "Herewise is free software"),
            h("p", { class: "hw-panel__body" }, data.licence_note))),
        table({
          caption: "The libraries this copy is built on",
          rows: data.packages,
          columns: [
            { label: "Library", render: (p) => h("span", {}, p.name,
              h("span", { class: "hw-muted hw-ids" }, ` ${p.version}`)) },
            { label: "Licence", render: (p) => p.licence },
            { label: "What it does here", render: (p) => p.why },
          ],
        })),

      section("Typefaces",
        table({
          caption: "The typefaces bundled with this copy",
          rows: data.fonts,
          columns: [
            { label: "Typeface", render: (f) => f.name },
            { label: "Licence", render: (f) => f.licence },
            { label: "Full text", align: "end", render: (f) =>
              h("a", { class: "hw-link", href: f.file, target: "_blank", rel: "noopener" },
                "Read the licence") },
          ],
        }),
        h("p", { class: "hw-section__help" },
          "Both are bundled with the app and never fetched, because this runs in a lecture theatre "
          + "with no internet.")),
    ],
  }));
}
