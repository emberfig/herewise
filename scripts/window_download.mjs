// Drive the packaged window to press Download your data, over the DevTools protocol.
//
//   node scripts/window_download.mjs <app port> <debug port>
//
// Used by scripts/install_acceptance.py, which watches for Windows' own Save dialog afterwards.
// A download is the one thing no test can see: pywebview cancels every download in its window
// unless ALLOW_DOWNLOADS is set, and in build 0.1.0 pressing the button did nothing at all.
//
// The window is started against a scratch data folder with no account in it, so this signs the
// register up as it goes: setup, then sign in, then the Backup screen.
const [appPort, debugPort] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const out = { pressed: false };

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
      const page = list.find((t) => t.type === "page" && t.url.includes(`:${appPort}`));
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(500);
  }
  return null;
}

const url = await target();
if (!url) {
  out.error = "the window's page never appeared on the debugging port";
  console.log(JSON.stringify(out));
  process.exit(0);
}

const ws = new WebSocket(url);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const waiting = new Map();
ws.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id && waiting.has(message.id)) {
    waiting.get(message.id)(message.result ?? message.error);
    waiting.delete(message.id);
  }
});
const send = (method, params = {}) => new Promise((resolve) => {
  const n = ++id;
  waiting.set(n, resolve);
  ws.send(JSON.stringify({ id: n, method, params }));
});
const evaluate = async (expression) => (await send("Runtime.evaluate",
  { expression, awaitPromise: true, returnByValue: true }))?.result?.value;

await send("Runtime.enable");
await send("Page.enable");

out.setup = await evaluate(`(async () => {
  const status = await fetch('/api/setup/status').then((r) => r.json());
  if (!status.needs_setup) return 'already set up';
  const made = await fetch('/api/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'acceptance', display_name: 'Acceptance Run',
                           password: 'acceptance-pass-2026', academic_session: '2026/2027' }) });
  return made.status + '';
})()`);
out.signedIn = await evaluate(`fetch('/api/login', { method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'acceptance', password: 'acceptance-pass-2026' }) })
  .then((r) => r.status)`);

// The page booted before the account existed, so it is sitting on first-run setup and sends every
// route back there. It is loaded again now that there is a session, and only then pointed at the
// screen: a hash change on the setup screen goes straight back to setup.
await send("Page.navigate", { url: `http://127.0.0.1:${appPort}/` });
await sleep(6000);
await evaluate(`location.hash = '#/settings/backup'`);
await sleep(4000);

out.screen = await evaluate(`document.querySelector('#main h1')?.textContent || document.title`);
out.pressed = await evaluate(`(() => {
  const button = [...document.querySelectorAll('button')]
    .find((b) => /download your data/i.test(b.textContent || ''));
  if (!button) return false;
  button.click();
  return true;
})()`);

console.log(JSON.stringify(out));
ws.close();
