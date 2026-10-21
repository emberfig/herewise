// Measure the Living sheet gallery at a CPU slowdown, as docs/COMPONENT-GUIDE.md step 4 asks.
//
// Run, with the gallery served (python -m http.server 8765 --bind 127.0.0.1 --directory rollcall/static):
//   node scripts/measure_sheet.mjs [chrome.exe] [slowdown]
//
// No dependencies: Node 22 or later has WebSocket built in, and any Chromium will do (Playwright's cached
// copy works). Interactions are real key presses sent through the DevTools protocol, and their latency is
// read from the browser's Event Timing API, the same span INP measures: input delay, handlers and the
// next frame painted. Event Timing reports nothing under 16 ms, so "under 16" is a measurement, not a gap.

import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = process.argv[2] ||
  join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1208", "chrome-win64", "chrome.exe");
const SLOWDOWN = Number(process.argv[3] || 4);
// Optional CSS added to the page, to test one suspected cost at a time against the same presses.
const EXTRA_CSS = process.argv[4] ?? "";
const GALLERY = "http://127.0.0.1:8765/gallery/sheet.html";
const PORT = 9333;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), "hw-measure-"));
// Headless Chrome paints in software. HEADFUL=1 opens a real window (off screen) that paints with the GPU,
// which is what a lecturer's laptop does; compare the two before blaming the component for paint time.
const HEADFUL = process.env.HEADFUL === "1";
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  ...(HEADFUL ? ["--window-position=-2400,0", "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding", "--disable-background-timer-throttling"] : ["--headless=new"]),
  "--window-size=1366,768", "--no-first-run", "--no-default-browser-check", "--disable-component-update",
  // Chrome's own background work (a 199 ms AIPageContentAgent task showed up in a trace) is not the sheet's.
  "--disable-features=AIPageContentAgent,OptimizationHints,OptimizationGuideModelDownloading,Translate",
  "about:blank"], { stdio: "ignore" });

async function target() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not listening yet */ }
    await sleep(200);
  }
  throw new Error("Chrome did not open a debugging port.");
}

const ws = new WebSocket(await target());
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let seq = 0;
const pending = new Map();
const traceEvents = [];
let traceDone = null;
ws.addEventListener("message", (m) => {
  const msg = JSON.parse(m.data);
  if (msg.method === "Tracing.dataCollected") traceEvents.push(...msg.params.value);
  if (msg.method === "Tracing.tracingComplete") traceDone?.();
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  pending.set(id, (msg) => (msg.error ? reject(new Error(`${method}: ${msg.error.message}`)) : resolve(msg.result)));
  ws.send(JSON.stringify({ id, method, params }));
});
const run = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? "evaluation failed");
  return r.result.value;
};
const key = (k, code, keyCode) => Promise.all(["keyDown", "keyUp"].map((type) =>
  send("Input.dispatchKeyEvent", { type, key: k, code, windowsVirtualKeyCode: keyCode })));

// Background load has voided a whole session of numbers once, so every run states what it ran beside.
function cpuLoadPercent() {
  try {
    const out = execFileSync("powershell", ["-NoProfile", "-Command",
      "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
    { encoding: "utf8", timeout: 20000 });
    return Number(out.trim());
  } catch { return null; }
}
const loadBefore = cpuLoadPercent();

const median = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];
const p90 = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length * 0.9)];
const results = {};

try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1366, height: 768, deviceScaleFactor: 1, mobile: false });
  await send("Emulation.setCPUThrottlingRate", { rate: SLOWDOWN });

  // FIXTURES=sheet-12 runs a small sheet as a control: a stall that appears there is not about size.
  for (const fixture of (process.env.FIXTURES ?? "sheet-24,sheet-30").split(",")) {
    await send("Page.navigate", { url: `${GALLERY}?state=loading&panels=light` });
    await sleep(1500 * SLOWDOWN / 4 + 1000);
    // First render: set the data, then wait for the frame that paints it.
    const renders = await run(`(async () => {
      const extra = document.createElement("style");
      extra.textContent = ${JSON.stringify(EXTRA_CSS)};
      document.head.append(extra);
      const data = await (await fetch("fixtures/${fixture}.json")).json();
      const out = [];
      for (let i = 0; i < 5; i++) {
        const s = document.querySelector("hw-sheet");
        s.innerHTML = "";
        await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
        const t0 = performance.now();
        s.data = structuredClone(data);
        await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
        out.push(Math.round(performance.now() - t0));
      }
      window.__events = [];
      // What each key press did to the sheet's scroll position, matched to Event Timing by timestamp.
      window.__moves = new Map();
      const sc = document.querySelector("hw-sheet .sheet__scroller");
      document.addEventListener("keydown", (e) => {
        const before = [sc.scrollTop, sc.scrollLeft];
        requestAnimationFrame(() => window.__moves.set(Math.round(e.timeStamp),
          [Math.round(sc.scrollTop - before[0]), Math.round(sc.scrollLeft - before[1])]));
      }, true);
      new PerformanceObserver((list) => { for (const e of list.getEntries()) window.__events.push({ name: e.name, duration: e.duration, start: e.startTime,
        delay: e.processingStart - e.startTime, handlers: e.processingEnd - e.processingStart,
        paint: e.startTime + e.duration - e.processingEnd }); })
        .observe({ type: "event", durationThreshold: 16, buffered: false });
      document.querySelector("hw-sheet [tabindex='0']").focus();
      return { renders: out, elements: document.querySelector("hw-sheet").querySelectorAll("*").length };
    })()`);

    // Twenty arrow presses, down and right alternately, 150 ms apart: a person stepping through boxes.
    // TRACE=1 records them and prints which rendering steps took longest.
    const TRACE = process.env.TRACE === "1";
    if (TRACE) await send("Tracing.start", { categories: process.env.TRACE_CATEGORIES ?? "devtools.timeline,blink,disabled-by-default-devtools.timeline.invalidationTracking", transferMode: "ReportEvents" });
    // PRESSES=down or PRESSES=right separates vertical from horizontal movement.
    const PRESSES = process.env.PRESSES ?? "mixed";
    await sleep(2000);   // let load-time work finish before the first press
    for (let round = 0; round < 3; round++) {
      await run("(() => { const s = document.querySelector('hw-sheet'); s.moveTo(0, 3); })()");
      await sleep(500);
      for (let i = 0; i < 20; i++) {
        const right = PRESSES === "right" || (PRESSES === "mixed" && i % 2);
        await (right ? key("ArrowRight", "ArrowRight", 39) : key("ArrowDown", "ArrowDown", 40));
        await sleep(150);
      }
    }
    if (TRACE) {
      const done = new Promise((r) => { traceDone = r; });
      await send("Tracing.end");
      await done;
      const totals = {};
      for (const e of traceEvents) {
        if (e.ph !== "X" || !e.dur) continue;
        const t = (totals[e.name] ??= { count: 0, total_ms: 0, worst_ms: 0 });
        t.count += 1; t.total_ms += e.dur / 1000; t.worst_ms = Math.max(t.worst_ms, e.dur / 1000);
      }
      results.trace_layouts = traceEvents.filter((e) => e.name === "Layout" && e.dur > 5000)
        .sort((a, b) => b.dur - a.dur).slice(0, 5)
        .map((e) => ({ ms: Math.round(e.dur / 1000), ...e.args?.beginData, roots: e.args?.endData?.layoutRoots?.length }));
      // What the slowest layout ran inside: the enclosing events name who asked for it.
      const worst = traceEvents.filter((e) => e.name === "Layout" && e.dur).sort((a, b) => b.dur - a.dur)[0];
      results.trace_worst_layout_inside = worst ? traceEvents
        .filter((e) => e.ph === "X" && e.dur && e.tid === worst.tid && e.ts <= worst.ts && e.ts + e.dur >= worst.ts + worst.dur)
        .sort((a, b) => b.dur - a.dur).map((e) => `${e.name} ${Math.round(e.dur / 1000)} ms`) : [];
      results.trace_styles = traceEvents.filter((e) => e.name === "UpdateLayoutTree" && e.dur > 5000)
        .sort((a, b) => b.dur - a.dur).slice(0, 3).map((e) => ({ ms: Math.round(e.dur / 1000), elements: e.args?.elementCount }));
      const reasons = {};
      for (const e of traceEvents) {
        const d = e.args?.data;
        if (!e.name.includes("InvalidationTracking") || !d) continue;
        const why = `${e.name.replace("InvalidationTracking", "")}: ${d.reason ?? d.invalidationSet?.id ?? ""} ${d.nodeName ?? ""}`.trim();
        reasons[why] = (reasons[why] ?? 0) + 1;
      }
      results.trace_reasons = Object.entries(reasons).sort((a, b) => b[1] - a[1]).slice(0, 12);
      results.trace_top = Object.entries(totals).sort((a, b) => b[1].worst_ms - a[1].worst_ms).slice(0, 14)
        .map(([name, t]) => `${name}: worst ${t.worst_ms.toFixed(0)} ms, total ${t.total_ms.toFixed(0)} ms, ${t.count}x`);
    }
    const arrowEvents = await run(`window.__events.splice(0).filter((e) => e.name === 'keydown')
      .map((e) => ({ ...e, scrolled: window.__moves.get(Math.round(e.start)) ?? null }))`);
    const arrows = arrowEvents.map((e) => e.duration);
    const split = (k) => Math.round(median(arrowEvents.map((e) => e[k])));

    // Typing a filter, one character at a time, then clearing it.
    // Long animation frames catch work the component defers out of the input event, so moving the
    // cost to a later task cannot hide it.
    await run(`(() => { window.__loaf = []; new PerformanceObserver((l) => { for (const e of l.getEntries())
      window.__loaf.push(Math.round(e.duration)); }).observe({ type: "long-animation-frame" }); })()`);
    await run("document.querySelector('hw-sheet .sheet__filter').focus()");
    for (const ch of "okafor") {
      await send("Input.insertText", { text: ch });
      await sleep(250);
    }
    await key("Escape", "Escape", 27);
    await sleep(300);
    const typingEvents = await run("window.__events.splice(0)");
    const longFrames = await run("window.__loaf.splice(0)");
    const typing = typingEvents.map((e) => e.duration);

    results[fixture] = {
      elements: renders.elements,
      first_render_ms: renders.renders,
      headful: HEADFUL, arrow_keydowns_ms: arrows.map(Math.round),
      arrow_by_scroll: arrowEvents.map((e) => [Math.round(e.duration), e.scrolled]),
      arrow_slowest_split: [...arrowEvents].sort((a, b) => b.duration - a.duration).slice(0, 6)
        .map((e) => ({ ms: Math.round(e.duration), delay: Math.round(e.delay), handlers: Math.round(e.handlers), paint: Math.round(e.paint) })), arrow_keydowns_over_16ms: arrows.length, arrow_worst_ms: arrows.length ? Math.max(...arrows) : "under 16",
      arrow_median_of_reported_ms: arrows.length ? median(arrows) : "under 16",
      arrow_p90_of_reported_ms: arrows.length ? p90(arrows) : "under 16",
      arrow_median_split_ms: arrows.length ? { delay: split("delay"), handlers: split("handlers"), paint: split("paint") } : null,
      filter_events: typingEvents.map((e) => `${e.name} ${Math.round(e.duration)} (delay ${Math.round(e.delay)}, handlers ${Math.round(e.handlers)}, paint ${Math.round(e.paint)})`),
      filter_events_over_16ms: typing.length,
      filter_long_frames_ms: longFrames, filter_worst_ms: typing.length ? Math.max(...typing) : "under 16",
    };
  }
  console.log(JSON.stringify({ chrome: (await send("Browser.getVersion")).product, slowdown: SLOWDOWN,
    cpu_load_percent_before: loadBefore, cpu_load_percent_after: cpuLoadPercent(),
    extra_css: EXTRA_CSS || undefined, results }, null, 2));
} finally {
  ws.close();
  chrome.kill();
  await sleep(500);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome may still hold the profile; the OS temp cleaner takes it */ }
}
