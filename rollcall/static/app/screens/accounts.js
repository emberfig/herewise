// Screen 37: Accounts. Mockups: Accounts.png, Accountsaddinganaccount.png,
// Accountsdisabledaccount.png, Accountslastowner.png.
// Fix list: docs/DESIGN-DEVIATIONS.md, "37 Accounts".
//
// Two things no role can grant, and both are enforced in the backend as well as shown here: the
// database always keeps one enabled account holding the owner role, and nobody corrects or excuses
// the student record their own account is linked to.
//
// Known gap 3, closed 2026-09-21: an account whose password is forgotten gets a new one from here,
// and a disabled account can be turned back on. The sole owner has nobody above them, so their way
// back is on this computer itself: python -m rollcall reset-password <username>.

import { ApiError, api } from "../api.js";
import { href } from "../router.js";
import { session } from "../session.js";
import {
  invalid, actionRow, announce, button, dialog, field, fill, h, loadingTable, page, plural, section, setBusy,
  table, toast,
} from "../ui.js";

export default {
  id: "accounts",
  nav: "settings",
  title: "Accounts",
  permission: "accounts.manage",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Accounts",
      children: [loadingTable(["Name", "Username", "Role", "Linked student", ""])] }));
    const reload = () => this.render(fill(view), ctx);
    // The way back in is read from the backend, because it is a different command in the installed
    // app from a source checkout, and the people who get locked out are running the installed one.
    const [accounts, roles, about] = await Promise.all([
      api.get("/api/accounts"), api.get("/api/roles"),
      api.get("/api/about").catch(() => ({})),
    ]);
    draw(host, accounts, roles, reload, about.reset_password_command);
  },
};

function draw(host, accounts, roles, reload, resetCommand) {
  const state = { query: "" };
  const list = h("div");
  const owners = accounts.filter((a) => a.is_owner && !a.disabled);

  const search = h("input", { class: "hw-input", type: "search", placeholder: "Find an account",
    autocomplete: "off", "aria-label": "Find an account" });
  search.addEventListener("input", () => { state.query = search.value; paint(); });

  function paint() {
    const q = state.query.trim().toLowerCase();
    const rows = q
      ? accounts.filter((a) => `${a.display_name} ${a.username} ${a.role}`.toLowerCase().includes(q))
      : accounts;
    fill(list, table({
      caption: "Every account on this computer",
      rows,
      rowAttrs: (a) => (a.disabled ? { dataset: { dimmed: "true" } } : null),
      columns: [
        { label: "Name", render: (a) => h("span", {}, a.display_name,
          a.id === session.account.id ? h("span", { class: "hw-tag" }, "you") : null) },
        { label: "Username", render: (a) => h("span", { class: "hw-ids" }, a.username) },
        { label: "Role", render: (a) => h("span", {}, a.role || "–",
          a.is_owner ? h("span", { class: "hw-tag" }, "owner") : null) },
        { label: "Linked student", render: (a) => a.person_id
          ? h("a", { class: "hw-link", href: href(`students/${a.person_id}`) }, "Their record")
          : h("span", { class: "hw-muted" }, "Not linked") },
        { label: "State", render: (a) => a.disabled
          ? h("span", { class: "hw-pill", dataset: { tone: "neutral" } },
            h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "✕"), "Turned off")
          : h("span", { class: "hw-pill", dataset: { tone: "present" } },
            h("span", { class: "hw-pill__glyph", "aria-hidden": "true" }, "✓"), "On") },
        { label: "", align: "end", render: (a) => actions(a, roles, owners, reload) },
      ],
    }));
  }

  fill(host, page({
    title: "Accounts",
    subtitle: `${plural(accounts.filter((a) => !a.disabled).length, "account")} on this computer`,
    actions: [button({ label: "Add an account", primary: true,
      onClick: () => addDialog(roles, reload) })],
    children: [
      h("div", { class: "hw-row hw-row--between", style: { marginBlockEnd: "var(--hw-space-4)" } },
        h("div", { style: { flex: "0 1 380px" } }, search)),
      list,
      section("If somebody cannot get in",
        h("div", { class: "hw-card hw-stack hw-stack--tight" },
          h("p", { style: { margin: 0 } },
            "Set them a new password from the row above. They are signed out everywhere as it "
            + "changes, because a forgotten password often means somebody else has it."),
          h("p", { class: "hw-muted", style: { margin: 0 } },
            "If the person locked out is the only owner, nobody here can help them: the way back is "
            + "on this computer itself, by running"),
          h("p", { class: "hw-well hw-ids", style: { margin: 0 } },
            resetCommand || "python -m rollcall reset-password <username>"),
          h("p", { class: "hw-muted", style: { margin: 0 } },
            "It needs the same access to this machine as copying the register would, and it is "
            + "recorded in the activity log."))),
    ],
  }));
  paint();
}

function actions(account, roles, owners, reload) {
  const me = account.id === session.account.id;
  const lastOwner = account.is_owner && owners.length <= 1 && !account.disabled;
  return actionRow(
    button({ label: "New password", onClick: () => passwordDialog(account, reload) }),
    button({ label: "Change role", reason: lastOwner
      ? "This is the only owner. Make somebody else an owner first, or nobody could grant anything."
      : "", onClick: () => roleDialog(account, roles, reload) }),
    account.disabled
      ? button({ label: "Turn back on", primary: true,
          onClick: () => enable(account, reload) })
      : button({ label: "Turn off", variant: "destructive",
          reason: me ? "You cannot turn off your own account."
            : lastOwner ? "This is the only owner. Turning it off would lock everybody out." : "",
          onClick: () => disableDialog(account, reload) }));
}

function addDialog(roles, reload) {
  const name = field({ label: "Name", help: "Shown in the app and on every correction they sign.",
    validate: (v) => (v.trim() ? "" : "Give the account a name.") });
  const username = field({ label: "Username", help: "What they type to sign in.",
    validate: (v) => (v.trim() ? "" : "Choose a username.") });
  const password = field({ label: "First password", type: "password",
    help: "At least 6 characters. They can be given a new one at any time from this screen.",
    validate: (v) => (v.length >= 6 ? "" : "Use at least 6 characters.") });
  const role = field({ label: "Role",
    options: roles.map((r) => ({ value: r.id, label: `${r.name} · ${r.description}` })) });
  const person = field({ label: "Linked student", help:
    "Optional. Their matric number, if this account belongs to a student on the register. Herewise "
    + "then refuses to let them correct or excuse their own attendance." });

  const found = { personId: null };
  person.control.addEventListener("input", async () => {
    const q = person.value().trim();
    if (q.length < 2) { found.personId = null; return; }
    const results = await api.get(`/api/students/search?q=${encodeURIComponent(q)}`).catch(() => []);
    found.personId = results.length === 1 ? results[0].id : null;
  });

  const save = button({ label: "Make the account", primary: true, busyLabel: "Making" });
  const box = dialog({
    title: "Add an account",
    body: h("div", { class: "hw-stack" }, name, username, password, role, person),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(name, username, password)) return;
    setBusy(save, true);
    try {
      await api.post("/api/accounts", { username: username.value().trim(),
        display_name: name.value().trim(), password: password.value(),
        role_id: Number(role.value()), person_id: found.personId });
      box.close();
      toast("The account is made. Tell them their first password in person.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      username.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}

function passwordDialog(account, reload) {
  const password = field({ label: "New password", type: "password",
    help: "At least 6 characters. Tell them in person, not in writing.",
    validate: (v) => (v.length >= 6 ? "" : "Use at least 6 characters.") });
  const save = button({ label: "Set the password", primary: true, busyLabel: "Setting" });
  const box = dialog({
    title: `A new password for ${account.display_name}`,
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        "You never see their old one: only the new password is stored, and it is stored as a hash. "
        + "Every session this account has open ends as it changes."),
      password),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    if (invalid(password)) return;
    setBusy(save, true);
    try {
      await api.post(`/api/accounts/${account.id}/password`, { password: password.value() });
      box.close();
      toast(`${account.display_name} can sign in with the new password.`);
      announce("The password is set.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      password.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}

function roleDialog(account, roles, reload) {
  const role = field({ label: "Role", value: String(account.role_id),
    options: roles.map((r) => ({ value: r.id, label: `${r.name} · ${r.description}` })) });
  const save = button({ label: "Change the role", primary: true, busyLabel: "Changing" });
  const box = dialog({
    title: `What ${account.display_name} may do`,
    body: h("div", { class: "hw-stack" },
      h("p", { style: { margin: 0 } },
        "A role is a row somebody made and ticked. Changing it changes what this account can open "
        + "from the next screen they load."),
      role),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  save.addEventListener("click", async () => {
    setBusy(save, true);
    try {
      await api.post(`/api/accounts/${account.id}/role`, { role_id: Number(role.value()) });
      box.close();
      toast("The role is changed.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}

function disableDialog(account, reload) {
  const go = button({ label: "Turn it off", variant: "destructive", busyLabel: "Turning off" });
  const box = dialog({
    title: `Turn off ${account.display_name}?`,
    body: h("p", { style: { margin: 0 } },
      "They cannot sign in, and any session they have open ends. Everything they have ever done "
      + "stays in the register with their name on it, and the account can be turned back on."),
    actions: [button({ label: "Leave it on", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      await api.post(`/api/accounts/${account.id}/disable`, {});
      box.close();
      toast("The account is turned off.");
      await reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}

async function enable(account, reload) {
  try {
    await api.post(`/api/accounts/${account.id}/enable`, {});
    toast(`${account.display_name} can sign in again.`);
    await reload();
  } catch (error) {
    toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
  }
}
