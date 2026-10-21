// Screen 2: Sign in. Mockups: Signin.png, Signin-failedattempt.png, Signin-CapsLockon.png,
// Signin-signedout.png. Fix list: docs/DESIGN-DEVIATIONS.md, "2 Sign in".
//
// Three things that panel does and this keeps: one panel naming all three causes, no red border and
// no helper text on either field, and nothing that tells a stranger which half was wrong. The
// username is kept and the password emptied and focused for another try.
//
// Fixed from the mockup: the failure glyph is a cross, not an empty ring (an empty ring is this
// app's mark for "not reached"); the column is anchored at a fixed top offset so a panel pushes only
// what is beneath it; and an input keeps its height whether it holds anything or not.

import { ApiError, api } from "../api.js";
import { mark } from "../icons.js";
import { session } from "../session.js";
import { announce, button, credit, field, h, panel, setBusy } from "../ui.js";

const FAILURE = "That username and password did not sign you in";
const FAILURE_BODY = "Check both and try again. Passwords are case-sensitive. If your account has been " +
  "turned off, ask someone whose role allows managing accounts.";

export default {
  id: "signin",
  title: "Sign in",
  chrome: false,
  permission: null,

  render(view) {
    const username = field({ label: "Username", name: "username", autocomplete: "username" });
    const show = h("button", { class: "hw-button hw-button--quiet", type: "button",
      dataset: { action: "show-password" }, "aria-pressed": "false" }, "Show");
    const password = field({ label: "Password", name: "password", type: "password",
      autocomplete: "current-password", labelAside: show });
    show.addEventListener("click", () => {
      const showing = password.control.type === "password";
      password.control.type = showing ? "text" : "password";
      show.textContent = showing ? "Hide" : "Show";
      show.setAttribute("aria-pressed", String(showing));
      password.control.focus();
    });

    // Quiet, in ink, and nothing else on the card moves for it.
    const caps = h("p", { class: "hw-field__help", hidden: true },
      h("span", { class: "hw-visually-hidden" }, "Warning: "),
      h("kbd", { style: { border: "1px solid var(--hw-rule-strong)", borderRadius: "4px", padding: "0 4px" } }, "⇧"),
      " Caps Lock is on.");
    password.append(caps);
    const watchCaps = (event) => {
      const on = event.getModifierState?.("CapsLock");
      if (on === undefined) return;
      caps.hidden = !on;
    };
    password.control.addEventListener("keyup", watchCaps);
    password.control.addEventListener("keydown", watchCaps);

    const slot = h("div");
    const submit = button({ label: "Sign in", primary: true, type: "submit", busyLabel: "Signing in" });
    submit.classList.add("hw-button--block", "hw-button--large");

    const form = h("form", { class: "hw-card hw-stack", novalidate: true },
      h("h1", { class: "hw-page__title", style: { fontSize: "var(--hw-text-title)" } }, "Sign in"),
      slot, username, password, submit);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      slot.replaceChildren();
      setBusy(submit, true);
      try {
        const me = await api.post("/api/login", { username: username.value(), password: password.value() });
        session.adopt(me);
        if (!session.groups.length) await session.load();
        window.dispatchEvent(new CustomEvent("hw-signed-in"));
      } catch (error) {
        setBusy(submit, false);
        const slow = error instanceof ApiError && error.status === 429;
        slot.append(panel({
          tone: "failure",
          title: slow ? "Too many attempts in a row" : FAILURE,
          body: slow ? error.message : FAILURE_BODY,
          role: "alert",
        }));
        announce(slow ? error.message : FAILURE);
        password.control.value = "";
        password.control.focus();
      }
    });

    if (sessionStorage.getItem("hw-signed-out")) {
      sessionStorage.removeItem("hw-signed-out");
      slot.append(panel({ tone: "info", body: "You have been signed out. Sign in again to carry on." }));
    }

    view.append(h("div", { class: "hw-column" },
      h("div", { class: "hw-column__brand" }, mark({ size: 36 }), h("span", {}, "herewise")),
      form,
      h("p", { class: "hw-column__foot" },
        "Forgotten your password? Ask someone whose role allows managing accounts to set a new one."),
      h("p", { class: "hw-column__note" }, "Works on this computer only. No internet needed."),
      credit()));

    username.control.focus();
  },
};
