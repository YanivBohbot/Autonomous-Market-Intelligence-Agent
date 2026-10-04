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
