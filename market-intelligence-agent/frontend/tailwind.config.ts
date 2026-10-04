import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Values live in CSS variables (src/index.css): light theme on
        // :root, dark theme under [data-theme="dark"]. Every component
        // keeps using bg-terminal-bg etc. unchanged -- the toggle in
        // Header.tsx just flips which palette those variables resolve to.
        terminal: {
          bg: "rgb(var(--terminal-bg) / <alpha-value>)",
          panel: "rgb(var(--terminal-panel) / <alpha-value>)",
          border: "rgb(var(--terminal-border) / <alpha-value>)",
          text: "rgb(var(--terminal-text) / <alpha-value>)",
          muted: "rgb(var(--terminal-muted) / <alpha-value>)",
          accent: "rgb(var(--terminal-accent) / <alpha-value>)",
          "accent-dim": "rgb(var(--terminal-accent-dim) / <alpha-value>)",
          warn: "rgb(var(--terminal-warn) / <alpha-value>)",
          "warn-dim": "rgb(var(--terminal-warn-dim) / <alpha-value>)",
          danger: "rgb(var(--terminal-danger) / <alpha-value>)",
          "danger-dim": "rgb(var(--terminal-danger-dim) / <alpha-value>)",
          user: "rgb(var(--terminal-user) / <alpha-value>)",
          "user-border": "rgb(var(--terminal-user-border) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        "glow-green": "0 0 12px rgba(52,211,153,0.25)",
        "glow-amber": "0 0 12px rgba(251,191,36,0.25)",
        "glow-red": "0 0 12px rgba(248,113,113,0.25)",
        "inner-glow": "inset 0 1px 0 rgba(255,255,255,0.04)",
      },
      keyframes: {
        "fade-in-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "blink-caret": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
        "pulse-dot": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(52,211,153,0.4)" },
          "50%": { boxShadow: "0 0 0 4px rgba(52,211,153,0)" },
        },
        "slide-in-right": {
          "0%": { opacity: "0", transform: "translateX(12px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
      },
      animation: {
        "fade-in-up": "fade-in-up 0.2s ease-out forwards",
        "blink-caret": "blink-caret 1s step-start infinite",
        "pulse-dot": "pulse-dot 2s ease-in-out infinite",
        "slide-in-right": "slide-in-right 0.18s ease-out forwards",
      },
    },
  },
  plugins: [],
} satisfies Config;
