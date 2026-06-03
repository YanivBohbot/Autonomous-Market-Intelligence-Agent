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
          warn: "#fbbf24", // amber: awaiting approval
          danger: "#f87171", // red: reject/error
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
