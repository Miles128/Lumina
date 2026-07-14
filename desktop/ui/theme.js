(function () {
  "use strict";

  const PREFS_KEY = "lumina.ui.preferences.v1";
  const MIGRATE_KEY = "lumina.ui.theme-migrate.v2";

  try {
    const raw = localStorage.getItem(PREFS_KEY);
    let prefs = raw ? JSON.parse(raw) : null;

    // theme was stored but unused until recently; the form default "light"
    // started forcing a white canvas over system dark. One-time migrate.
    if (!localStorage.getItem(MIGRATE_KEY)) {
      localStorage.setItem(MIGRATE_KEY, "1");
      if (prefs && prefs.theme === "light") {
        prefs = Object.assign({}, prefs, { theme: "system" });
        localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
      }
    }

    applyTheme(prefs && prefs.theme);
  } catch (_error) {
    // ignore corrupt prefs
  }

  function applyTheme(theme) {
    const root = document.documentElement;
    if (theme === "light" || theme === "dark" || theme === "paper") {
      root.setAttribute("data-theme", theme);
    } else {
      root.removeAttribute("data-theme");
    }
  }

  window.LuminaTheme = {
    apply: applyTheme,
  };
})();
