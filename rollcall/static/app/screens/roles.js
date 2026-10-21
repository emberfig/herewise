// Screen 42: Roles. Mockups: RolesOwnerLecturer.png, RolesCourserep.png, RolesNewexamofficer.png,
// RolesStillinuse.png. Fix list: docs/DESIGN-DEVIATIONS.md, "42 Roles".
//
// Roles are rows people create and name for themselves. The permission vocabulary is fixed in code,
// because a permission nothing checks is a lie told to whoever ticks it, and every route is gated
// on exactly one of them.
//
// The owner role is the exception: it always holds every permission, including ones a later version
// adds, and cannot be edited or deleted. Without it a database can reach a state where nobody can
// grant anybody anything, which is unrecoverable without editing SQLite by hand.

import { ApiError, api } from "../api.js";
import { session } from "../session.js";
import {
  invalid, actionRow, announce, button, dialog, field, fill, h, loadingCards, page, plural, section, setBusy,
  toast,
} from "../ui.js";

export default {
  id: "roles",
  nav: "settings",
  title: "Roles",
  permission: "roles.manage",

  async render(view, ctx) {
    const host = h("div");
    view.append(host);
    fill(host, page({ title: "Roles", children: [loadingCards(3)] }));
    const reload = () => this.render(fill(view), ctx);
    const [roles, groups, accounts] = await Promise.all([
      api.get("/api/roles"),
      api.get("/api/permissions"),
      api.get("/api/accounts").catch(() => []),
    ]);
    draw(host, roles, groups, accounts, reload);
  },
};

function draw(host, roles, groups, accounts, reload) {
  const holders = (roleId) => accounts.filter((a) => a.role_id === roleId && !a.disabled).length;

  fill(host, page({
    title: "Roles",
    subtitle: `${plural(roles.length, "role")} · each one is a row you name and tick yourself`,
    actions: [button({ label: "New role", primary: true,
      onClick: () => editor(null, groups, reload) })],
    children: [
      h("p", { class: "hw-muted", style: { maxWidth: "70ch", marginBlockEnd: "var(--hw-space-6)" } },
        "There is no fixed list of job titles here. Make a role, call it what your department calls "
        + "it, and tick what it may do. Every screen names the permission it needs, not a role, so "
        + "anyone holding it can use that screen."),
      h("div", { class: "hw-stack" }, ...roles.map((role) => card(role, groups, holders(role.id), reload))),
    ],
  }));
}

function card(role, groups, holders, reload) {
  const owner = Boolean(role.is_owner);
  return h("article", { class: "hw-card hw-stack hw-stack--tight" },
    h("div", { class: "hw-row hw-row--between" },
      h("div", {},
        h("h3", { style: { margin: 0, fontSize: "var(--hw-text-lead)" } }, role.name,
          owner ? h("span", { class: "hw-tag" }, "owner") : null),
        h("p", { class: "hw-muted", style: { margin: "var(--hw-space-1) 0 0" } }, role.description)),
      actionRow(
        button({ label: "Edit", reason: owner
          ? "The owner role always holds every permission, so there is nothing to edit."
          : "", onClick: () => editor(role, groups, reload) }),
        button({ label: "Delete", variant: "destructive",
          reason: owner ? "There is always one owner role. Deleting it would lock everybody out."
            : holders ? `${plural(holders, "account")} still hold${holders === 1 ? "s" : ""} it. `
              + "Move them to another role first."
              : "",
          onClick: () => remove(role, reload) }))),
    h("p", { class: "hw-muted", style: { margin: 0 } },
      `${plural(holders, "account")} hold${holders === 1 ? "s" : ""} it · `
      + (owner ? "every permission, now and in future versions"
        : `${plural(role.permissions.length, "permission")}`)),
    owner ? null : permissionSummary(role, groups));
}

function permissionSummary(role, groups) {
  const held = new Set(role.permissions);
  return h("div", { class: "hw-row", style: { gap: "var(--hw-space-4)" } },
    ...groups.map((group) => {
      const count = group.permissions.filter((p) => held.has(p.key)).length;
      return h("span", { class: "hw-muted" },
        h("span", { "aria-hidden": "true",
          style: { color: count ? "var(--hw-present)" : "var(--hw-ink-muted)" } },
          count ? "✓ " : "○ "),
        `${group.group} ${count} of ${group.permissions.length}`);
    }));
}

/** The permission grid: grouped, with the plain sentence under each, from GET /api/permissions. */
function editor(role, groups, reload) {
  const name = field({ label: "Name", value: role ? role.name : "",
    help: "What your department calls this job. Nothing depends on the word.",
    validate: (v) => (v.trim() ? "" : "Give the role a name.") });
  const description = field({ label: "What it is for", rows: 2,
    value: role ? role.description : "",
    help: "Shown beside the name, so whoever assigns it knows what they are giving." });

  const held = new Set(role ? role.permissions : []);
  const grid = h("div", { class: "hw-stack" });
  for (const group of groups) {
    const boxes = group.permissions.map((permission) => {
      const input = h("input", { type: "checkbox", value: permission.key,
        checked: held.has(permission.key) || null });
      input.addEventListener("change", () => {
        if (input.checked) held.add(permission.key);
        else held.delete(permission.key);
      });
      return h("label", { class: "hw-choice" }, input,
        h("span", {},
          h("span", { class: "hw-choice__label" }, permission.label),
          // The plain sentence the backend writes for this permission, not a paraphrase.
          h("span", { class: "hw-choice__help" }, ` ${permission.help}`)));
    });
    grid.append(section(group.group, h("div", { class: "hw-stack hw-stack--tight" }, ...boxes)));
  }

  const save = button({ label: role ? "Save the role" : "Make the role", primary: true,
    busyLabel: "Saving" });
  const box = dialog({
    title: role ? `Edit ${role.name}` : "A new role",
    body: h("div", { class: "hw-stack" }, name, description, grid),
    actions: [button({ label: "Go back", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });

  save.addEventListener("click", async () => {
    if (invalid(name)) return;
    setBusy(save, true);
    const body = { name: name.value().trim(), description: description.value().trim(),
      permissions: [...held] };
    try {
      if (role) await api.patch(`/api/roles/${role.id}`, body);
      else await api.post("/api/roles", body);
      box.close();
      toast(role ? "The role is saved." : "The role is made.");
      announce("Saved.");
      await reload();
    } catch (error) {
      setBusy(save, false);
      name.showError(error instanceof ApiError ? error.message : "That did not save.");
    }
  });
}

function remove(role, reload) {
  const go = button({ label: "Delete it", variant: "destructive", busyLabel: "Deleting" });
  const box = dialog({
    title: `Delete ${role.name}?`,
    body: h("p", { style: { margin: 0 } },
      "The role goes. Nobody holds it, so nothing anyone can do changes. Making it again later "
      + "means ticking its permissions again."),
    actions: [button({ label: "Keep it", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, go)],
  });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      await api.del(`/api/roles/${role.id}`);
      box.close();
      toast("The role is deleted.");
      await reload();
    } catch (error) {
      setBusy(go, false);
      toast(error instanceof ApiError ? error.message : "That did not work.", "failure");
    }
  });
}
