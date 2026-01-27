import { fontFamily } from "tailwindcss/defaultTheme";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class"],
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--bg) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        card: "rgb(var(--card) / <alpha-value>)",
        border: "rgb(var(--border) / <alpha-value>)",
        primary: "rgb(var(--primary) / <alpha-value>)",
        "primary-fg": "rgb(var(--primary-fg) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        "danger-fg": "rgb(var(--danger-fg) / <alpha-value>)",
        warning: "rgb(var(--warning) / <alpha-value>)",
        "warning-fg": "rgb(var(--warning-fg) / <alpha-value>)",
        success: "rgb(var(--success) / <alpha-value>)",
        "success-fg": "rgb(var(--success-fg) / <alpha-value>)",
        badge: "rgb(var(--badge) / <alpha-value>)",
        "badge-fg": "rgb(var(--badge-fg) / <alpha-value>)"
      },
      fontFamily: {
        sans: ["Inter", ...fontFamily.sans]
      }
    }
  }
};
