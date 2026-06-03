import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: "#0a0e14",
          panel: "#0f1620",
          border: "#1c2733",
          text: "#c9d4e0",
          muted: "#6b7a8d",
          accent: "#34d399", // signal green
          "accent-dim": "#1a6b4a",
          warn: "#fbbf24", // amber: awaiting approval
          "warn-dim": "#6b4f0a",
          danger: "#f87171", // red: reject/error
          "danger-dim": "#6b1a1a",
          user: "#1e3a5f",
          "user-border": "#2563eb",
        },
      },
      fontFamily: {
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
