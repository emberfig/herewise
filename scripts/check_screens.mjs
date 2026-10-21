// The screen checks, in one pass over every route of the demo register:
//
//   accessibility  axe-core 4.13.0 (scripts/vendor, MPL-2.0, used here only and never shipped), WCAG
//                  2.0, 2.1 and 2.2 A and AA rules, in the light theme and the dark one. Two faults
//                  are planted for it first, and the run stops if it does not find them, so a
//                  harness that is not running can never read as a clean screen
//   speed          time from a route change to its finished screen, at 1x and at 4x CPU slowdown,
//                  and the Event Timing of real clicks and key presses on the screens that filter or
//                  search, the span INP measures (docs/COMPONENT-GUIDE.md: under 200 ms at 1x and 4x).
//                  Each interaction is done twice and the second is the one measured, and the app's
//                  own processing time is reported beside the wait, because the first interaction
//                  after a route loads is charged the browser's own first frame
//   pictures       a full-page screenshot of every route, for the Checklist Design audits
//
// Run, with scripts/dev_server.py serving the demo register:
//   node scripts/check_screens.mjs [out-folder] [port]
//
// The port defaults to 8000, which is also the port the installed Herewise takes. A run started
// while that is running checks the installed build against somebody's real register: it reported
// five interactions "missing" because that register has no demo courses to filter (2026-09-22). It
// prints the port it used.
//
// No dependencies beyond Node 22 and a Chromium (Playwright's cached copy), as scripts/walk_screens.mjs.
// Check the machine is idle first: the load before the run is printed with the results, because a
// busy machine slows every number here and the numbers are only comparable at rest.
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const AXE = readFileSync(join(HERE, "vendor", "axe-core-4.13.0", "axe.min.js"), "utf8");
const CHROME = join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1208", "chrome-win64", "chrome.exe");
const OUT = process.argv[2] || join(tmpdir(), "herewise-screen-checks");
const PORT = 9445;
const APP_PORT = process.argv[3] || "8000";
const BASE = `http://127.0.0.1:${APP_PORT}`;
const ROUTES = [
  "today", "pull", "unassigned", "corrections", "courses", "courses/1/sheet", "courses/1/setup",
  "courses/1/classes", "courses/1/students", "courses/1/percentages", "courses/1/eligibility",
  "courses/1/progress", "courses/1/groups", "courses/4/groups", "courses/4/sheet", "courses/4/classes",
  "classes/27", "classes/1", "students", "students/5", "levels",
  "levels/2/import", "excusals", "enrolment", "device", "device/connection", "device/admins",
  "device/push", "device/unmatched", "device/usb", "device/unlock", "device/clear",
  "settings", "settings/accounts", "settings/roles", "settings/activity", "settings/backup",
  "settings/about",
];
// Real input on the controls that change a screen without saving anything.
const INTERACTIONS = [
  { route: "classes/1", what: "a count filter", click: '[data-action^="filter-"]:nth-of-type(2)' },
  { route: "classes/1", what: "typing in the register search", type: 'input[type="search"]', text: "ade" },
  { route: "courses", what: "typing in the course filter", type: "#courses-filter", text: "pct" },
  { route: "courses", what: "switching the view", click: '[data-action^="view-"]:not([aria-pressed="true"])' },
  { route: "courses/1/percentages", what: "a status filter", click: '[data-action^="filter-"]:nth-of-type(2)' },
  { route: "courses/1/percentages", what: "typing a new pass mark", type: 'input[type="number"]', text: "5" },
  { route: "students", what: "typing a student search", type: 'input[type="search"]', text: "ok" },
];
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const load = (() => {
  try {
    return Number(execFileSync("powershell", ["-NoProfile", "-Command",
      "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
    { encoding: "utf8" }).trim());
  } catch { return null; }
})();

mkdirSync(join(OUT, "light"), { recursive: true });
mkdirSync(join(OUT, "dark"), { recursive: true });
const profile = mkdtempSync(join(tmpdir(), "hw-checks-"));
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--headless=new", "--window-size=1366,900", "--no-first-run", "--no-default-browser-check",
  "--disable-component-update",
  "--disable-features=AIPageContentAgent,OptimizationHints,OptimizationGuideModelDownloading,Translate",
  "about:blank"], { stdio: "ignore" });

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
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
  const msg = JSON.parse(event.data);
  if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg.result ?? msg.error); waiting.delete(msg.id); }
  if (msg.method === "Runtime.exceptionThrown") thrown.push(msg.params.exceptionDetails.text);
});
const send = (method, params = {}) => new Promise((resolve) => {
  const n = ++id;
  waiting.set(n, resolve);
  ws.send(JSON.stringify({ id: n, method, params }));
});
const evaluate = async (expression) => {
  const out = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  return out?.result?.value;
};

// Finished means: a heading is up, nothing in the page region is still loading, and it has held
// still for two checks in a row.
const READY = `(() => new Promise((resolve) => {
  const main = document.getElementById('main');
  const t0 = window.__navStart;
  let calm = 0;
  const tick = () => {
    const done = main && main.querySelector('h1') && !main.querySelector('[aria-busy="true"]');
    calm = done ? calm + 1 : 0;
    if (calm >= 2) return resolve(Math.round(performance.now() - t0 - 10));
    if (performance.now() - t0 > 20000) return resolve(-1);
    setTimeout(tick, 5);
  };
  tick();
}))()`;

async function go(route) {
  await evaluate(`window.__navStart = performance.now(); location.hash = '#/${route}'`);
  return evaluate(READY);
}

async function scheme(dark) {
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: dark ? "dark" : "light" }] });
}

async function axe() {
  const found = await evaluate(`(async () => {
    if (!window.axe) { ${AXE}; }
    const r = await axe.run(document, { runOnly: { type: 'tag', values: ${JSON.stringify(WCAG)} },
                                        resultTypes: ['violations'] });
    return r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help,
      nodes: v.nodes.length, where: v.nodes.slice(0, 3).map((n) => n.target.join(' ')),
      summary: v.nodes[0]?.failureSummary?.split('\\n').slice(0, 3).join(' ') }));
  })()`);
  return found || [];
}

async function screenshot(file) {
  const height = await evaluate("Math.min(document.documentElement.scrollHeight, 6000)");
  await send("Emulation.setDeviceMetricsOverride", { width: 1366, height, deviceScaleFactor: 1, mobile: false });
  await sleep(250);
  const shot = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(file, Buffer.from(shot.data, "base64"));
  await send("Emulation.setDeviceMetricsOverride", { width: 1366, height: 900, deviceScaleFactor: 1, mobile: false });
}

async function center(selector) {
  return evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null; el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect();
    el.focus?.(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
}

async function press(point, step) {
  if (step.click) {
    for (const type of ["mousePressed", "mouseReleased"]) {
      await send("Input.dispatchMouseEvent", { type, x: point.x, y: point.y, button: "left", clickCount: 1 });
    }
    return;
  }
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: point.x, y: point.y, button: "left", clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: point.x, y: point.y, button: "left", clickCount: 1 });
  for (const ch of step.text) {
    await send("Input.dispatchKeyEvent", { type: "keyDown", key: ch, text: ch });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key: ch });
    await sleep(60);
  }
}

// The interaction is done twice and only the second is measured. The first one after a route has
// loaded is charged the browser's own first frame: on 2026-09-21 the Courses filter read 232 ms at
// 1x with 0 ms of the app's own processing in it, and 56 ms at 4x, and on a repeat the first round
// was 176 ms and every round after it 32 ms. Event Timing measures to the next paint, so a number
// with no processing behind it is the harness, not the screen. Both are reported now: worst_ms is
// what a person waits, worst_processing_ms is what this app's own handlers cost.
async function measureInteraction(step) {
  await go(step.route);
  await sleep(400);
  const warm = await center(step.click || step.type);
  if (!warm) return { route: step.route, what: step.what, missing: true };
  await press(warm, step);
  await sleep(600);

  await go(step.route);
  await sleep(400);
  await evaluate(`window.__events = []; new PerformanceObserver((list) => { for (const e of list.getEntries())
    window.__events.push({ name: e.name, duration: e.duration,
      processing: e.processingEnd - e.processingStart }); })
    .observe({ type: 'event', durationThreshold: 16, buffered: false }); true`);
  const point = await center(step.click || step.type);
  if (!point) return { route: step.route, what: step.what, missing: true };
  await press(point, step);
  await sleep(1200);
  const events = (await evaluate("window.__events")) || [];
  const worst = events.reduce((m, e) => Math.max(m, e.duration), 0);
  const worstProcessing = events.reduce((m, e) => Math.max(m, e.processing), 0);
  return { route: step.route, what: step.what, events: events.length,
    worst_ms: events.length ? Math.round(worst) : "under 16",
    worst_processing_ms: Math.round(worstProcessing) };
}

await send("Runtime.enable");
await send("Page.enable");
await send("Page.navigate", { url: BASE });
await sleep(2500);
await evaluate(`fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({username:'aokonkwo', password:'herewise-dev-pass'})}).then(r=>r.status)`);
await send("Page.navigate", { url: BASE });
await sleep(3000);

// A control before any result is believed: a screen with nothing wrong and a harness that is not
// running read the same. Two faults axe certainly knows are put on the page, and the run stops if
// it does not find them (studio rule: a control that cannot succeed is not a control).
const control = await evaluate(`(async () => {
  if (!window.axe) { ${AXE}; }
  const box = document.createElement('div');
  box.innerHTML = '<img src="data:,x"><input type="text">';
  document.body.append(box);
  const r = await axe.run(box, { runOnly: { type: 'tag', values: ${JSON.stringify(WCAG)} },
                                 resultTypes: ['violations'] });
  box.remove();
  return r.violations.map((v) => v.id);
})()`);
if (!control || !control.includes("image-alt") || !control.includes("label")) {
  console.error("axe-core did not report the two faults planted for it:", control);
  ws.close(); chrome.kill();
  process.exit(2);
}

const results = {};
for (const dark of [false, true]) {
  await scheme(dark);
  for (const route of ROUTES) {
    thrown.length = 0;
    const ms = await go(route);
    await sleep(route.startsWith("device") && route !== "device/usb" ? 2500 : 300);
    const entry = results[route] ??= { route };
    if (!dark) {
      entry.ready_ms_1x = ms;
      await screenshot(join(OUT, "light", `${route.replaceAll("/", "_")}.png`));
    } else {
      await screenshot(join(OUT, "dark", `${route.replaceAll("/", "_")}.png`));
    }
    entry[dark ? "axe_dark" : "axe_light"] = await axe();
    if (thrown.length) entry.threw = [...thrown];
  }
}

await scheme(false);
const interactions = { "1x": [], "4x": [] };
for (const rate of [1, 4]) {
  await send("Emulation.setCPUThrottlingRate", { rate });
  if (rate === 4) {
    for (const route of ROUTES) results[route].ready_ms_4x = await go(route);
  }
  for (const step of INTERACTIONS) interactions[`${rate}x`].push(await measureInteraction(step));
}
await send("Emulation.setCPUThrottlingRate", { rate: 1 });

const report = { load_before_percent: load, out: OUT, routes: Object.values(results), interactions };
writeFileSync(join(OUT, "report.json"), JSON.stringify(report, null, 2));
const violations = report.routes.flatMap((r) => [...r.axe_light, ...r.axe_dark].map((v) => `${r.route}: ${v.id}`));
console.log(JSON.stringify({
  port: APP_PORT,
  load_before_percent: load,
  axe_violations: [...new Set(violations)],
  slowest_ready_1x: [...report.routes].sort((a, b) => b.ready_ms_1x - a.ready_ms_1x).slice(0, 5).map((r) => `${r.route} ${r.ready_ms_1x} ms`),
  slowest_ready_4x: [...report.routes].sort((a, b) => b.ready_ms_4x - a.ready_ms_4x).slice(0, 5).map((r) => `${r.route} ${r.ready_ms_4x} ms`),
  interactions,
  threw: report.routes.filter((r) => r.threw).map((r) => `${r.route}: ${r.threw[0]}`),
  report: join(OUT, "report.json"),
}, null, 2));
ws.close();
chrome.kill();
try { rmSync(profile, { recursive: true, force: true }); } catch {}
