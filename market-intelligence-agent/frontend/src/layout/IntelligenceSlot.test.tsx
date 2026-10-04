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
});
