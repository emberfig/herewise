// Ask a running Herewise for every file it can produce, and check each one comes back whole.
//
//   node scripts/check_exports.mjs <port> [--setup]
//
// Point it at the packaged app, not at a source run. Excluding PIL from the PyInstaller build made
// every PDF export fail with ModuleNotFoundError while every PDF export in a source run worked,
// because reportlab imports PIL at the top of reportlab/lib/utils.py. A lecturer found it on Export
// PDF and saw "Internal Server Error" (2026-09-22). A test suite cannot see this and neither can a
// screen check: only the built program can.
//
// --setup signs a scratch register up first, for a packaged app started against an empty folder.
// Without it, sign in as the demo owner.
//
// Each export is asked for over the app's own HTTP, then checked: the status, the media type, the
// filename in Content-Disposition, and the first bytes of the body, because a 200 holding an HTML
// error page is still a failure.
const PORT = process.argv[2] || "8000";
const SETUP = process.argv.includes("--setup");
const BASE = `http://127.0.0.1:${PORT}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let cookie = "";
async function call(path, options = {}) {
  const answer = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { ...(options.headers || {}), ...(cookie ? { cookie } : {}) },
    redirect: "manual",
  });
  const set = answer.headers.getSetCookie?.() || [];
  if (set.length) cookie = set.map((line) => line.split(";")[0]).join("; ");
  return answer;
}

// A PDF starts %PDF, an xlsx is a zip so it starts PK, a CSV is text. Anything else is a page
// describing a failure.
const STARTS = { pdf: [0x25, 0x50, 0x44, 0x46], xlsx: [0x50, 0x4b, 0x03, 0x04] };

const failures = [];
function check(ok, what, detail = "") {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${detail ? `: ${detail}` : ""}`);
  if (!ok) failures.push(what);
}

async function ready() {
  for (let i = 0; i < 60; i++) {
    try {
      const answer = await fetch(`${BASE}/api/setup/status`);
      if (answer.ok) return await answer.json();
    } catch {}
    await sleep(1000);
  }
  return null;
}

const status = await ready();
if (!status) {
  console.log(`Nothing answering on ${BASE}. Start the app first.`);
  process.exit(2);
}

if (SETUP && status.needs_setup) {
  const made = await call("/api/setup", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: "checker", display_name: "Export Checker",
                           password: "check-exports-pass", academic_session: "2026/2027" }),
  });
  check(made.ok, "a scratch register was set up", String(made.status));
} else {
  const inn = await call("/api/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(SETUP
      ? { username: "checker", password: "check-exports-pass" }
      : { username: "aokonkwo", password: "herewise-dev-pass" }),
  });
  check(inn.ok, "signed in", String(inn.status));
}

// A register with nothing in it can still be asked for a sheet, so the ids are found rather than
// assumed, and an export nothing exists for is skipped rather than failed.
const courses = await (await call("/api/courses")).json().catch(() => []);
const course = Array.isArray(courses) && courses.length ? courses[0] : null;
let template = null;
if (course) {
  const summary = await (await call(`/api/courses/${course.id}/template`)).json().catch(() => null);
  template = summary?.id ?? summary?.template?.id ?? null;
}
if (!course) {
  console.log("No course in this register, so only the activity log can be exported.");
}
// A course split into groups (0.1.16) exports one group's sheet, or every group's in one file: a
// PDF of several sections and a workbook of several worksheets, both code the first course's
// single sheet never reaches.
// The list of courses does not carry their groups; one course asked for on its own does.
let grouped = null;
for (const c of Array.isArray(courses) ? courses : []) {
  const one = await (await call(`/api/courses/${c.id}`)).json().catch(() => null);
  if ((one?.groups || []).length) { grouped = one; break; }
}
let groupedTemplate = null;
if (grouped) {
  const summary = await (await call(`/api/courses/${grouped.id}/template`)).json().catch(() => null);
  groupedTemplate = summary?.id ?? summary?.template?.id ?? null;
} else {
  console.log("No course here is split into groups, so the group exports are not asked for.");
}

const wanted = [
  ["the activity log, CSV", "/api/audit/export", "csv"],
  ...(course ? [
    ["the eligibility list, PDF", `/api/courses/${course.id}/eligibility/export?format=pdf&variant=full`, "pdf"],
    ["the eligibility notice, PDF", `/api/courses/${course.id}/eligibility/export?format=pdf&variant=notice`, "pdf"],
    ["the eligibility list, Excel", `/api/courses/${course.id}/eligibility/export?format=xlsx&variant=full`, "xlsx"],
    ["attendance so far, PDF", `/api/courses/${course.id}/progress/export?format=pdf&variant=notice`, "pdf"],
    ["the at-risk list, PDF", `/api/courses/${course.id}/progress/export?format=pdf&variant=at_risk`, "pdf"],
    ["attendance so far, Excel", `/api/courses/${course.id}/progress/export?format=xlsx&variant=notice`, "xlsx"],
  ] : []),
  ...(template ? [
    ["the attendance sheet, PDF", `/api/templates/${template}/export?format=pdf`, "pdf"],
    ["the attendance sheet, Excel", `/api/templates/${template}/export?format=xlsx`, "xlsx"],
  ] : []),
  ...(groupedTemplate ? [
    ["one group's sheet, PDF", `/api/templates/${groupedTemplate}/export?format=pdf&group=${grouped.groups[0].id}`, "pdf"],
    ["every group's sheet, PDF", `/api/templates/${groupedTemplate}/export?format=pdf&group=all`, "pdf"],
    ["every group's sheet, Excel", `/api/templates/${groupedTemplate}/export?format=xlsx&group=all`, "xlsx"],
  ] : []),
];

for (const [what, path, kind] of wanted) {
  let answer;
  try {
    answer = await call(path);
  } catch (error) {
    check(false, what, String(error));
    continue;
  }
  if (!answer.ok) {
    // The server's own words, which is where ModuleNotFoundError showed up.
    const said = (await answer.text()).slice(0, 200).replace(/\s+/g, " ");
    check(false, what, `${answer.status} ${said}`);
    continue;
  }
  const bytes = new Uint8Array(await answer.arrayBuffer());
  const name = /filename\*?=(?:UTF-8'')?"?([^";]+)/i
    .exec(answer.headers.get("content-disposition") || "")?.[1] || "";
  const start = STARTS[kind];
  const rightBytes = start ? start.every((b, i) => bytes[i] === b) : bytes.length > 0;
  check(rightBytes && bytes.length > 200 && name.endsWith(`.${kind}`), what,
        `${answer.status}, ${bytes.length} bytes, ${name || "no filename"}`);
}

console.log(failures.length ? `FAILED: ${failures.join("; ")}` : "Every export came back whole.");
process.exit(failures.length ? 1 : 0);
