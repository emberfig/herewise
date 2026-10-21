// Who is signed in, what their role lets them do, and the sentence to write on anything it does not.
//
// The refusal sentence is built from the same vocabulary the backend gates on (GET /api/permissions,
// rollcall/roles.py), so a control's reason and the route's refusal cannot drift apart. Screens name
// the permission, never a role: roles are rows people create and name themselves, so any fixed job
// title is wrong for somebody (docs/DESIGN-DEVIATIONS.md, standing deviation 3).

import { api } from "./api.js";

const state = {
  account: null,
  permissions: new Set(),
  labels: new Map(),     // permission key to its label, for the refusal sentence
  groups: [],            // the vocabulary, grouped, for the role editor
  reminders: [],
  settings: null,
  listeners: new Set(),
};

export const session = {
  get account() { return state.account; },
  get reminders() { return state.reminders; },
  get groups() { return state.groups; },
  get signedIn() { return state.account !== null; },

  can(permission) {
    return !permission || state.permissions.has(permission);
  },

  // "Your role does not allow this: correct attendance." The backend says exactly this
  // (roles.denial); the label comes from the same table.
  denial(permission) {
    const label = state.labels.get(permission);
    return `Your role does not allow this: ${(label || permission).toLowerCase()}.`;
  },

  label(permission) {
    return state.labels.get(permission) || permission;
  },

  // Nobody corrects, excuses or decides for the student record their own account is linked to.
  // Enforced in the backend as well, twice over, because it is not a permission.
  isSelf(personId) {
    return Boolean(personId) && state.account !== null && state.account.person_id === personId;
  },

  onChange(listener) {
    state.listeners.add(listener);
    return () => state.listeners.delete(listener);
  },

  async load() {
    const me = await api.get("/api/me");
    adopt(me);
    if (!state.groups.length) {
      state.groups = await api.get("/api/permissions");
      for (const group of state.groups) {
        for (const item of group.permissions) state.labels.set(item.key, item.label);
      }
    }
    return me;
  },

  adopt,

  async settings(reload = false) {
    if (!state.settings || reload) state.settings = await api.get("/api/settings");
    return state.settings;
  },

  clearSettings() { state.settings = null; },

  clear() {
    state.account = null;
    state.permissions = new Set();
    state.reminders = [];
    state.settings = null;
    announce();
  },
};

function adopt(me) {
  state.account = me;
  state.permissions = new Set(me.permissions || []);
  state.reminders = me.reminders || [];
  announce();
}

function announce() {
  for (const listener of state.listeners) listener(state.account);
}
