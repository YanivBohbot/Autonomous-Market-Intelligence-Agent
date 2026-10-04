# Navigation Layout (chantier 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `Header.tsx`'s flat 3-link nav with a 5-section `AppLayout` (Briefing/Clients/Recherche/Rapports/Données) in a 3-column shape (nav | content | Intelligence), wiring in the two sections that already have real content (Recherche = today's Market Desk, Données = today's `/data` page) and placeholders for the other three.

**Architecture:** A new `frontend/src/layout/` module owns the layout: `AppLayout.tsx` (nav rail + top bar + Intelligence column, rendered once via `<Route element={<AppLayout/>}>` wrapping the 5 nested routes), `IntelligenceSlot.tsx` (a React context letting whichever page is mounted push its own content into the right column), `ComingSoonPage.tsx` (one reusable placeholder for the three sections with no content yet). `Header.tsx` is retired; its logic moves into `AppLayout`. `DeskView.tsx` is the only existing page that changes behavior — it now pushes `DeskActivityRail` through the slot instead of rendering it directly.

**Tech Stack:** React 19, TypeScript, react-router-dom v7, Tailwind (existing `terminal-*` design tokens), Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-04-nav-shell-design.md`

## Global Constraints

- No new backend endpoints or agent logic — nothing under `app/` changes in this chantier.
- The existing frontend Vitest suite (108 tests passing before this chantier) must stay green throughout and at the end.
- TDD: write the failing test before the implementation in every task.
- Reuse the existing `terminal-*` Tailwind tokens and `font-mono` visual language already established project-wide — no new design system.

## Review Focus

- Moving the theme toggle from `Header.tsx` into `AppLayout` must not silently break it (it's a relocation, not a new feature, and relocations are exactly where a working feature quietly stops being wired up) — covered in Task 3.
- `/` → `/recherche` must redirect with `replace` so the back button doesn't loop on an unreachable `/` — covered in Task 3 and Task 4.
- Navigating from Recherche to any other section must clear the Intelligence column rather than leaving the previous page's agent-activity content stuck on screen — covered in Task 1 and Task 5.
- No nav link anywhere points at `/classic` (an explicit spec decision, easy to accidentally reintroduce while editing nav markup) — covered in Task 3, re-checked in Task 4.
- Clicking "+ New session" while on a route that doesn't use `threadId` (e.g. `/data`, `/briefing`) must not crash — covered in Task 3.

---

### Task 1: Intelligence slot primitive

**Files:**
- Create: `frontend/src/layout/IntelligenceSlot.tsx`
- Test: `frontend/src/layout/IntelligenceSlot.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks (first task).
- Produces: `IntelligenceSlotProvider({children, onContentChange}: {children: ReactNode; onContentChange: (node: ReactNode | null) => void})` and `useIntelligenceSlot(node: ReactNode): void`, both exported from `frontend/src/layout/IntelligenceSlot.tsx`. `AppLayout` (Task 3) renders `IntelligenceSlotProvider` with `onContentChange` wired to its own state. `DeskView` (Task 5) calls `useIntelligenceSlot(<DeskActivityRail/>)`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/layout/IntelligenceSlot.test.tsx
import { useState, type ReactNode } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { IntelligenceSlotProvider, useIntelligenceSlot } from "./IntelligenceSlot";

function Pusher({ text }: { text: string }) {
  useIntelligenceSlot(<div data-testid="pushed">{text}</div>);
  return null;
}

function Harness({ children }: { children: ReactNode }) {
  const [content, setContent] = useState<ReactNode | null>(null);
  return (
    <IntelligenceSlotProvider onContentChange={setContent}>
      {children}
      <div data-testid="slot-output">{content}</div>
    </IntelligenceSlotProvider>
  );
}

describe("IntelligenceSlot", () => {
  it("renders pushed content into the slot output", () => {
    render(
      <Harness>
        <Pusher text="hello" />
      </Harness>,
    );
    expect(screen.getByTestId("pushed")).toHaveTextContent("hello");
  });

  it("clears the slot when the pushing component unmounts", () => {
    function Wrapper({ show }: { show: boolean }) {
      return <Harness>{show && <Pusher text="hello" />}</Harness>;
    }
    const { rerender } = render(<Wrapper show={true} />);
    expect(screen.getByTestId("pushed")).toBeInTheDocument();
    rerender(<Wrapper show={false} />);
    expect(screen.queryByTestId("pushed")).not.toBeInTheDocument();
  });

  it("does not leak the first pusher's content once a second pusher mounts in its place", () => {
    function Wrapper({ which }: { which: "a" | "b" }) {
      return <Harness>{which === "a" ? <Pusher text="first" /> : <Pusher text="second" />}</Harness>;
    }
    const { rerender } = render(<Wrapper which="a" />);
    expect(screen.getByTestId("pushed")).toHaveTextContent("first");
    rerender(<Wrapper which="b" />);
    expect(screen.getByTestId("pushed")).toHaveTextContent("second");
    expect(screen.queryByText("first")).not.toBeInTheDocument();
  });

  it("throws a clear error when used outside an IntelligenceSlotProvider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Pusher text="hello" />)).toThrow(/IntelligenceSlotProvider/);
    spy.mockRestore();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/layout/IntelligenceSlot.test.tsx` (from `frontend/`)
Expected: FAIL — `./IntelligenceSlot` does not exist yet.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/layout/IntelligenceSlot.tsx
import { createContext, useContext, useEffect, type ReactNode } from "react";

interface IntelligenceSlotContextValue {
  setContent: (node: ReactNode | null) => void;
}

const IntelligenceSlotContext = createContext<IntelligenceSlotContextValue | null>(null);

export function IntelligenceSlotProvider({
  children,
  onContentChange,
}: {
  children: ReactNode;
  onContentChange: (node: ReactNode | null) => void;
}) {
  return <IntelligenceSlotContext.Provider value={{ setContent: onContentChange }}>{children}</IntelligenceSlotContext.Provider>;
}

// Call once from a page that owns the Intelligence column's content for its
// whole mount (e.g. DeskView pushes <DeskActivityRail/>). Deliberately not
// designed for content that changes across a page's own re-renders -- the
// effect below runs once per mount/unmount, not on every `node` identity
// change, since every current and planned consumer pushes one static
// element for its entire lifetime.
export function useIntelligenceSlot(node: ReactNode): void {
  const ctx = useContext(IntelligenceSlotContext);
  if (!ctx) {
    throw new Error("useIntelligenceSlot must be used within an IntelligenceSlotProvider (AppLayout)");
  }
  const { setContent } = ctx;
  useEffect(() => {
    setContent(node);
    return () => setContent(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-once by design, see comment above
  }, [setContent]);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/layout/IntelligenceSlot.test.tsx`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/layout/IntelligenceSlot.tsx frontend/src/layout/IntelligenceSlot.test.tsx
git commit -m "feat(layout): add IntelligenceSlot context for the nav layout's right column"
```

---

### Task 2: ComingSoonPage placeholder

**Files:**
- Create: `frontend/src/layout/ComingSoonPage.tsx`
- Test: `frontend/src/layout/ComingSoonPage.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ComingSoonPage({title, description}: {title: string; description: string})`, exported from `frontend/src/layout/ComingSoonPage.tsx`. Used by `App.tsx` (Task 4) for the `/briefing`, `/clients` and `/rapports` routes.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/layout/ComingSoonPage.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ComingSoonPage } from "./ComingSoonPage";

describe("ComingSoonPage", () => {
  it("renders the given title and description", () => {
    render(<ComingSoonPage title="Briefing" description="Résumé quotidien à venir." />);
    expect(screen.getByRole("heading", { name: "Briefing" })).toBeInTheDocument();
    expect(screen.getByText("Résumé quotidien à venir.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/layout/ComingSoonPage.test.tsx`
Expected: FAIL — `./ComingSoonPage` does not exist yet.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/layout/ComingSoonPage.tsx
interface ComingSoonPageProps {
  title: string;
  description: string;
}

export function ComingSoonPage({ title, description }: ComingSoonPageProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
      <h1 className="font-mono text-lg font-semibold text-terminal-text">{title}</h1>
      <p className="max-w-md font-mono text-sm text-terminal-muted">{description}</p>
      <span className="mt-2 rounded border border-terminal-border bg-terminal-panel px-3 py-1 font-mono text-[10px] uppercase tracking-widest text-terminal-muted">
        Bientôt disponible
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/layout/ComingSoonPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/layout/ComingSoonPage.tsx frontend/src/layout/ComingSoonPage.test.tsx
git commit -m "feat(layout): add the shared ComingSoonPage placeholder"
```

---

### Task 3: AppLayout — nav rail, top bar, Intelligence column; retire Header

**Files:**
- Create: `frontend/src/layout/AppLayout.tsx`
- Test: `frontend/src/layout/AppLayout.test.tsx`
- Delete: `frontend/src/components/Header.tsx` (no test file exists for it today — nothing to delete there)

**Interfaces:**
- Consumes: `IntelligenceSlotProvider` from Task 1 (`../layout/IntelligenceSlot`); `getHealth` from `../lib/api` (unchanged, same as `Header.tsx` used); `getTheme`/`toggleTheme`/`Theme` from `../theme` (unchanged, same as `Header.tsx` used).
- Produces: `AppLayout({threadId, onNewSession}: {threadId: string; onNewSession: () => void})`, exported from `frontend/src/layout/AppLayout.tsx`. Renders `<Outlet/>` for the active route's content. `App.tsx` (Task 4) uses it as `<Route element={<AppLayout threadId={threadId} onNewSession={onNewSession} />}>` wrapping the 5 nested routes.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/layout/AppLayout.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "./AppLayout";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppLayout threadId="t1" onNewSession={() => undefined} />}>
          <Route path="/" element={<Navigate to="/recherche" replace />} />
          <Route path="/briefing" element={<div>briefing page</div>} />
          <Route path="/clients" element={<div>clients page</div>} />
          <Route path="/recherche" element={<div>recherche page</div>} />
          <Route path="/rapports" element={<div>rapports page</div>} />
          <Route path="/data" element={<div>data page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppLayout", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok", version: "1.2.3" }) }),
    );
  });

  it("shows all 5 nav links with the right labels and hrefs", () => {
    renderAt("/recherche");
    expect(screen.getByRole("link", { name: "Briefing" })).toHaveAttribute("href", "/briefing");
    expect(screen.getByRole("link", { name: "Clients" })).toHaveAttribute("href", "/clients");
    expect(screen.getByRole("link", { name: "Recherche" })).toHaveAttribute("href", "/recherche");
    expect(screen.getByRole("link", { name: "Rapports" })).toHaveAttribute("href", "/rapports");
    expect(screen.getByRole("link", { name: "Données" })).toHaveAttribute("href", "/data");
  });

  it("has no nav link to /classic", () => {
    renderAt("/recherche");
    expect(screen.queryByRole("link", { name: /classic/i })).not.toBeInTheDocument();
  });

  it("marks the active route's nav link and not the others", () => {
    renderAt("/rapports");
    expect(screen.getByRole("link", { name: "Rapports" })).toHaveClass("text-terminal-accent");
    expect(screen.getByRole("link", { name: "Recherche" })).not.toHaveClass("text-terminal-accent");
  });

  it("redirects / to /recherche", () => {
    renderAt("/");
    expect(screen.getByText("recherche page")).toBeInTheDocument();
  });

  it("toggling the theme button updates the document's data-theme attribute", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/recherche");
    document.documentElement.setAttribute("data-theme", "light");
    await user.click(screen.getByRole("button", { name: /dark/i }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("shows the session id and calls onNewSession when + New session is clicked, even on a non-chat route", async () => {
    const onNewSession = vi.fn();
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/data"]}>
        <Routes>
          <Route element={<AppLayout threadId="t1" onNewSession={onNewSession} />}>
            <Route path="/data" element={<div>data page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("t1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(onNewSession).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/layout/AppLayout.test.tsx`
Expected: FAIL — `./AppLayout` does not exist yet.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/layout/AppLayout.tsx
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getHealth } from "../lib/api";
import { getTheme, toggleTheme, type Theme } from "../theme";
import { IntelligenceSlotProvider } from "./IntelligenceSlot";

interface AppLayoutProps {
  threadId: string;
  onNewSession: () => void;
}

const NAV_ITEMS = [
  { to: "/briefing", label: "Briefing" },
  { to: "/clients", label: "Clients" },
  { to: "/recherche", label: "Recherche" },
  { to: "/rapports", label: "Rapports" },
  { to: "/data", label: "Données" },
];

const emptyIntelligence = (
  <aside className="flex h-full w-64 flex-none flex-col items-center justify-center border-l border-terminal-border bg-terminal-panel">
    <span className="font-mono text-[10px] text-terminal-muted">Aucune activité</span>
  </aside>
);

export function AppLayout({ threadId, onNewSession }: AppLayoutProps) {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string>("");
  const [theme, setThemeState] = useState<Theme>("light");
  const [intelligenceContent, setIntelligenceContent] = useState<ReactNode | null>(null);

  useEffect(() => {
    setThemeState(getTheme());
  }, []);

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const h = await getHealth();
        if (active) {
          setHealthy(h.status === "ok" || h.status === "healthy");
          setVersion(h.version);
        }
      } catch {
        if (active) setHealthy(false);
      }
    };
    check();
    const id = setInterval(check, 10000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const dotClass =
    healthy === null ? "bg-terminal-muted" : healthy ? "bg-terminal-accent animate-pulse-dot shadow-glow-green" : "bg-terminal-danger shadow-glow-red";

  return (
    <div className="flex h-full flex-col bg-terminal-bg">
      <header className="scan-lines flex items-center justify-between border-b border-terminal-border bg-terminal-panel px-4 py-2.5 shadow-inner-glow">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${dotClass}`} />
            <span className="font-mono text-sm font-semibold text-terminal-muted">MIA · Dev Console</span>
          </div>
          {version && (
            <span className="rounded border border-terminal-border px-1.5 py-0.5 font-mono text-[10px] text-terminal-muted">v{version}</span>
          )}
          {healthy === false && (
            <span className="rounded bg-terminal-danger/10 px-2 py-0.5 font-mono text-[10px] text-terminal-danger">backend offline</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 rounded border border-terminal-border bg-terminal-bg px-2.5 py-1">
            <span className="font-mono text-[10px] text-terminal-muted">session</span>
            <span className="font-mono text-[10px] text-terminal-accent">{threadId}</span>
          </div>
          <button
            onClick={onNewSession}
            className="rounded border border-terminal-border bg-terminal-bg px-3 py-1 font-mono text-xs text-terminal-muted transition-all hover:border-terminal-accent hover:text-terminal-accent"
          >
            + New session
          </button>
          <button
            type="button"
            onClick={() => setThemeState(toggleTheme())}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            className="rounded border border-terminal-border bg-terminal-bg px-2.5 py-1 font-mono text-xs text-terminal-muted transition-all hover:border-terminal-accent hover:text-terminal-accent"
          >
            {theme === "dark" ? "☀ Light" : "🌙 Dark"}
          </button>
          <button
            type="button"
            title="Profil (bientôt disponible)"
            className="rounded border border-terminal-border bg-terminal-bg px-2.5 py-1 font-mono text-xs text-terminal-muted"
          >
            Profil
          </button>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav className="flex w-48 flex-none flex-col gap-1 border-r border-terminal-border bg-terminal-panel p-2">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded px-3 py-2 font-mono text-xs transition-colors ${
                  isActive ? "bg-terminal-accent/15 text-terminal-accent" : "text-terminal-muted hover:text-terminal-text"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <IntelligenceSlotProvider onContentChange={setIntelligenceContent}>
          <main className="flex min-h-0 min-w-0 flex-1 flex-col">
            <Outlet />
          </main>
        </IntelligenceSlotProvider>
        {intelligenceContent ?? emptyIntelligence}
      </div>
    </div>
  );
}
```

Delete `frontend/src/components/Header.tsx` in this step (its logic above fully replaces it; nothing else in the codebase imports it after Task 4 rewires `App.tsx` — Task 4 removes the import).

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/layout/AppLayout.test.tsx`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/layout/AppLayout.tsx frontend/src/layout/AppLayout.test.tsx
git rm frontend/src/components/Header.tsx
git commit -m "feat(layout): add AppLayout (5-section nav + Intelligence column), retire Header"
```

---

### Task 4: Wire routing in App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `AppLayout` (Task 3, `./layout/AppLayout`), `ComingSoonPage` (Task 2, `./layout/ComingSoonPage`), existing `DeskView`, `DataPage`.
- Produces: the live route table other chantiers build on (`/briefing`, `/clients`, `/recherche`, `/rapports`, `/data` under `AppLayout`; `/classic` standalone).

- [ ] **Step 1: Update the failing/changed tests first**

Replace `frontend/src/App.test.tsx` with:

```tsx
// frontend/src/App.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("./desk/DeskView", () => ({
  DeskView: ({ threadId }: { threadId: string }) => <div data-testid="desk-view">{threadId}</div>,
}));

import App from "./App";

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}>{<App />}</MemoryRouter>);
}

describe("App routing", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok", version: "1.2.3" }),
      }),
    );
  });

  it("/ redirects to /recherche", () => {
    renderAt("/");
    expect(screen.getByTestId("desk-view")).toBeInTheDocument();
  });

  it("/recherche renders Market Desk", () => {
    renderAt("/recherche");
    expect(screen.getByTestId("desk-view")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/ask the agent/i)).not.toBeInTheDocument();
  });

  it("/classic renders the classic chat", () => {
    renderAt("/classic");
    expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument();
    expect(screen.queryByTestId("desk-view")).not.toBeInTheDocument();
  });

  it("/classic has no AppLayout nav (it's outside the layout)", () => {
    renderAt("/classic");
    expect(screen.queryByRole("link", { name: "Recherche" })).not.toBeInTheDocument();
  });

  it("the three not-yet-built sections render ComingSoonPage without crashing", () => {
    renderAt("/briefing");
    expect(screen.getByText(/bientôt disponible/i)).toBeInTheDocument();
    renderAt("/clients");
    expect(screen.getByText(/bientôt disponible/i)).toBeInTheDocument();
    renderAt("/rapports");
    expect(screen.getByText(/bientôt disponible/i)).toBeInTheDocument();
  });

  it("New session gives the desk a new thread id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/recherche");
    const before = screen.getByTestId("desk-view").textContent;
    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(screen.getByTestId("desk-view").textContent).not.toBe(before);
  });

  it("Market Desk runs on its own thread, never Classic's", () => {
    renderAt("/classic");
    const classicThread = screen.getByText(/^web_session_/).textContent;
    renderAt("/recherche");
    expect(screen.getByTestId("desk-view").textContent).not.toBe(classicThread);
  });

  it("New session clears Classic's chat history", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/classic");

    await user.type(screen.getByPlaceholderText(/ask the agent/i), "hello world");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("hello world")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(screen.queryByText("hello world")).not.toBeInTheDocument();
  });
});
```

Note what changed from the previous version: the old "the nav link to Classic has the right href" test is **removed** — Classic intentionally has no nav link anywhere now (spec decision 7). A new test confirms that absence instead. Paths that used to assert against `/` now use `/recherche` directly, plus one dedicated redirect test keeps `/` covered.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/App.test.tsx` (from `frontend/`)
Expected: FAIL — `App.tsx` still renders the old flat `Header` + 3 routes, so `/briefing`, `/clients`, `/rapports` 404 and `/recherche` doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Replace the whole file (`frontend/src/App.tsx`) with — `ClassicChat` is copied verbatim from the current file, only the imports and `App()` change:

```tsx
import { useState, useRef, type FormEvent, type KeyboardEvent } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "./layout/AppLayout";
import { ComingSoonPage } from "./layout/ComingSoonPage";
import { ChatPane } from "./components/ChatPane";
import { ActivityRail } from "./components/ActivityRail";
import { ApprovalCard } from "./components/ApprovalCard";
import { VoicePanel } from "./components/VoicePanel";
import { useChatStream } from "./hooks/useChatStream";
import { newThreadId } from "./lib/api";
import { DeskView } from "./desk/DeskView";
import { DataPage } from "./data/DataPage";

function ClassicChat({ threadId }: { threadId: string }) {
  const [input, setInput] = useState("");
  const [voiceOpen, setVoiceOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { messages, activity, streaming, pending, send, resolvePending } = useChatStream(threadId);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    submitQuery();
  }
  function submitQuery() {
    const q = input.trim();
    if (!q || streaming || pending) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    void send(q);
  }
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitQuery();
    }
  }
  function onTextareaChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }
  const inputDisabled = streaming || !!pending;

  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-hidden">
          <ChatPane messages={messages} streaming={streaming} />
        </div>
        {pending && (
          <div className="border-t border-terminal-border px-4 py-3">
            <ApprovalCard threadId={threadId} pending={pending} onResolved={(text, still) => resolvePending(text, still)} />
          </div>
        )}
        <div className="border-t border-terminal-border bg-terminal-panel">
          <form onSubmit={onSubmit} className="flex items-end gap-2 px-3 py-3">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={onTextareaChange}
              onKeyDown={onKeyDown}
              disabled={inputDisabled}
              placeholder="Ask the agent…"
              className="flex-1 resize-none overflow-hidden rounded-xl border border-terminal-border bg-terminal-bg px-3.5 py-2.5 font-mono text-sm text-terminal-text placeholder-terminal-muted outline-none transition-colors focus:border-terminal-accent/60 disabled:cursor-not-allowed disabled:opacity-50"
            />
            <div className="flex flex-none items-center gap-1.5 pb-0.5">
              <button type="submit" disabled={inputDisabled || !input.trim()} className="rounded-xl bg-terminal-accent px-4 py-2.5 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none">
                {streaming ? <span className="animate-pulse">…</span> : "Send"}
              </button>
              <button type="button" onClick={() => setVoiceOpen((v) => !v)} className={`rounded-xl border px-3 py-2.5 font-mono text-sm transition-all ${voiceOpen ? "border-terminal-accent/50 bg-terminal-accent/10 text-terminal-accent" : "border-terminal-border text-terminal-muted hover:border-terminal-accent/40 hover:text-terminal-text"}`} title="Toggle voice">
                🎤
              </button>
            </div>
          </form>
          <div className="px-4 pb-2">
            <span className="font-mono text-[10px] text-terminal-muted">Enter to send · Shift+Enter for newline</span>
          </div>
        </div>
        {voiceOpen && <VoicePanel threadId={threadId} />}
      </main>
      <ActivityRail activity={activity} />
    </div>
  );
}

export default function App() {
  const [threadId, setThreadId] = useState(newThreadId);

  function onNewSession() {
    setThreadId(newThreadId());
  }

  return (
    <div className="flex h-full flex-col bg-terminal-bg">
      <Routes>
        <Route element={<AppLayout threadId={threadId} onNewSession={onNewSession} />}>
          <Route path="/" element={<Navigate to="/recherche" replace />} />
          <Route
            path="/briefing"
            element={
              <ComingSoonPage
                title="Briefing"
                description="Résumé quotidien automatique : alertes de concentration, mouvements de marché notables, synthèse de l'agent. Arrive dans un prochain chantier."
              />
            }
          />
          <Route
            path="/clients"
            element={
              <ComingSoonPage
                title="Clients"
                description="Espace de travail par client : résumé, graphique, positions et chat scopé. Arrive dans un prochain chantier."
              />
            }
          />
          <Route path="/recherche" element={<DeskView key={threadId} threadId={`desk_${threadId}`} />} />
          <Route
            path="/rapports"
            element={
              <ComingSoonPage
                title="Rapports"
                description="Génération et historique des rapports clients (Excel/PDF/Word). Arrive dans un prochain chantier."
              />
            }
          />
          <Route path="/data" element={<DataPage />} />
        </Route>
        <Route path="/classic" element={<ClassicChat key={threadId} threadId={threadId} />} />
      </Routes>
    </div>
  );
}
```

Delete the old `import { Header } from "./components/Header";` line — `Header.tsx` no longer exists after Task 3.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/App.test.tsx`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(layout): wire the 5-section routing through AppLayout"
```

---

### Task 5: DeskView pushes its activity rail through the Intelligence slot

**Files:**
- Modify: `frontend/src/desk/DeskView.tsx`
- Modify: `frontend/src/desk/DeskView.test.tsx`

**Interfaces:**
- Consumes: `useIntelligenceSlot` (Task 1, `../layout/IntelligenceSlot`).
- Produces: nothing new consumed by later tasks — this is the last task in this chantier.

- [ ] **Step 1: Update the failing test first**

In `frontend/src/desk/DeskView.test.tsx`, add a mock for the new import alongside the existing mocks, and remove the now-unused `useAgent` mock entry (DeskActivityRail is passed to the mocked `useIntelligenceSlot`, which discards it without mounting it, so `useAgent` is never called in this test file anymore):

```tsx
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

const chatProps: Record<string, unknown>[] = [];
vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  CopilotChat: (props: Record<string, unknown>) => {
    chatProps.push(props);
    return null;
  },
  HttpAgent: class {},
  useRenderTool: () => undefined,
  useConfigureSuggestions: () => undefined,
}));
vi.mock("./useDeskInterrupt", () => ({ useDeskInterrupt: () => undefined }));
vi.mock("./displays/useToolDisplay", () => ({ useToolDisplay: () => undefined }));
vi.mock("../layout/IntelligenceSlot", () => ({ useIntelligenceSlot: () => undefined }));

import { DeskView } from "./DeskView";

describe("DeskView", () => {
  it("enables chat attachments with an onUpload handler", () => {
    render(<DeskView threadId="t1" />);
    const props = chatProps[chatProps.length - 1];
    const attachments = props.attachments as { enabled: boolean; onUpload: unknown };
    expect(attachments.enabled).toBe(true);
    expect(typeof attachments.onUpload).toBe("function");
  });

  it("includes the saved workspace path as attachment metadata the model can read", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ path: "uploads/ab12_report.pdf" }) }));
    render(<DeskView threadId="t1" />);
    const props = chatProps[chatProps.length - 1];
    const attachments = props.attachments as { onUpload: (f: File) => Promise<{ type: string; value: string; metadata?: Record<string, unknown> }> };
    const file = new File(["x"], "report.pdf", { type: "application/pdf" });
    const result = await attachments.onUpload(file);
    expect(result).toEqual({
      type: "url",
      value: "uploads/ab12_report.pdf",
      metadata: { filename: "report.pdf", note: "Read this with read_text_file at path uploads/ab12_report.pdf if relevant." },
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/desk/DeskView.test.tsx` (from `frontend/`)
Expected: FAIL — `../layout/IntelligenceSlot` doesn't exist as an import inside `DeskView.tsx` yet, and the mock for a module nothing imports is harmless but the real behavior (pushing through the slot) isn't implemented, so this step's purpose is confirming the test file itself is valid against the *old* `DeskView.tsx`; the meaningful check is Step 4 passing after Step 3.

- [ ] **Step 3: Write the implementation**

In `frontend/src/desk/DeskView.tsx`, add the import and call the hook, and simplify `DeskBody`'s JSX now that it has one child instead of two:

```tsx
import { useMemo } from "react";
import { CopilotChat, CopilotKitProvider, HttpAgent, useConfigureSuggestions } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { MARKET_DESK_AGENT_ID, MARKET_DESK_URL } from "./constants";
import { DeskActivityRail } from "./DeskActivityRail";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { useDeskInterrupt } from "./useDeskInterrupt";
import { useToolDisplay } from "./displays/useToolDisplay";
import { uploadToWorkspace } from "../lib/api";
import { useIntelligenceSlot } from "../layout/IntelligenceSlot";

// Market Desk: CopilotKit v2 talking AG-UI straight to FastAPI (no runtime).
// Remounted per thread by App (key={threadId}), so New session starts clean.
export function DeskView({ threadId }: { threadId: string }) {
  const agent = useMemo(() => new HttpAgent({ url: MARKET_DESK_URL }), []);
  return (
    <CopilotKitProvider
      agentId={MARKET_DESK_AGENT_ID}
      agents__unsafe_dev_only={{ [MARKET_DESK_AGENT_ID]: agent }}
      messageFilter={(messages) => messages.slice(-1)}
      showDevConsole={false}
      enableInspector={false}
    >
      <DeskBody threadId={threadId} />
    </CopilotKitProvider>
  );
}

function DeskBody({ threadId }: { threadId: string }) {
  useDeskInterrupt();
  useToolDisplay();
  // Pushed into AppLayout's Intelligence column (Task 1/3) instead of
  // rendered as a direct sibling -- DeskActivityRail itself is unchanged,
  // only where it mounts changes.
  useIntelligenceSlot(<DeskActivityRail />);
  useConfigureSuggestions({
    suggestions: [
      { title: "Portfolio value", message: "What is the total value of a client's portfolio?" },
      { title: "Stock price", message: "What is AAPL trading at?" },
      { title: "Concentration risk", message: "Are any clients over-concentrated in one stock?" },
    ],
  }, []);
  return (
    <main className="relative flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="pointer-events-none absolute inset-x-4 bottom-20 z-50 flex">
        <ThinkingIndicator />
      </div>
      <CopilotChat
        agentId={MARKET_DESK_AGENT_ID}
        threadId={threadId}
        className="h-full"
        input={{
          positioning: "static",
          className: "border-t border-terminal-border bg-terminal-panel px-3 py-3",
          textArea:
            "rounded-xl border border-terminal-border bg-terminal-bg px-3.5 py-2.5 font-mono text-sm text-terminal-text placeholder-terminal-muted outline-none transition-colors focus:border-terminal-accent/60",
          sendButton:
            "rounded-xl bg-terminal-accent px-4 py-2.5 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none",
        }}
        attachments={{
          enabled: true,
          maxSize: 20 * 1024 * 1024,
          onUpload: async (file) => {
            const { path } = await uploadToWorkspace(file);
            return {
              type: "url",
              value: path,
              metadata: { filename: file.name, note: `Read this with read_text_file at path ${path} if relevant.` },
            };
          },
        }}
      />
    </main>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/desk/DeskView.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full frontend suite**

Run: `npx vitest run` (from `frontend/`)
Expected: PASS, 108 previously-passing tests + this chantier's new tests (Tasks 1–5) all green, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx
git commit -m "feat(layout): DeskView pushes its activity rail through the Intelligence slot"
```
