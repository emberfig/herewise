// The one place the screens talk to the backend. Nothing else calls fetch.
//
// Every failure arrives as an ApiError carrying the backend's own sentence, because the backend
// already writes in the words the lecturer should read (roles.denial, DeviceError.message). A
// screen that rewords a refusal will drift from the route that enforces it.

export class ApiError extends Error {
  constructor(status, body) {
    const message = (body && (body.error || body.detail)) || fallback(status);
    super(typeof message === "string" ? message : fallback(status));
    this.status = status;
    this.hint = (body && body.hint) || "";
    this.code = (body && body.code) || "";
    this.retryAfter = (body && body.retryAfter) || null;
  }

  // Signed out, rather than refused: the shell sends these back to sign in.
  get signedOut() { return this.status === 401; }
  get refused() { return this.status === 403; }
  get offline() { return this.status === 0; }
}

function fallback(status) {
  if (status === 0) return "Herewise is not answering. Check its window is still open, then try again.";
  if (status === 404) return "That is not here any more.";
  if (status >= 500) return "Herewise ran into a problem it could not name.";
  return "That did not work.";
}

async function request(method, path, { body, form, signal } = {}) {
  const init = { method, credentials: "same-origin", signal, headers: {} };
  if (form) {
    init.body = form;
  } else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw new ApiError(0, null);
  }
  if (response.status === 204) return null;
  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = { error: text }; }
  }
  if (!response.ok) {
    const error = new ApiError(response.status, payload);
    const after = response.headers.get("Retry-After");
    if (after) error.retryAfter = Number(after);
    throw error;
  }
  return payload;
}

export const api = {
  get: (path, options) => request("GET", path, options),
  post: (path, body, options) => request("POST", path, { ...options, body }),
  put: (path, body, options) => request("PUT", path, { ...options, body }),
  patch: (path, body, options) => request("PATCH", path, { ...options, body }),
  del: (path, options) => request("DELETE", path, options),
  upload: (path, form, options) => request("POST", path, { ...options, form }),
};

// A download goes through the browser, not through fetch, so Windows gets the filename the backend
// chose and the file never sits in memory. Nothing is fetched from outside the app.
/**
 * Download a file the backend builds, and hand back the name it was saved as.
 *
 * It fetches the file first and saves the bytes, rather than pointing a link at the address and
 * letting the window go and get it. **In the packaged window the second way silently failed for
 * anything slow to build.** The link was clicked and removed in the same breath, and WebView2
 * aborted the request while the server was still drawing the PDF: `net::ERR_ABORTED`, then a
 * download called `export.txt` (the address, not the file) and Edge's own "Something went wrong",
 * outside the app where nothing could explain it. The backup, which is a file copy and answers at
 * once, survived the same code, which is why this was not found until a real export (2026-09-21).
 *
 * Fetching also means a refusal arrives as an ApiError with the backend's own sentence, so the
 * screen can say what happened instead of leaving it to the browser.
 */
export async function download(path) {
  const response = await fetch(path, { credentials: "same-origin" });
  if (!response.ok) {
    let payload = null;
    const text = await response.text().catch(() => "");
    if (text) { try { payload = JSON.parse(text); } catch { payload = { error: text }; } }
    throw new ApiError(response.status, payload);
  }
  const blob = await response.blob();
  const name = nameFrom(response.headers.get("Content-Disposition")) || path.split("/").pop();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  // The object URL has to outlive the click, or the save has nothing to read.
  setTimeout(() => { link.remove(); URL.revokeObjectURL(url); }, 60000);
  return name;
}

/** The filename the backend asked for: filename="Eligibility PCT 201 2026-2027.pdf". */
function nameFrom(disposition) {
  if (!disposition) return "";
  const quoted = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  return quoted ? decodeURIComponent(quoted[1].trim()) : "";
}
