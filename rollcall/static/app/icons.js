// Line icons for the rail and a few controls. Drawn here rather than shipped as files: they are
// seven shapes, they must take `currentColor` to follow the theme, and nothing is ever fetched at
// runtime. The logo is the one mark that is never redrawn: it comes from design/logo.py, verbatim.
//
// One grid: 24 units, 1.75 stroke, round caps and joins, so they sit together on the rail.

import { h } from "./ui.js";

const PATHS = {
  today: ["M7 3v3", "M17 3v3", "M4 9h16", "M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"],
  courses: ["M4 5a1 1 0 0 1 1-1h5a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H5a1 1 0 0 1-1-1z",
            "M20 5a1 1 0 0 0-1-1h-5a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h5a1 1 0 0 0 1-1z"],
  students: ["M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M3 20a6 6 0 0 1 12 0",
             "M16.5 11.5a3 3 0 0 0 0-6", "M17 14.5a5.5 5.5 0 0 1 4 5.5"],
  levels: ["M12 3 3 7.5 12 12l9-4.5z", "M3 12.5 12 17l9-4.5", "M3 17 12 21.5 21 17"],
  enrolment: ["M9 4h6v3H9z", "M7 5H6a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-1",
              "M9 12h6", "M9 16h4"],
  device: ["M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z",
           "M8 6h8v5H8z", "M9 14.5h1.5", "M14 14.5h1", "M9 18h1.5", "M14 18h1"],
  settings: ["M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
             "M19.4 14.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.2a1.6 1.6 0 0 0-2.8-1 1.6 1.6 0 0 0-1.7.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 14.5H3a2 2 0 1 1 0-4h.2a1.6 1.6 0 0 0 1-2.8 1.6 1.6 0 0 0-.3-1.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.2a1.6 1.6 0 0 0-1.4 1z"],
  search: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z", "m20 20-4-4"],
  download: ["M12 4v11", "m7.5 11 4.5 4 4.5-4", "M5 20h14"],
  file: ["M13 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V8z", "M13 3v5h5", "M9 13h6", "M9 17h4"],
};

export function icon(name, { size = 20 } = {}) {
  const paths = PATHS[name];
  if (!paths) return null;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.75");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

/** The mark, exactly as design/logo.py draws it: two stems in currentColor, the tick in the accent. */
export function mark({ size = 32 } = {}) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 64 64");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const x of [12, 44]) {
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", String(x));
    rect.setAttribute("y", "8");
    rect.setAttribute("width", "8");
    rect.setAttribute("height", "48");
    rect.setAttribute("fill", "currentColor");
    svg.append(rect);
  }
  const tick = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  tick.setAttribute("points", "15 31 24 40 49 24");
  tick.setAttribute("fill", "none");
  tick.setAttribute("stroke", "var(--hw-accent)");
  tick.setAttribute("stroke-width", "6");
  tick.setAttribute("stroke-linecap", "round");
  tick.setAttribute("stroke-linejoin", "round");
  svg.append(tick);
  return svg;
}

/** The wordmark: live type in Inter 600, never outlined (docs/DESIGN-BRIEF.md). */
export function wordmark() {
  return h("span", {}, "herewise");
}
