import { createContext, useContext, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface IntelligenceSlotContextValue {
  container: HTMLElement | null;
  setOccupied: (occupied: boolean) => void;
}

const IntelligenceSlotContext = createContext<IntelligenceSlotContextValue | null>(null);

export function IntelligenceSlotProvider({
  container,
  onOccupiedChange,
  children,
}: {
  container: HTMLElement | null;
  onOccupiedChange: (occupied: boolean) => void;
  children: ReactNode;
}) {
  return (
    <IntelligenceSlotContext.Provider value={{ container, setOccupied: onOccupiedChange }}>
      {children}
    </IntelligenceSlotContext.Provider>
  );
}

// Returns a portal that mounts `node`'s DOM output into AppLayout's
// Intelligence column, while keeping `node` itself in the CALLING
// component's own React tree -- e.g. DeskView's CopilotKitProvider. React
// context follows the React tree, not the DOM tree: lifting `node` up
// through state (the previous design) re-creates it as a child of
// whatever owns that state, silently losing any context the caller's
// subtree provided. A portal is the one React primitive built for exactly
// this -- "render here in the tree, but mount there in the DOM."
//
// Call once from a page that owns the Intelligence column's content for
// its whole mount, and render the returned node somewhere in its own JSX
// (e.g. `const portal = useIntelligenceSlot(<DeskActivityRail/>); return
// <>{portal}<main>...</main></>`). Returns null until AppLayout's target
// DOM node exists. Deliberately not designed for content that changes
// across a page's own re-renders -- the effect below runs once per
// mount/unmount, not on every `node` identity change, since every current
// and planned consumer pushes one static element for its entire lifetime.
export function useIntelligenceSlot(node: ReactNode): ReactNode {
  const ctx = useContext(IntelligenceSlotContext);
  if (!ctx) {
    throw new Error("useIntelligenceSlot must be used within an IntelligenceSlotProvider (AppLayout)");
  }
  const { container, setOccupied } = ctx;
  useEffect(() => {
    setOccupied(true);
    return () => setOccupied(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-once by design, see comment above
  }, [setOccupied]);
  if (!container) return null;
  return createPortal(node, container);
}
