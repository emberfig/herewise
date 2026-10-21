// Gallery for <hw-sheet>: every state from the fixtures, in light, dark and projection panels.
// A file, not an inline script, because the app's Content-Security-Policy allows scripts from itself only.
import "../components/hw-sheet.js";

const PANELS = {
  light: { theme: "light", label: "Light" },
  dark: { theme: "dark", label: "Dark" },
  projection: { theme: "light", label: "Projection", projection: true },
};
const cache = new Map();
const host = document.getElementById("panels-host");
const state = document.getElementById("state");
const panels = document.getElementById("panels");
const log = document.getElementById("log");

// Remember the last choice in the address, so a reload or a shared link shows the same state.
const params = new URLSearchParams(location.search);
if (params.get("state")) state.value = params.get("state");
if (params.get("panels")) panels.value = params.get("panels");

async function fixture(name) {
  if (!cache.has(name)) cache.set(name, fetch(`fixtures/${name}.json`).then((r) => r.json()));
  return cache.get(name);
}

async function show() {
  history.replaceState(null, "", `?state=${state.value}&panels=${panels.value}`);
  const keys = panels.value === "all" ? ["light", "dark", "projection"] : [panels.value];
  host.replaceChildren();
  for (const key of keys) {
    const p = PANELS[key];
    const section = document.createElement("section");
    section.className = "gallery__panel";
    section.dataset.theme = p.theme;
    section.innerHTML = `<h2>${p.label}</h2>`;
    const sheet = document.createElement("hw-sheet");
    sheet.setAttribute("setup-href", "#sheet-setup");
    sheet.setAttribute("add-students-href", "#course-students");
    if (p.projection) sheet.setAttribute("projection", "");
    section.append(sheet);
    host.append(section);
    if (state.value === "loading") sheet.showLoading();
    else if (state.value === "error") sheet.showError();
    else sheet.data = structuredClone(await fixture(state.value));
  }
  window.sheets = [...host.querySelectorAll("hw-sheet")];
}

document.addEventListener("hw-sheet-open", (event) => {
  const d = event.detail;
  log.textContent = `hw-sheet-open: ${d.full_name} (${d.matric_no}), person ${d.person_id}, class ${d.session_id}, week ${d.week} class ${d.slot}, ${d.state}`;
});
document.addEventListener("hw-sheet-retry", () => { log.textContent = "hw-sheet-retry"; });
state.addEventListener("change", show);
panels.addEventListener("change", show);
show();
  
