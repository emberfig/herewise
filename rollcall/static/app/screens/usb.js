// Screen 34: USB import, gated. Mockups: ImportfromUSBflashdrive.png,
// ImportfromUSBcablenotanswering.png, ImportfromUSBviewerrole.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "34 USB import (gated)".
//
// Nothing here pretends the import works. The parser is written against a real file exported from
// this K40, not documentation (known gap 9), and POST /api/imports/usb returns 501 until it is.
//
// Fixed from the mockup: "Run the connection check" is gated on device.read like every other
// control, because a Viewer cannot run the diagnostics either; and it appears once, not twice.

import { href } from "../router.js";
import { button, h, page, section } from "../ui.js";

const SETTINGS = [
  ["Download Options, Delete ATT Data", "Off",
    "If it is on, the terminal wipes its own copy as it exports, and a failed import loses the scans."],
  ["Download Options, Encrypt", "Off",
    "An encrypted file cannot be read by anything but ZKTeco's own software."],
  ["USB drive format", "FAT32",
    "The terminal does not read exFAT or NTFS drives."],
];

export default {
  id: "usb",
  nav: "device",
  title: "Import from a USB drive",
  permission: "register.pull",

  render(view) {
    view.append(page({
      title: "Import from a USB drive",
      subtitle: "For when the cable cannot be used",
      children: [
        h("div", { class: "hw-panel", dataset: { tone: "review" },
          style: { marginBlockEnd: "var(--hw-space-6)" } },
          h("span", { class: "hw-panel__glyph", "aria-hidden": "true" }, "?"),
          h("div", {},
            h("p", { class: "hw-panel__title" }, "Not available yet"),
            h("p", { class: "hw-panel__body" },
              "The reader for the terminal's own file format is not written. It will be written "
              + "against a real file exported from this K40, not from documentation, because the "
              + "format differs between firmware versions and a parser written from a manual would "
              + "silently mis-read dates."),
            h("p", { class: "hw-panel__body", style: { marginBlockStart: "var(--hw-space-2)" } },
              "Until then, attendance comes off the terminal over the network cable."))),
        section("What to do meanwhile",
          h("div", { class: "hw-card hw-stack" },
            h("p", { style: { margin: 0 } },
              "Nothing is lost while the cable is out. The terminal keeps every scan in its own "
              + "memory until somebody clears it, so they can be read whenever the cable works "
              + "again."),
            h("p", { class: "hw-card__foot" },
              button({ label: "Run the connection check", primary: true, permission: "device.read",
                href: href("device/connection") })))),
        section("When the reader is built, the export settings will matter",
          h("div", { class: "hw-card hw-stack hw-stack--tight" },
            ...SETTINGS.map(([name, value, why]) => h("div", {},
              h("p", { style: { margin: 0 } },
                h("span", { "aria-hidden": "true", style: { color: "var(--hw-review)" } }, "? "),
                h("b", {}, name), " ", h("span", { class: "hw-ids" }, value)),
              h("p", { class: "hw-muted",
                style: { margin: "var(--hw-space-1) 0 0", fontSize: "var(--hw-text-body)" } }, why))),
            h("p", { class: "hw-muted", style: { margin: 0 } },
              "From the manual for a related model. Not yet confirmed on this K40."))),
        button({ label: "Choose a file", primary: true,
          reason: "Not available until the reader is built." }),
      ],
    }));
  },
};
