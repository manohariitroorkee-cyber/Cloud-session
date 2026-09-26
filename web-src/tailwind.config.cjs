/** @type {import('tailwindcss').Config} */
// Colours come from CSS variables in input.css so one class works in both
// themes (and follows the host's data-theme override).
module.exports = {
  content: [__dirname + "/template.html", __dirname + "/app.js"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        panel: "color-mix(in srgb, var(--panel) calc(<alpha-value> * 100%), transparent)",
        sunk: "var(--sunk)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        line: "var(--line)",
        accent: "var(--accent)",
        "accent-hover": "var(--accent-hover)",
        "accent-ink": "var(--accent-ink)",
        "accent-soft": "var(--accent-soft)",
        crit: "var(--crit)",
        good: "var(--good)",
      },
    },
  },
};
