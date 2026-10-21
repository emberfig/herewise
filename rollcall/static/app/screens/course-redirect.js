// #/courses/3 has no body of its own: the tabs are the screens, and Sheet is the one a course opens
// on (docs/SCREENS.md, screen 11).

import { go } from "../router.js";

export default {
  id: "course",
  nav: "courses",
  title: "Course",
  permission: "register.read",
  render(view, { params }) {
    go(`courses/${params.id}/sheet`, { replace: true });
  },
};
