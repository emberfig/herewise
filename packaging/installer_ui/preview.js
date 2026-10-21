// A stand-in for packaging/installer_window.py, so the installer's screens can be looked at in a
// browser: index.html?preview=install, update, remove, running, portable or runtime. Never built in.

const kind = new URLSearchParams(location.search).get("preview") || "install";
const PROGRAM = "C:\\Users\\lecturer\\AppData\\Local\\Programs\\Herewise";
const REGISTER = "C:\\Users\\lecturer\\AppData\\Local\\Herewise";
const wait = (ms) => new Promise((done) => setTimeout(done, ms));
let tries = 0;

async function play(steps) {
  for (const [step, done, total, detail] of steps) {
    window.hw.progress({ step, done, total, detail });
    await wait(450);
  }
}

window.pywebview = {
  api: {
    async info() {
      return {
        mode: kind === "remove" ? "remove" : "install",
        version: "0.1.6",
        previous: kind === "install" || kind === "runtime" ? null : "0.1.5",
        program_dir: PROGRAM,
        register_dir: REGISTER,
        register_exists: kind !== "install",
      };
    },
    async install(withDesktop) {
      if (kind === "running" && tries++ === 0) {
        await wait(300);
        return window.hw.failed({ heading: "Herewise is still running.", body: "", code: "running" });
      }
      if (kind === "portable") {
        await wait(300);
        return window.hw.failed({ heading: "This copy of Herewise keeps its register inside the program folder.",
          body: `${PROGRAM} has been set up to run portably, so the attendance records are in it, and replacing or removing the folder would delete them.\n\nNothing has been changed. Take a backup from the app first, or move rollcall.db out of that folder, then run this again.`,
          code: "portable" });
      }
      await play([["prepare", 0, 3404, "Getting ready"], ["copy", 800, 3404, "Copying files, 800 of 3,400"],
        ["copy", 2100, 3404, "Copying files, 2,100 of 3,400"], ["copy", 3400, 3404, "Copying files, 3,400 of 3,400"],
        ["shortcuts", 3401, 3404, "Making the shortcuts"], ["entry", 3402, 3404, "Adding Herewise to Installed apps"],
        ["runtime", 3403, 3404, "Checking the window runtime"], ["done", 3404, 3404, "Done"]]);
      window.hw.finished({ mode: "install", replacing: kind !== "install" && kind !== "runtime",
        previous: kind === "install" || kind === "runtime" ? null : "0.1.5", version: "0.1.6", desktop: withDesktop,
        runtime: kind === "runtime" ? "This computer does not have the Microsoft Edge WebView2 Runtime, which draws Herewise's window, so Herewise will open in your web browser instead. Everything works the same there." : "" });
    },
    async uninstall() {
      await play([["check", 0, 3, "Checking Herewise is closed"], ["shortcuts", 1, 3, "Removing the shortcuts"],
        ["entry", 2, 3, "Taking Herewise out of Installed apps"], ["done", 3, 3, "Done"]]);
      window.hw.finished({ mode: "remove", register: REGISTER, register_exists: true });
    },
    async close_running() { await wait(600); return 1; },
    async open_app() { console.log("open_app"); },
    async open_register() { console.log("open_register"); },
    async close() { console.log("close"); },
  },
};
