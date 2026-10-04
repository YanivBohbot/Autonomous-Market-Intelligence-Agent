import { createContext, useContext, useState, type ReactNode } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { IntelligenceSlotProvider, useIntelligenceSlot } from "./IntelligenceSlot";

function Pusher({ text }: { text: string }) {
  const portal = useIntelligenceSlot(<div data-testid="pushed">{text}</div>);
  return <>{portal}</>;
}

function Harness({ children }: { children: ReactNode }) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [occupied, setOccupied] = useState(false);
  return (
    <>
      <IntelligenceSlotProvider container={container} onOccupiedChange={setOccupied}>
        {children}
      </IntelligenceSlotProvider>
      <div ref={setContainer} data-testid="slot-target" />
      <div data-testid="occupied">{String(occupied)}</div>
    </>
  );
}

describe("IntelligenceSlot", () => {
  it("renders pushed content into the target DOM node", () => {
    render(
      <Harness>
        <Pusher text="hello" />
      </Harness>,
    );
    expect(screen.getByTestId("pushed")).toHaveTextContent("hello");
    expect(screen.getByTestId("slot-target")).toContainElement(screen.getByTestId("pushed"));
  });

  it("marks the slot occupied while content is pushed, and clears it on unmount", () => {
    function Wrapper({ show }: { show: boolean }) {
      return <Harness>{show && <Pusher text="hello" />}</Harness>;
    }
    const { rerender } = render(<Wrapper show={true} />);
    expect(screen.getByTestId("occupied")).toHaveTextContent("true");
    expect(screen.getByTestId("pushed")).toBeInTheDocument();
    rerender(<Wrapper show={false} />);
    expect(screen.getByTestId("occupied")).toHaveTextContent("false");
    expect(screen.queryByTestId("pushed")).not.toBeInTheDocument();
  });

  it("does not leak the first pusher's content once a second pusher mounts in its place", () => {
    // key forces a real unmount+mount, matching how React Router swaps in a
    // genuinely different route component (DeskView vs ComingSoonPage) --
    // without it React would just re-render the same Pusher instance with
    // new props, never re-running the mount-once effect this hook relies on.
    function Wrapper({ which }: { which: "a" | "b" }) {
      return <Harness>{which === "a" ? <Pusher key="a" text="first" /> : <Pusher key="b" text="second" />}</Harness>;
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

  it("content rendered through the slot still sees context from where it was created, not where its DOM lands", () => {
    // This is the regression this hook exists to prevent: DeskActivityRail
    // is created inside DeskView's CopilotKitProvider, but AppLayout's
    // Intelligence column is a DOM sibling of that provider, not a React
    // descendant of it. A portal keeps the pushed element in its creator's
    // React tree (so it still sees CopilotKitProvider's context) while its
    // DOM output moves to AppLayout's target node. Lifting the element
    // through state instead -- the previous, broken design -- re-creates it
    // as a child of whatever rendered the state, losing that context.
    const AncestorContext = createContext("default");

    function ContextReader() {
      const value = useContext(AncestorContext);
      return <div data-testid="context-value">{value}</div>;
    }

    function PusherUnderAncestor() {
      const portal = useIntelligenceSlot(<ContextReader />);
      return <>{portal}</>;
    }

    function HarnessWithAncestorContext() {
      const [container, setContainer] = useState<HTMLDivElement | null>(null);
      const [, setOccupied] = useState(false);
      return (
        <>
          <AncestorContext.Provider value="from-ancestor">
            <IntelligenceSlotProvider container={container} onOccupiedChange={setOccupied}>
              <PusherUnderAncestor />
            </IntelligenceSlotProvider>
          </AncestorContext.Provider>
          <div ref={setContainer} data-testid="slot-target" />
        </>
      );
    }

    render(<HarnessWithAncestorContext />);
    expect(screen.getByTestId("context-value")).toHaveTextContent("from-ancestor");
  });
});
