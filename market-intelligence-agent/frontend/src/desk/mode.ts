export type ConsoleMode = "desk" | "classic";

const KEY = "mia.consoleMode";

export function loadMode(): ConsoleMode {
  try {
    return localStorage.getItem(KEY) === "classic" ? "classic" : "desk";
  } catch {
    return "desk";
  }
}

export function saveMode(mode: ConsoleMode): void {
  try {
    localStorage.setItem(KEY, mode);
  } catch {
    // Storage blocked (private window): the toggle still works for this tab.
  }
}
