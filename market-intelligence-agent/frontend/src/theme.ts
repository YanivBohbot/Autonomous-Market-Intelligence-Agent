export type Theme = "light" | "dark";

const STORAGE_KEY = "mia-theme";

export function getTheme(): Theme {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export function setTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  // CopilotKit v2's prebuilt chat ships its own self-contained dark theme,
  // keyed on Tailwind's ":is(.dark *)" ancestor-class selector -- unrelated
  // to our own data-theme attribute. Toggling both keeps the chat in sync
  // with the rest of the app.
  document.documentElement.classList.toggle("dark", theme === "dark");
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Private browsing / storage disabled -- the toggle still works for
    // the current page load, it just won't persist across reloads.
  }
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}
