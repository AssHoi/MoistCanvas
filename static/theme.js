// Dark mode removed (2026-05-21). This file is kept as a no-op stub so any
// legacy callers of window.StudioTheme stay alive without throwing.
// It does NOT read or write localStorage, and never adds the
// theme-dark / studio-theme-dark class.
(function () {
    window.StudioTheme = {
        key: 'studio_theme',
        get: function () { return 'light'; },
        apply: function () { /* no-op */ },
        set: function () { /* no-op */ }
    };
})();
