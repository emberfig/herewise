// Walk every screen in the app and report anything that renders an error state, leaks a null or
// an undefined into the page, or throws.
//
// Run, with scripts/dev_server.py serving the demo register:
//   node scripts/walk_screens.mjs [port]
//
// Give it the port the development server is on. The default is 8000, which is also the port the
// installed Herewise takes, so a walk started while that is running checks the installed build
// against somebody's real register and reports a clean sweep of code that was never loaded
// (2026-09-22). It prints the port it used, and refuses one it cannot reach.
//
// No dependencies: Node 22 or later has WebSocket built in, and any Chromium will do (Playwright's
// cached copy works), the same approach as scripts/measure_sheet.mjs.
//
// It exists because two whole classes of fault only appear when a screen is actually rendered
// against real data: a contract field named differently from the guess (`cancelled` against
// `cancelled_at`), and a conditional child the DOM stringifies into the word "null".
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1208", "chrome-win64", "chrome.exe");
const PORT = 9444;
const APP_PORT = process.argv[2] || "8000";
const BASE = `http://127.0.0.1:${APP_PORT}`;
const ROUTES = [
  "today", "pull", "unassigned", "corrections", "courses", "courses/1/sheet", "courses/1/setup",
  "courses/1/classes", "courses/1/students", "courses/1/percentages", "courses/1/eligibility",
  "courses/1/progress", "courses/1/groups", "courses/4/groups", "courses/4/sheet", "courses/4/classes",
  "courses/4/percentages", "classes/27", "classes/1", "students", "students/5", "levels",
  "levels/2/import", "excusals", "enrolment", "live", "device", "device/connection", "device/admins",
  "device/push", "device/unmatched", "device/usb", "device/unlock", "device/clear",
  "settings", "settings/accounts", "settings/roles", "settings/activity", "settings/backup",
  "settings/about",
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "hw-walk-"));
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--headless=new", "--window-size=1366,900", "--no-first-run", "--no-default-browser-check",
  "--disable-component-update", "about:blank"], { stdio: "ignore" });

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
const consoleErrors = [];
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg.result); waiting.delete(msg.id); }
  if (msg.method === "Runtime.exceptionThrown") {
    consoleErrors.push(msg.params.exceptionDetails.exception?.description
      || msg.params.exceptionDetails.text);
  }
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

await send("Runtime.enable");
await send("Page.enable");
await send("Page.navigate", { url: BASE });
await sleep(2500);
await evaluate(`fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({username:'aokonkwo', password:'herewise-dev-pass'})}).then(r=>r.status)`);
await send("Page.navigate", { url: BASE });
await sleep(3000);

// Kept, not cleared: a module that fails to parse throws once, at load, and the loop below used to
// wipe that before looking at anything.
const atLoad = consoleErrors.slice();

const problems = [];
if (atLoad.length) problems.push({ route: "(loading the app)", failure: null, nulls: false,
  blank: false, threw: atLoad.slice(0, 2) });
for (const route of ROUTES) {
  consoleErrors.length = 0;
  await evaluate(`location.hash = '#/${route}'`);
  await sleep(route.startsWith("device") && route !== "device/usb" ? 3000 : 1400);
  const seen = await evaluate(`(() => {
    const bad = document.querySelector('.hw-state[data-tone="failure"]');
    return { title: document.title,
             failure: bad ? bad.querySelector('.hw-state__heading')?.textContent : null,
             // Did anything render at all? A SyntaxError in a module means the app never boots,
             // and every check below it then reads clean because there is nothing to find. One
             // duplicated function in ui.js blanked all 34 screens and this walk said "no
             // problems" (2026-09-22). The rail, the top bar and the page region are the shell.
             rendered: Boolean(document.querySelector('.hw-rail') && document.getElementById('main'))
               && document.body.innerText.trim().length > 60,
             nulls: document.body.innerText.includes('nullnull')
               || /\bundefined\b/.test(document.body.innerText) };
  })()`);
  if (seen?.failure || seen?.nulls || !seen?.rendered || consoleErrors.length) {
    problems.push({ route, failure: seen?.failure ?? null, nulls: seen?.nulls ?? false,
      blank: !seen?.rendered, threw: consoleErrors.slice(0, 2) });
  }
}
console.log(JSON.stringify({ port: APP_PORT, checked: ROUTES.length, problems }, null, 2));
ws.close();
chrome.kill();
// Chrome holds its profile for a moment after being killed, so cleanup is allowed to fail.
try { rmSync(profile, { recursive: true, force: true }); } catch {}
process.exit(problems.length ? 1 : 0);
