// Every route at several window widths, reporting anything that overflows, collides, cannot be
// hit or cannot be read.
//
//   node scripts/check_layout.mjs <port> [out folder]
//
// Give it the port scripts/dev_server.py is on. It signs in as the demo owner, walks every route at
// 1920, 1366, 1280 and 1024, and writes layout.json plus a screenshot of every route at 1366 and
// 1024. It ends by planting three faults it must find, because a check that cannot fail is not a
// check: exit 2 means the measurements themselves stopped working.
//
// What it looks for, all of it measurable rather than a matter of taste:
//   * the page scrolling sideways, or a control past the right edge with no way to reach it
//   * a control whose real hit area is under the 24x24 CSS px floor (WCAG 2.2 SC 2.5.8), measured
//     by what a press at each corner would actually activate, so a checkbox inside a label counts
//     as the size of the label
//   * a text box wider than the measure a sentence is read at, which promises a long answer
//   * text under 12px, and a line of prose past about 80 characters
//   * two controls overlapping each other, which is a misparented layout
//   * a control meant to be the size of its words stretched by the grid it sits in
//
// A link inside a sentence, a control under the sticky action bar, and a control inside a frame
// that scrolls sideways are all counted separately: each is either exempt or one scroll away.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = process.argv[2] || "8000";
const PROVE = !process.argv.includes("--no-prove");
const OUT = process.argv[3] || join(tmpdir(), "herewise-layout");
const BASE = `http://127.0.0.1:${PORT}`;
const CHROME = join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1208", "chrome-win64", "chrome.exe");
const DEBUG = 9451;
const WIDTHS = [[1920, 1080], [1366, 768], [1280, 800], [1024, 768]];
const ROUTES = [
  "today", "pull", "unassigned", "corrections", "courses", "courses/new", "courses/1",
  "courses/1/sheet", "courses/1/setup", "courses/1/classes", "courses/1/students",
  "courses/1/percentages", "courses/1/eligibility", "courses/1/progress", "courses/1/groups",
  "courses/4/groups", "courses/4/sheet", "courses/4/classes", "courses/4/percentages", "classes/27", "classes/21",
  "students", "students/1", "levels", "levels/2/import", "excusals",
  "enrolment", "device", "device/connection", "device/admins", "device/push",
  "device/unmatched", "device/usb", "device/unlock", "device/clear", "device/empty",
  "settings", "settings/accounts", "settings/roles", "settings/activity",
  "settings/backup", "settings/about",
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

mkdirSync(OUT, { recursive: true });
const profile = mkdtempSync(join(tmpdir(), "hw-layout-"));
const chrome = spawn(CHROME, [`--remote-debugging-port=${DEBUG}`, `--user-data-dir=${profile}`,
  "--headless=new", "--window-size=1920,1080", "--no-first-run", "--no-default-browser-check",
  "--disable-component-update", "about:blank"], { stdio: "ignore" });

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${DEBUG}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(200);
  }
  throw new Error("Chrome did not start");
}

const ws = new WebSocket(await target());
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const waiting = new Map();
const thrown = [];
ws.addEventListener("message", (event) => {
  const m = JSON.parse(event.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m.result ?? m.error); waiting.delete(m.id); }
  if (m.method === "Runtime.exceptionThrown") thrown.push(m.params.exceptionDetails.text);
});
const send = (method, params = {}) => new Promise((resolve) => {
  const n = ++id; waiting.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params }));
});
const evaluate = async (expression) => (await send("Runtime.evaluate",
  { expression, awaitPromise: true, returnByValue: true }))?.result?.value;

const MEASURE = `(() => {
  const out = { overflowX: 0, tooSmall: [], tinyText: [], overhang: [], overlaps: [],
                tooWide: [], tooClose: [], tooLong: [], stretched: [] };
  const doc = document.documentElement;
  out.overflowX = Math.max(0, doc.scrollWidth - doc.clientWidth);
  const main = document.getElementById('main');
  const edge = main ? main.getBoundingClientRect().right : window.innerWidth;
  const label = (el) => (el.textContent || el.getAttribute('aria-label') || el.tagName)
    // Doubled, because this whole block is a template literal: a single backslash would reach the
    // page as /s+/ and quietly strip every s from the labels it reports.
    .trim().replace(/\\s+/g, ' ').slice(0, 40);
  // What a click at this point would actually activate. A checkbox inside a label is as big as the
  // label, and measuring the input's own box called an easy target too small.
  const activated = (node) => {
    if (!node) return null;
    const lab = node.closest('label');
    if (lab && lab.control) return lab.control;
    return node.closest('button, a[href], input, select, textarea, [role="button"]');
  };
  const reaches = (el, size) => {
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2, half = size / 2 - 0.5;
    const mine = activated(el);
    if (!mine) return true;
    return [[cx - half, cy - half], [cx + half, cy - half], [cx - half, cy + half], [cx + half, cy + half]]
      .every(([x, y]) => {
        if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return true;
        // Nothing at all under a point means the point is outside what the window shows, not that
        // something covers the control. The visible area is shorter than innerHeight by the
        // scrollbar, and a Remove button straddling the foot of a 1080px window was called too
        // small because its lower test points found nothing (Sheet setup at 1920, 2026-09-23).
        const there = document.elementFromPoint(x, y);
        if (there === null) return true;
        return activated(there) === mine;
      });
  };
  const controls = [...document.querySelectorAll(
    'button, a[href], input, select, textarea, [role="button"], [tabindex="0"]')]
    .filter((el) => el.getClientRects().length && el.offsetWidth > 1 && el.offsetHeight > 1);
  for (const el of controls) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (!reaches(el, 24)) {
      // A link inside a sentence is exempt from WCAG 2.2 SC 2.5.8, so it is reported separately
      // rather than counted as a fault.
      // Inline means "in a sentence", which WCAG 2.2 SC 2.5.8 exempts: any real words around it
      // in the same block, not counting the control's own accessible name.
      const para = el.closest('p, li, td, th, dd, caption');
      const around = para
        ? para.textContent.trim().length - el.textContent.trim().length : 0;
      // Two more that are not faults. A control under the sticky action bar is covered while the
      // bar is stuck and scrolls clear of it, and one inside a frame that scrolls sideways is one
      // scroll away, which is what the frame is for.
      const covered = !!document.querySelector('.hw-sticky')
        && (() => {
          const bar = document.querySelector('.hw-sticky').getBoundingClientRect();
          return r.bottom > bar.top - 4 && r.top < bar.bottom + 4;
        })();
      const inline = (!!para && around > 3) || covered
        || !!el.closest('[data-overflowing="true"]');
      out.tooSmall.push({ what: label(el), w: Math.round(r.width), h: Math.round(r.height),
                          inline });
    }
    // Past the page edge only counts when there is no way to reach it. A control inside a frame
    // that scrolls sideways is one scroll away, which is the point of the frame.
    if (r.right > edge + 2 && !el.closest('[data-overflowing="true"]')) {
      out.overhang.push({ what: label(el), over: Math.round(r.right - edge) });
    }
  }
  for (const el of document.querySelectorAll('#main *')) {
    if (!el.firstChild || el.firstChild.nodeType !== 3 || !el.textContent.trim()) continue;
    if (!el.getClientRects().length) continue;
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size && size < 12) out.tinyText.push({ what: label(el), px: Math.round(size * 10) / 10 });
  }
  // A control meant to be the size of its words, stretched by the grid it sits in. The toggle on
  // Send to the device became a 1,020px bar across a card because inline-flex says nothing to a
  // grid item (2026-09-22).
  for (const el of document.querySelectorAll('#main :is(.hw-toggle, .hw-pill, .hw-chip)')) {
    const r = el.getBoundingClientRect();
    if (!r.width) continue;
    // A Range over the contents, not the element children: a pill's own words are a text node and
    // summing only the child elements called every pill stretched.
    const range = document.createRange();
    range.selectNodeContents(el);
    const style = getComputedStyle(el);
    const inside = range.getBoundingClientRect().width
      + parseFloat(style.paddingInlineStart) + parseFloat(style.paddingInlineEnd);
    if (inside && r.width - inside > 80) {
      out.stretched.push({ what: label(el), w: Math.round(r.width), content: Math.round(inside) });
    }
  }

  // A line of prose longer than about 80 characters is scanned and lost rather than read. 760px is
  // roughly that at the 14px body size, so this only catches the ones that are plainly too long.
  for (const el of document.querySelectorAll('#main :is(p, li)')) {
    if (!el.getClientRects().length) continue;
    const words = el.textContent.trim();
    if (words.length < 90) continue;
    const w = el.getBoundingClientRect().width;
    if (w > 760) out.tooLong.push({ what: words.slice(0, 40), w: Math.round(w) });
  }

  // A text box wider than a sentence is a promise the answer is long. 34rem is the cap ui.css sets.
  for (const el of document.querySelectorAll('#main :is(input, select)')) {
    const w = el.getBoundingClientRect().width;
    if (w > 545) out.tooWide.push({ what: el.name || el.id || el.type, w: Math.round(w) });
  }
  // A press meant for the primary action must not be able to land on the destructive one. No
  // number is given for "not adjacent", so this asks for 24px of clear space, about the width of
  // one target (ui-ux-laws, Fitts).
  const primary = [...document.querySelectorAll('.hw-button--primary')];
  for (const bad of document.querySelectorAll('.hw-button--destructive')) {
    const a = bad.getBoundingClientRect();
    for (const good of primary) {
      // Only within one group. The primary at the foot of a table row and the destructive at the
      // head of the next are 17px apart by the nature of rows, and the rule between them says they
      // belong to different things; what matters is two actions offered together.
      if (bad.closest('tr') !== good.closest('tr')) continue;
      const b = good.getBoundingClientRect();
      const gapX = Math.max(a.left - b.right, b.left - a.right);
      const gapY = Math.max(a.top - b.bottom, b.top - a.bottom);
      const gap = Math.max(gapX, gapY);
      if (gap < 24) {
        out.tooClose.push({ destructive: label(bad), primary: label(good), gap: Math.round(gap) });
      }
    }
  }

  // What of a control can actually be seen: its box cut to every ancestor that clips. A row scrolled
  // out of sight inside a table's own frame still reports where it would be, which is on top of
  // whatever sits below the frame, and was reported as overlapping the next section's Download PDF
  // (courses/1/progress at 1024, 2026-09-23) when nothing on the screen overlapped anything.
  const visible = (el) => {
    let r = el.getBoundingClientRect();
    let box = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    for (let p = el.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (s.overflowX === "visible" && s.overflowY === "visible") continue;
      const c = p.getBoundingClientRect();
      box = { left: Math.max(box.left, c.left), top: Math.max(box.top, c.top),
        right: Math.min(box.right, c.right), bottom: Math.min(box.bottom, c.bottom) };
    }
    return { ...box, width: Math.max(0, box.right - box.left), height: Math.max(0, box.bottom - box.top) };
  };
  const boxes = controls.map((el) => ({ el, r: visible(el) }))
    .filter((b) => b.r.width > 8 && b.r.height > 8);
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
      const hh = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      // The sticky action bar sits over the form while it is stuck, which is the point of it.
      if (a.el.closest('.hw-sticky') || b.el.closest('.hw-sticky')) continue;
      if (w > 4 && hh > 4) out.overlaps.push({ a: label(a.el), b: label(b.el),
        by: Math.round(Math.min(w, hh)) });
    }
  }
  out.tinyText = out.tinyText.slice(0, 6);
  out.overlaps = out.overlaps.slice(0, 6);
  out.tooClose = out.tooClose.slice(0, 6);
  out.tooLong = out.tooLong.slice(0, 6);
  out.stretched = out.stretched.slice(0, 6);
  return out;
})()`;

await send("Runtime.enable");
await send("Page.enable");
await send("Page.navigate", { url: BASE });
await sleep(2500);
await evaluate(`fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({username:'aokonkwo', password:'herewise-dev-pass'})}).then(r=>r.status)`);
await send("Page.navigate", { url: BASE });
await sleep(3000);

const findings = [];
let exempt = 0;
for (const [width, height] of WIDTHS) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  for (const route of ROUTES) {
    thrown.length = 0;
    await evaluate(`location.hash = '#/${route}'`);
    await sleep(route.startsWith("device") && route !== "device/usb" ? 2200 : 900);
    if (width === 1366 || width === 1024) {
      const png = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
      if (png?.data) writeFileSync(join(OUT, `${width}-${route.replace(/\//g, "-")}.png`),
        Buffer.from(png.data, "base64"));
    }
    const seen = await evaluate(MEASURE);
    if (!seen) continue;
    const trouble = {};
    if (seen.overflowX > 2) trouble.overflowX = seen.overflowX;
    const small = seen.tooSmall.filter((s) => !s.inline);
    if (small.length) trouble.tooSmall = small.slice(0, 6);
    exempt += seen.tooSmall.filter((s) => s.inline).length;
    if (seen.tinyText.length) trouble.tinyText = seen.tinyText;
    if (seen.overhang.length) trouble.overhang = seen.overhang.slice(0, 5);
    if (seen.tooWide.length) trouble.tooWide = seen.tooWide.slice(0, 5);
    if (seen.overlaps.length) trouble.overlaps = seen.overlaps;
    if (seen.tooClose.length) trouble.tooClose = seen.tooClose;
    if (seen.tooLong.length) trouble.tooLong = seen.tooLong;
    if (seen.stretched.length) trouble.stretched = seen.stretched;
    if (thrown.length) trouble.threw = thrown.slice(0, 1);
    // A link in a sentence, a control under the action bar and one inside a sideways-scrolling
    // frame are counted, not reported: none of them is something to fix.
    if (Object.keys(trouble).length) findings.push({ width, route, ...trouble });
  }
}
writeFileSync(join(OUT, "layout.json"), JSON.stringify(findings, null, 2));

// Three planted faults, because a sweep that reports nothing is worth nothing until it has been
// shown to report something. A 12px button, a box wider than the window, and two buttons laid over
// each other: if the measurements miss any, every clean result above is meaningless. The third was
// added when the overlap check was changed to measure only what a scrolling frame lets be seen
// (2026-09-23), so that change is proved not to have blinded it.
let proof = "not run";
if (PROVE) {
  await send("Emulation.setDeviceMetricsOverride",
    { width: 1366, height: 850, deviceScaleFactor: 1, mobile: false });
  await evaluate(`location.hash = '#/today'`);
  await sleep(900);
  const caught = await evaluate(`(() => {
    const main = document.getElementById('main');
    const tiny = document.createElement('button');
    tiny.textContent = 'x';
    tiny.style.cssText = 'width:12px;height:12px;padding:0;min-height:0;position:relative;z-index:9';
    const wide = document.createElement('div');
    wide.style.cssText = 'width:3000px;height:8px';
    const under = document.createElement('button');
    under.textContent = 'planted under';
    under.style.cssText = 'position:relative;width:120px;height:40px';
    const over = document.createElement('button');
    over.textContent = 'planted over';
    over.style.cssText = 'position:relative;width:120px;height:40px;margin-top:-30px;display:block';
    main.append(tiny, wide, under, over);
    // Into view, because the hit test asks what a press at four points would activate and a point
    // outside the window is not a fault. Appended to the end of a page taller than the window, the
    // planted button sat below the fold and the proof reported itself missed.
    tiny.scrollIntoView({ block: 'center' });
    const box = tiny.getBoundingClientRect();
    return { added: true, onScreen: box.top > 0 && box.bottom < window.innerHeight };
  })()`);
  const seen = caught ? await evaluate(MEASURE) : null;
  const foundTiny = !!seen && seen.tooSmall.some((s) => s.what === "x" && !s.inline);
  const foundWide = !!seen && seen.overflowX > 100;
  const foundOverlap = !!seen && seen.overlaps.some((o) =>
    [o.a, o.b].some((x) => String(x).includes("planted under")) && [o.a, o.b].some((x) => String(x).includes("planted over")));
  proof = foundTiny && foundWide && foundOverlap
    ? `all three planted faults were found${caught?.onScreen ? "" : " (the button was off screen)"}`
    : `MISSED: ${[!foundTiny && "the 12px button", !foundWide && "the page overflow",
      !foundOverlap && "the two overlapping buttons"].filter(Boolean).join(" and ")}`;
}

console.log(JSON.stringify({ port: PORT, widths: WIDTHS.map((w) => w[0]), routes: ROUTES.length,
  findings: findings.length, exempt_by_rule: exempt, findings_by_width: Object.fromEntries(WIDTHS.map(([w]) =>
    [w, findings.filter((f) => f.width === w).length])), proof,
  detail: findings.slice(0, 40) }, null, 2));
ws.close();
chrome.kill();
try { rmSync(profile, { recursive: true, force: true }); } catch {}
process.exit(proof.startsWith("MISSED") ? 2 : findings.length ? 1 : 0);
