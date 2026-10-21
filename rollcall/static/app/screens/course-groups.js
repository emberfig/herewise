// Groups, a tab of a course (asked for on 2026-09-29, no design yet): split the course's students
// into Group A, B, C and D, move a student between groups, and paste a department's own list into a
// group. A course with no groups is taken with its whole roster, as every course was before.
//
// The rules are the backend's (rollcall/groups.py). This screen asks the one question that needs a
// person: when a student who has had classes with their group moves, whether they are changing group
// from today (those classes stay with the old group) or were in the wrong group all along.

import { ApiError, api } from "../api.js";
import {
  actionRow, announce, button, dialog, field, fill, h, invalid, matricText, panel, plural, section,
  setBusy, setReason, table, toast,
} from "../ui.js";
import { frame } from "./course.js";

export default {
  id: "course-groups",
  nav: "courses",
  title: "Groups",
  permission: "register.read",

  async render(view, ctx) {
    const courseId = Number(ctx.params.id);
    const reload = () => this.render(fill(view), ctx);
    const { course, body } = await frame(view, courseId, "groups");
    const data = await api.get(`/api/courses/${courseId}/groups`);
    if (!data.groups.length) {
      drawSplit(body, course, data, reload);
    } else {
      drawGroups(body, course, data, reload);
    }
  },
};

function failed(error, fallback) {
  toast(error instanceof ApiError ? error.message : fallback, "failure");
}

function drawSplit(body, course, data, reload) {
  const students = data.students.length;
  const count = field({ label: "How many groups", type: "number", width: "short", value: "4", min: 2, max: 20,
    validate: (v) => (Number(v) >= 2 && Number(v) <= 20 ? "" : "Choose 2 to 20 groups.") });
  const order = field({ label: "Share the students out in", name: "order", width: "medium", value: "matric",
    options: [{ value: "matric", label: "Matric number order" }, { value: "surname", label: "Surname order" }] });
  const go = button({ label: "Split into groups", primary: true, busyLabel: "Splitting",
    permission: "courses.manage",
    reason: students < 2 ? "This course needs at least two students before it can be split." : "",
    onClick: async () => {
      if (invalid(count)) return;
      setBusy(go, true);
      try {
        const done = await api.post(`/api/courses/${course.id}/groups/split`,
          { count: Number(count.value()), order: order.querySelector("select").value });
        toast(`${course.code} is split into ${plural(done.groups.length, "group")}.`);
        announce("The groups are made.");
        await reload();
      } catch (error) {
        setBusy(go, false);
        failed(error, "The course was not split.");
      }
    } });
  // Asked for on 2026-09-29, after the first real split: the lecturer picks who goes where. Empty
  // groups first, then everybody is in no group and is ticked into one.
  const empty = button({ label: "Make empty groups, and pick the students myself", busyLabel: "Making",
    permission: "courses.manage",
    onClick: async () => {
      if (invalid(count)) return;
      setBusy(empty, true);
      try {
        for (let n = 0; n < Number(count.value()); n += 1) await api.post(`/api/courses/${course.id}/groups`, {});
        toast(`${plural(Number(count.value()), "empty group")} made. Tick students to put them in one.`);
        await reload();
      } catch (error) {
        setBusy(empty, false);
        failed(error, "The groups were not made.");
      }
    } });
  fill(body,
    section("Take this course in groups",
      h("p", {}, `${course.code} is taken with its whole roster: every class is for all `
        + `${plural(students, "student")}. Split it into groups to take a class for one group at a time, `
        + "for example a practical for Group A. Classes for everybody still work as they do now."),
      h("p", { class: "hw-muted" }, "Each group gets an unbroken run of the list, and the groups differ "
        + "by one student at most. A student is counted only against the classes for everybody and "
        + "their own group's. Other courses keep their whole roster."),
      h("div", { class: "hw-stack hw-stack--tight" }, count, order, h("div", { class: "hw-row" }, go, empty))));
}

function drawGroups(body, course, data, reload) {
  const picker = pickStudents(course, data, reload);
  const byGroup = new Map(data.groups.map((g) => [g.id, []]));
  const loose = [];
  for (const s of data.students) (s.group_id ? byGroup.get(s.group_id) : loose)?.push(s);

  const add = button({ label: "Add a group", permission: "courses.manage", onClick: async () => {
    try {
      const made = await api.post(`/api/courses/${course.id}/groups`, {});
      toast(`${made.name} is added.`);
      await reload();
    } catch (error) { failed(error, "The group was not added."); }
  } });
  const clearAll = button({ label: "Remove all groups", variant: "destructive", permission: "courses.manage",
    reason: data.group_classes ? "Classes have been taken for these groups, so they stay: they are "
      + "those classes' registers." : "",
    onClick: () => confirmClear(course, reload) });

  const shareOut = loose.length ? button({ label: `Put ${plural(loose.length, "student")} in the smallest `
    + (loose.length === 1 ? "group" : "groups"),
    primary: true, permission: "courses.manage", busyLabel: "Placing",
    onClick: async () => {
      setBusy(shareOut, true);
      try {
        const done = await api.post(`/api/courses/${course.id}/groups/share-out`, {});
        toast(`${plural(done.placed, "student")} placed.`);
        await reload();
      } catch (error) { setBusy(shareOut, false); failed(error, "Nobody was placed."); }
    } }) : null;

  fill(body,
    h("p", { class: "hw-muted" },
      `${plural(data.groups.length, "group")}. A class is started for one group or for everybody, and each `
      + "student is counted only against the classes for everybody and their own group's."),
    loose.length ? panel({ tone: "review", title: `${plural(loose.length, "student")} in no group`,
      body: "No group's class counts for them, only the classes for everybody. Students added to the "
        + "course after it was split start here." }) : null,
    table({
      caption: "Groups",
      rows: data.groups,
      columns: [
        { label: "Group", render: (g) => g.name },
        { label: "Students", align: "end", render: (g) => h("span", { class: "hw-ids" }, String(g.students)) },
        { label: "Classes held", align: "end", render: (g) => h("span", { class: "hw-ids" }, String(g.held)) },
        { label: "", align: "end", render: (g) => actionRow(
          button({ label: "Paste a list", permission: "courses.manage", onClick: () => pasteList(g, reload) }),
          button({ label: "Rename", permission: "courses.manage", onClick: () => rename(g, reload) }),
          button({ label: "Remove", variant: "destructive", permission: "courses.manage",
            reason: g.can_delete ? "" : `${g.name} has classes, so it stays: they are its register.`,
            onClick: () => removeGroup(g, reload) })) },
      ],
    }),
    // Remove all groups is held apart from the rest by the parted row's rule, never beside a primary.
    h("div", { class: "hw-row hw-row--parted", style: { margin: "var(--hw-space-3) 0 var(--hw-space-5)" } },
      h("div", { class: "hw-row" }, shareOut, add), clearAll),
    picker.bar,
    ...(loose.length ? [studentsSection("In no group", loose, course, data, reload, picker)] : []),
    ...data.groups.map((g) => studentsSection(`${g.name} (${byGroup.get(g.id).length})`, byGroup.get(g.id),
      course, data, reload, picker)));
}

/**
 * Pick students by hand (asked for on 2026-09-29, after the first real split): tick names in any
 * list, choose a group, and put them all in it. Each one is a move "from today", which for a student
 * with no class in their old group is the same as putting them there from the start.
 */
function pickStudents(course, data, reload) {
  const ticked = new Set();
  const count = h("span", { class: "hw-muted", role: "status" }, "Tick students below to put them in a group.");
  const target = field({ label: "Put them in", name: "target", width: "medium", value: String(data.groups[0]?.id ?? ""),
    options: [...data.groups.map((g) => ({ value: String(g.id), label: g.name })), { value: "", label: "No group" }] });
  const go = button({ label: "Put them in", primary: true, busyLabel: "Moving", permission: "courses.manage",
    onClick: async () => {
      if (!ticked.size) { toast("Tick at least one student first.", "failure"); return; }
      const value = target.querySelector("select").value;
      setBusy(go, true);
      let done = 0;
      try {
        for (const id of ticked) {
          const s = data.students.find((x) => x.person_id === id);
          if (String(s.group_id ?? "") === value) continue;
          await api.post(`/api/courses/${course.id}/groups/move`,
            { person_id: id, group_id: value ? Number(value) : null, how: "from_today" });
          done += 1;
        }
        toast(`${plural(done, "student")} moved.`);
        await reload();
      } catch (error) {
        setBusy(go, false);
        failed(error, `${plural(done, "student")} moved before it stopped.`);
        await reload();
      }
    } });
  const bar = h("div", { class: "hw-card hw-row", style: { alignItems: "flex-end", marginBlockEnd: "var(--hw-space-5)",
    position: "sticky", top: "0", zIndex: "3" } }, target, go, count);
  const box = (s) => {
    const input = h("input", { type: "checkbox", "aria-label": `Tick ${s.surname} ${s.other_names}`.trim() });
    input.addEventListener("change", () => {
      if (input.checked) ticked.add(s.person_id); else ticked.delete(s.person_id);
      count.textContent = ticked.size ? `${plural(ticked.size, "student")} ticked.` : "Tick students below to put them in a group.";
    });
    return h("label", { class: "hw-row", style: { minHeight: "var(--hw-target-min)",
      paddingInline: "var(--hw-space-2)", cursor: "pointer" } }, input);
  };
  return { bar, box };
}

function studentsSection(title, rows, course, data, reload, picker) {
  return section(title, rows.length ? table({
    caption: title, rows, limit: 25, what: "student", density: "compact",
    columns: [
      { label: "Pick", render: (s) => picker.box(s) },
      { label: "Matric no.", render: (s) => h("span", { class: "hw-ids" }, matricText(s.matric_no)) },
      { label: "Name", render: (s) => `${s.surname} ${s.other_names}`.trim() },
      { label: "Level", render: (s) => `${s.level} Level${s.kind === "carry_over" ? ", carry-over" : ""}` },
      { label: "", align: "end", render: (s) => button({ label: s.group_id ? "Move" : "Put in a group",
        permission: "courses.manage", onClick: () => moveDialog(s, course, data, reload) }) },
    ],
  }) : h("p", { class: "hw-muted" }, "Nobody in this group yet."));
}

function moveDialog(student, course, data, reload) {
  const name = `${student.surname} ${student.other_names}`.trim();
  const options = data.groups.filter((g) => g.id !== student.group_id)
    .map((g) => ({ value: String(g.id), label: g.name }));
  if (student.group_id) options.push({ value: "", label: "No group" });
  const pick = field({ label: "Group", name: "group", width: "medium", value: options[0]?.value ?? "", options });
  const select = pick.querySelector("select");
  const kept = student.classes_with_group;
  // The one question here that needs a person, asked only when there is something to keep. Two
  // choices with what each does written under it: a list box cut both sentences off at 1366 wide.
  const how = kept ? howChoice(student, kept, () => (select.selectedOptions[0]?.textContent || "the new group")) : null;
  const save = button({ label: "Move", primary: true, busyLabel: "Moving" });
  const box = dialog({
    title: `Move ${name}?`,
    body: h("div", { class: "hw-stack hw-stack--tight" }, pick, how,
      h("p", { class: "hw-muted", style: { margin: 0 } },
        "Only the classes for a group change. Classes for everybody count for them whatever their group.")),
    actions: [button({ label: "Keep them where they are", onClick: () => box.close() }),
      h("span", { class: "hw-cardfoot__end" }, save)],
  });
  select.addEventListener("change", () => how?.say());
  save.addEventListener("click", async () => {
    setBusy(save, true);
    const value = select.value;
    try {
      const done = await api.post(`/api/courses/${course.id}/groups/move`, {
        person_id: student.person_id, group_id: value ? Number(value) : null,
        how: kept ? how.value() : "wrong_group" });
      box.close();
      toast(`${name} is in ${done.group} now.`);
      await reload();
    } catch (error) { setBusy(save, false); failed(error, "They were not moved."); }
  });
}

/**
 * "Changing group from today" or "in the wrong group all along", with what each does to the classes
 * already held. From today is chosen to begin with: it rewrites nothing, where the other changes the
 * register of every class the student has had with their group so far.
 */
function howChoice(student, kept, target) {
  const name = `how-${student.person_id}`;
  const help = {};
  const row = (value, label, checked) => {
    const input = h("input", { type: "radio", name, value, checked: checked || null, dataset: { action: `how-${value}` } });
    help[value] = h("span", { class: "hw-choice__help" });
    return h("label", { class: "hw-choice" }, input,
      h("span", { class: "hw-stack hw-stack--tight", style: { gap: "2px" } },
        h("span", { class: "hw-choice__label" }, label), help[value]));
  };
  const set = h("fieldset", { class: "hw-fieldset" }, h("legend", {}, "What is this?"),
    row("from_today", "They are changing group from today", true),
    row("wrong_group", "They were in the wrong group all along", false));
  set.say = () => {
    const to = target().split(" · ")[0];
    const classes = plural(kept, `${student.group} class`, `${student.group} classes`);
    help.from_today.textContent = to === "No group"
      ? `Their ${classes} so far stay theirs. From today only the classes for everybody count for them.`
      : `Their ${classes} so far stay theirs. ${to}'s classes count for them from today.`;
    help.wrong_group.textContent = to === "No group"
      ? `Their ${classes} stop counting for them, as if they had never been in ${student.group}.`
      : `Their ${classes} stop counting for them, and ${to}'s classes from the same weeks count instead: `
        + "absent from any they did not scan in.";
  };
  set.value = () => set.querySelector("input:checked")?.value || "from_today";
  set.say();
  return set;
}

function rename(group, reload) {
  const name = field({ label: "Name", value: group.name, width: "medium",
    validate: (v) => (v.trim() ? "" : "A group needs a name.") });
  const save = button({ label: "Rename", primary: true, busyLabel: "Saving" });
  const box = dialog({ title: `Rename ${group.name}`, body: name,
    actions: [button({ label: "Cancel", onClick: () => box.close() }), h("span", { class: "hw-cardfoot__end" }, save)] });
  save.addEventListener("click", async () => {
    if (invalid(name)) return;
    setBusy(save, true);
    try {
      await api.patch(`/api/groups/${group.id}`, { name: name.value().trim() });
      box.close();
      toast("The group is renamed.");
      await reload();
    } catch (error) { setBusy(save, false); name.showError(error instanceof ApiError ? error.message : "That did not save."); }
  });
}

function removeGroup(group, reload) {
  const go = button({ label: `Remove ${group.name}`, variant: "destructive", busyLabel: "Removing" });
  const box = dialog({ title: `Remove ${group.name}?`,
    body: h("p", { style: { margin: 0 } }, `Its ${plural(group.students, "student")} will be in no group, `
      + "and can be put in another."),
    actions: [button({ label: "Keep it", onClick: () => box.close() }), h("span", { class: "hw-cardfoot__end" }, go)] });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      await api.del(`/api/groups/${group.id}`);
      box.close();
      toast(`${group.name} is removed.`);
      await reload();
    } catch (error) { setBusy(go, false); failed(error, "The group was not removed."); }
  });
}

function confirmClear(course, reload) {
  const go = button({ label: "Remove all groups", variant: "destructive", busyLabel: "Removing" });
  const box = dialog({ title: `Take ${course.code} back to its whole roster?`,
    body: h("p", { style: { margin: 0 } }, "Every group goes, and every class is for everybody again. "
      + "You can split it again afterwards."),
    actions: [button({ label: "Keep the groups", onClick: () => box.close() }), h("span", { class: "hw-cardfoot__end" }, go)] });
  go.addEventListener("click", async () => {
    setBusy(go, true);
    try {
      await api.del(`/api/courses/${course.id}/groups`);
      box.close();
      toast("The groups are removed.");
      await reload();
    } catch (error) { setBusy(go, false); failed(error, "The groups were not removed."); }
  });
}

function pasteList(group, reload) {
  const paste = field({ label: "Matric numbers", rows: 8, width: "full",
    help: "One per line, as the department's list has them. A name for a student with no matric number (DE)." });
  const result = h("div");
  const preview = button({ label: "Preview", busyLabel: "Reading" });
  const commit = button({ label: "Put them in", primary: true, busyLabel: "Saving", disabled: true,
    reason: "Preview first, so you can see what it would do." });
  const lines = () => paste.value().split("\n");
  const box = dialog({ title: `Put a list into ${group.name}`,
    body: h("div", { class: "hw-stack" }, paste, h("div", {}, preview), result),
    actions: [button({ label: "Go back", onClick: () => box.close() }), h("span", { class: "hw-cardfoot__end" }, commit)] });
  const commitButton = commit.matches("button") ? commit : commit.querySelector("button");
  preview.addEventListener("click", async () => {
    setBusy(preview, true);
    try {
      const plan = await api.post(`/api/groups/${group.id}/list/preview`, { lines: lines() });
      fill(result,
        h("p", { class: "hw-muted", style: { margin: 0 } },
          [`${plan.join} joining`, `${plan.move} moving`, `${plan.already} already in it`,
            `${plan.not_found} not on this course`].join(", ")),
        table({ caption: "What this list would do", density: "compact", rows: plan.entries, limit: 25, what: "line",
          columns: [
            { label: "Line", render: (e) => e.text },
            { label: "What happens", render: (e) => e.note },
          ] }));
      commitButton.disabled = !plan.can_commit;
      // The reason drawn at the start outlives the state that wrote it unless it is changed here.
      setReason(commit, plan.can_commit ? "" : "Nobody in this list would join or move.");
    } catch (error) { failed(error, "That list could not be read."); } finally { setBusy(preview, false); }
  });
  commitButton.addEventListener("click", async () => {
    setBusy(commit, true);
    try {
      await api.post(`/api/groups/${group.id}/list`, { lines: lines() });
      box.close();
      toast(`The list is in ${group.name}.`);
      await reload();
    } catch (error) { setBusy(commit, false); failed(error, "The list was not saved."); }
  });
}
