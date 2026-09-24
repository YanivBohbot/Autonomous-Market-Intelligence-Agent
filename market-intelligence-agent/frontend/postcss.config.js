import postcss from "postcss";
import tailwindcss from "tailwindcss";
import autoprefixer from "autoprefixer";

// Tailwind v3 processes our own CSS only. CopilotKit ships precompiled
// Tailwind v4 CSS (native @layer, imported by its own JS), which Tailwind v3
// rejects ("`@layer base` is used but no matching `@tailwind base`").
const tailwindForAppCss = () => {
  const tailwind = postcss([tailwindcss()]);
  return {
    postcssPlugin: "tailwindcss-app-css-only",
    async Once(root, { result }) {
      const file = root.source?.input.file ?? "";
      if (file.includes("node_modules")) return;
      // Processing a Root runs in place; forward Tailwind's dependency
      // messages so Vite still reloads on content changes.
      const out = await tailwind.process(root, { ...result.opts, from: file });
      result.messages.push(...out.messages);
    },
  };
};
tailwindForAppCss.postcss = true;

export default {
  plugins: [tailwindForAppCss(), autoprefixer()],
};
