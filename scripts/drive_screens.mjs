// Press the buttons. Everything else checks that a screen renders; this checks that it does what
// it says when somebody uses it.
//
//   node scripts/drive_screens.mjs <port>
//
// Point it at scripts/dev_server.py with the demo register. It works through the actions added
// after two real runs, each one something a lecturer asked for and none of it reachable by loading
// a route: deleting a course from its own settings, deleting a cancelled class from its row,
// adding one student by hand through the preview, Device explaining what to do when the
// register and the terminal disagree, reopening an ended class from its register, and choosing
// Dark and then System from the account menu.
//
// It exists because walk_screens.mjs loads every route and check_layout.mjs measures every width,
// and neither would have noticed that New course led nowhere: the link rendered, and nothing
// pressed it (2026-09-21). It makes and removes its own throwaway course, class and student, and
// uses a fresh matric number each run so a second run is not testing the first run's leftovers.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = process.argv[2] || "8014";
const BASE = `http://127.0.0.1:${PORT}`;
const CHROME = join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1208", "chrome-win64", "chrome.exe");
const DEBUG = 9457;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "hw-drive-"));
const chrome = spawn(CHROME, [`--remote-debugging-port=${DEBUG}`, `--user-data-dir=${profile}`,
  "--headless=new", "--window-size=1366,900", "--no-first-run", "--no-default-browser-check",
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
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m.result ?? m.error); waiting.delete(m.id); }
  if (m.method === "Runtime.exceptionThrown") thrown.push(m.params.exceptionDetails.text);
});
const send = (method, params = {}) => new Promise((res) => {
  const n = ++id; waiting.set(n, res); ws.send(JSON.stringify({ id: n, method, params }));
});
const run = async (expression) => (await send("Runtime.evaluate",
  { expression, awaitPromise: true, returnByValue: true }))?.result?.value;

// A fresh matric number each run: the first run left ZZZ/24/9001 on the course, so the
// second one previewed "already on it" and read as a failure of the screen.
const MATRIC = `ZZZ/24/${String(Date.now()).slice(-4)}`;
const failures = [];
const check = (ok, what, extra = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${extra ? `: ${extra}` : ""}`);
  if (!ok) failures.push(what);
};

await send("Runtime.enable");
await send("Page.navigate", { url: BASE });
await sleep(2500);
await run(`fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({username:'aokonkwo', password:'herewise-dev-pass'})}).then(r=>r.status)`);
await send("Page.navigate", { url: BASE });
await sleep(3000);

const go = async (route, wait = 2200) => { await run(`location.hash = '#/${route}'`); await sleep(wait); };
const press = async (text, within = "body") => run(`(() => {
  const root = document.querySelector(${JSON.stringify(within)});
  const el = [...root.querySelectorAll('button, a')]
    .find((b) => b.textContent.trim().toLowerCase().startsWith(${JSON.stringify(text.toLowerCase())}));
  if (!el) return false;
  el.click();
  return true;
})()`);

// -- 1. a course made and deleted from its own settings -------------------------------------------
const made = await run(`fetch('/api/courses', {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({level_id: 2, code: 'ZZZ 999', title: 'Made by the check'})})
  .then(r => r.json())`);
check(Boolean(made?.id), "a throwaway course was made to delete", made?.code);

await go(`courses/${made.id}/setup`, 2800);
const offered = await run(`(() => {
  const heads = [...document.querySelectorAll('h2')].map((h) => h.textContent);
  const button = [...document.querySelectorAll('button')]
    .find((b) => b.textContent.trim() === 'Delete this course');
  return { heads, has: Boolean(button), disabled: button ? button.disabled : null };
})()`);
check(offered.has && offered.disabled === false,
  "its settings offer Delete this course, enabled because nothing is recorded against it",
  JSON.stringify(offered.heads.slice(-1)));

check(await press("Delete this course"), "the delete dialog opens");
await sleep(600);
check(await press("Delete it", "dialog"), "the dialog's own Delete it can be pressed");
await sleep(2500);
// Asked of the backend, not of the page: the toast confirming the delete carries the course code,
// so "is the code on the screen" answers yes for the wrong reason.
const gone = await run(`(async () => ({ hash: location.hash,
  codes: (await (await fetch('/api/courses')).json()).map((c) => c.code) }))()`);
check(gone.hash.includes("courses") && !gone.codes.includes("ZZZ 999"),
  "it is gone and the screen went to Courses", JSON.stringify(gone));

// -- 2. a cancelled class deleted from its row ------------------------------------------------------
const cls = await run(`fetch('/api/sessions', {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({course_id: 1, date: '2026-09-14', start_time: '07:00', end_time: '07:30',
                        kind: 'manual'})}).then(r => r.json())`);
await run(`fetch('/api/sessions/${cls.id}/cancel', {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify({note: 'Made by the check.'})})
  .then(r => r.status)`);
await go("courses/1/classes", 2600);
const row = await run(`(() => {
  const cells = [...document.querySelectorAll('tbody tr')]
    .filter((tr) => tr.textContent.includes('07:00'));
  return { rows: cells.length,
           hasDelete: cells.some((tr) => [...tr.querySelectorAll('button')]
             .some((b) => b.textContent.trim() === 'Delete')) };
})()`);
check(row.rows === 1 && row.hasDelete, "the cancelled class shows a Delete on its row",
  JSON.stringify(row));

await run(`(() => {
  const tr = [...document.querySelectorAll('tbody tr')].find((r) => r.textContent.includes('07:00'));
  [...tr.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Delete').click();
})()`);
await sleep(600);
check(await press("Delete it", "dialog"), "its dialog can be pressed");
await sleep(2500);
check(!(await run(`document.body.innerText.includes('07:00')`)),
  "the class is off the list");

// -- 3. adding one student by hand ------------------------------------------------------------------
await go("courses/1/students", 2600);
check(await press("Add students"), "Add students opens");
await sleep(700);
const ways = await run(`(() => {
  const box = document.querySelector('dialog');
  return { title: box?.querySelector('h2, .hw-dialog__title')?.textContent,
           tabs: [...box.querySelectorAll('.hw-toggle__button')].map((b) => b.textContent),
           fields: [...box.querySelectorAll('.hw-field__label')].map((l) => l.textContent) };
})()`);
check((ways.tabs || []).length === 2 && (ways.fields || []).includes("Matric number"),
  "it offers one student or a list, with real fields", JSON.stringify(ways));

await run(`(() => {
  const box = document.querySelector('dialog');
  const value = (label, text) => {
    const field = [...box.querySelectorAll('.hw-field')]
      .find((f) => f.querySelector('.hw-field__label')?.textContent.startsWith(label));
    const input = field.querySelector('input, textarea');
    input.value = text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  };
  value('Matric number', '${MATRIC}');
  value('Full name', 'CHECKER Adaeze');
  value('Level', '300');
})()`);
check(await press("Preview", "dialog"), "Preview can be pressed");
await sleep(2000);
// The row the preview drew, not the dialog's prose: the body copy says "created" whatever happens,
// so matching on that passes even when the preview failed.
const plan = await run(`(() => {
  const box = document.querySelector('dialog');
  const row = [...box.querySelectorAll('tbody tr')]
    .find((tr) => tr.textContent.includes('${MATRIC}'));
  const commit = [...box.querySelectorAll('button')]
    .find((b) => b.textContent.trim().startsWith('Add '));
  return { row: row ? row.innerText.replace(/\\s+/g, ' ') : null,
           commit: commit ? commit.textContent.trim() : null,
           reason: box.querySelector('.hw-reason')?.textContent || "" };
})()`);
check(Boolean(plan.row) && /new to Herewise/i.test(plan.row) && plan.commit === "Add 1 student",
  "the preview draws the student and the button says how many", JSON.stringify(plan));
check(!plan.reason.includes("Preview first"),
  "the reason under an enabled button is not still asking for a preview", plan.reason);

check(await press("Add ", "dialog"), "the commit button can be pressed");
await sleep(2500);
check(await run(`document.body.innerText.includes('${MATRIC}')`),
  "the student is on the course");

// -- 3b. and taking them off again from the sheet -----------------------------------------------------
// Asked for on 2026-09-24: "can i delete students on the sheets too just like we can add". The name
// on the sheet opens Edit, whose Remove hands over to the Students tab's own removal. It also takes
// this run's throwaway student back off the course.
await go("courses/1/sheet", 3500);
const opened = await run(`(() => {
  const row = [...document.querySelectorAll('hw-sheet .sheet__row[data-person]')]
    .find((r) => r.textContent.includes('${MATRIC}'));
  if (!row) return false;
  row.querySelector('[data-col="2"]').click();
  return true;
})()`);
await sleep(800);
check(opened && await run(`Boolean(document.querySelector('dialog[open]')?.textContent.includes('Remove from this course'))`),
  "the student's name on the sheet opens Edit, with Remove from this course");
check(await press("Remove from this course", "dialog[open]"), "Remove can be pressed");
await sleep(800);
check(await run(`/^Remove .* from PCT 201\\?$/.test(document.querySelector('dialog[open] h2, dialog[open] [class*=title]')?.textContent.trim() || '')`),
  "it opens the course's own removal, which asks why");
await run(`(() => {
  const note = document.querySelector('dialog[open] textarea');
  note.value = 'Added by the check, taken off by the check.';
  note.dispatchEvent(new Event('input', { bubbles: true }));
})()`);
check(await press("Remove from this course", "dialog[open]"), "the removal can be pressed");
await sleep(2500);
check(await run(`![...document.querySelectorAll('hw-sheet .sheet__row')].some((r) => r.textContent.includes('${MATRIC}'))`),
  "the student is off the sheet");

// -- 4. forgetting the fingerprint records -----------------------------------------------------------
await go("device", 3200);
check(await run(`document.body.innerText.includes('If this register and the terminal disagree')`),
  "Device explains when the two disagree");

// -- 4b. reopening an ended class for whoever had not scanned (2026-10-22) -------------------------
// Taken and ended through the API, then reopened from the class register's own button and ended
// again. Cancelled at the end so the throwaway class counts towards nothing: a reopened class is
// never deleted, because the reopening is a record like a correction.
const taken = await run(`fetch('/api/courses/2/live', {method:'POST', headers:{'Content-Type':'application/json'},
  body: '{}'}).then(r => r.json())`);
const takenId = taken?.register?.session?.id;
check(Boolean(takenId), "a class was taken live to reopen", taken?.error || "");
await run(`fetch('/api/live/${takenId}/end', {method:'POST', headers:{'Content-Type':'application/json'},
  body: '{}'}).then(r => r.status)`);
await go(`classes/${takenId}`, 2800);
check(await press("Reopen attendance"), "the ended class's register offers Reopen attendance");
await sleep(600);
check(await press("Reopen attendance", "dialog[open]"), "its dialog's Reopen attendance can be pressed");
await sleep(4000);
const reopened = await run(`(async () => ({ hash: location.hash,
  says: document.querySelector('.hw-page__subtitle')?.textContent || "",
  open: (await (await fetch('/api/live')).json()).open }))()`);
check(reopened.hash === "#/live" && reopened.open?.class_id === takenId && Boolean(reopened.open?.reopened_at)
  && reopened.says.includes("reopened"),
  "it went to Taking attendance, open again and saying so", JSON.stringify({ hash: reopened.hash, says: reopened.says }));
check(await press("End attendance"), "End attendance can be pressed on the reopened class");
await sleep(600);
check(await run(`document.querySelector('dialog[open] h2')?.textContent.endsWith('again?')`),
  "its End dialog says it is ending it again");
check(await press("End attendance", "dialog[open]"), "the dialog's End attendance can be pressed");
await sleep(4000);
check(await run(`document.body.innerText.includes('came in while it was reopened')`),
  "Attendance taken says how many came in while it was reopened");
await run(`fetch('/api/sessions/${takenId}/cancel', {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({note: 'Made by the check.'})}).then(r => r.status)`);

// -- 4c. light and dark, from the account menu (2026-10-22) -----------------------------------------
await go("today", 2500);
await run(`window.dispatchEvent(new CustomEvent('hw-account-menu'))`);
await sleep(600);
const pick = (value) => run(`(() => {
  const input = document.querySelector('dialog[open] input[name=appearance-menu][value=${value}]');
  if (!input) return false;
  input.click();
  return true;
})()`);
check(await pick("dark"), "the account menu offers Dark");
await sleep(1200);
const dark = await run(`(async () => ({ theme: document.documentElement.dataset.theme || null,
  saved: (await (await fetch('/api/appearance')).json()).theme }))()`);
check(dark.theme === "dark" && dark.saved === "dark", "Dark takes effect at once and is kept", JSON.stringify(dark));
check(await pick("system"), "System can be chosen again");
await sleep(1200);
const back = await run(`(async () => ({ theme: document.documentElement.dataset.theme || null,
  saved: (await (await fetch('/api/appearance')).json()).theme }))()`);
check(back.theme === null && back.saved === "system", "System leaves it to Windows again", JSON.stringify(back));
await run(`document.querySelector('dialog[open]')?.close()`);

// -- 5. setting up this computer's Ethernet (0.1.16) ------------------------------------------------
// Pressed only against `scripts/dev_server.py --fake-network`, and only when every adapter the
// server reports is named "(pretend)". Against anything else, Set up would ask this PC's Windows for
// administrator rights and, answered Yes, change this PC's Ethernet.
if (!process.argv.includes("--fake-network")) {
  console.log("[SKIP] the Ethernet setup: start the server and this script with --fake-network to press it");
} else {
  const net = await run(`fetch('/api/devices/1/diagnose').then((r) => r.json()).then((d) => d.network)`);
  const names = [...(net?.offer?.choices || []), ...(net?.set || [])].map((a) => a.name);
  if (!names.length || !names.every((n) => n.includes("(pretend)"))) {
    check(false, "the server is on the pretend network, so nothing here asks this PC's Windows",
      JSON.stringify(names));
  } else {
    await go("device/connection", 3000);
    if (!(await run(`Boolean(document.querySelector('[data-part=ethernet-offer]'))`))) {
      // Left set up by an earlier run: take it off first, through its own dialog.
      check(await press("Take it off"), "an earlier run's setup can be taken off");
      await sleep(600);
      check(await press("Take it off", "dialog[open]"), "its dialog's Take it off can be pressed");
      await sleep(3000);
    }
    check(await run(`Boolean(document.querySelector('[data-part=ethernet-offer]'))`),
      "the Connection check offers to set up the Ethernet");
    check(await press("Set up this computer's Ethernet"), "Set up can be pressed");
    await sleep(2500);
    // The pretend prompt answers No the first time a server asks, then Yes.
    const first = await run(`({
      declined: Boolean(document.querySelector('[data-part=ethernet-offer] [role=alert]')),
      byHand: [...document.querySelectorAll('[data-part=ethernet-offer] details')]
        .some((d) => d.open && d.textContent.startsWith('Do it by hand')) })`);
    if (first.declined) {
      check(first.byHand, "a No to Windows leaves the steps by hand open");
      check(await press("Set up this computer's Ethernet"), "Set up can be pressed again");
      await sleep(3000);
    }
    const after = await run(`({
      title: document.querySelector('[data-part=verdict] .hw-panel__title')?.textContent,
      focused: document.activeElement?.dataset.part || document.activeElement?.tagName,
      undo: document.body.innerText.includes("This computer's Ethernet") })`);
    check(after.title === "Every link is working" && after.focused === "verdict" && after.undo,
      "a Yes walks the chain again, clean, with focus on the answer and the undo offered",
      JSON.stringify(after));
  }
}

console.log(thrown.length ? `THREW: ${thrown.slice(0, 2).join(" | ")}` : "nothing was thrown");
console.log(failures.length ? `FAILED: ${failures.join("; ")}` : "Every screen did what it says.");
ws.close();
chrome.kill();
try { rmSync(profile, { recursive: true, force: true }); } catch {}
process.exit(failures.length ? 1 : 0);
