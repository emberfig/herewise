// Hash routing, because the app is served by StaticFiles from one folder: a deep path would 404
// on reload, and there is no server-side router to add.
//
// A screen is a module with { id, title, permission, chrome, render(view, context) }. Modules are
// imported when their route is first opened, so opening Today does not parse 44 screens.

const routes = [];

/** define("courses/:id/sheet", () => import("./screens/course-sheet.js")) */
export function define(pattern, load) {
  const names = [];
  const source = pattern.split("/").map((part) => {
    if (part.startsWith(":")) {
      names.push(part.slice(1));
      return "([^/]+)";
    }
    return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }).join("/");
  routes.push({ test: new RegExp(`^${source}$`), names, load, pattern });
}

export function match(path) {
  for (const route of routes) {
    const found = route.test.exec(path);
    if (!found) continue;
    const params = {};
    route.names.forEach((name, index) => { params[name] = decodeURIComponent(found[index + 1]); });
    return { route, params };
  }
  return null;
}

export function current() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  return { path: path.replace(/\/$/, ""), query: new URLSearchParams(query) };
}

export function go(path, { replace = false } = {}) {
  const hash = `#/${String(path).replace(/^#?\/?/, "")}`;
  // replaceState does not fire hashchange and neither does setting the same hash twice, so both
  // cases announce themselves. Without this a redirect silently leaves the old screen on the page.
  if (replace || location.hash === hash) {
    if (location.hash !== hash) history.replaceState(null, "", hash);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    return;
  }
  location.hash = hash;
}

export function href(path) {
  return `#/${String(path).replace(/^#?\/?/, "")}`;
}

export function start(onRoute) {
  window.addEventListener("hashchange", () => onRoute(current()));
  onRoute(current());
}
