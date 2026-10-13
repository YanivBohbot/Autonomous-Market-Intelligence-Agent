import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let interruptConfig: {
  render: (props: {
    interrupt: unknown;
    resolve: (value: unknown) => void;
    cancel: () => void;
  }) => React.ReactNode;
};

vi.mock("@copilotkit/react-core/v2", () => ({
  useInterrupt: (config: typeof interruptConfig) => {
    interruptConfig = config;
  },
}));
vi.mock("./ApprovalPanel", () => ({
  ApprovalPanel: () => <div>approval</div>,
}));
vi.mock("./ChoiceCard", async (orig) => ({
  ...(await orig<typeof import("./ChoiceCard")>()),
  ChoiceCard: ({ onSubmit }: { onSubmit: (a: unknown) => void }) => (
    <button onClick={() => onSubmit({ selected: ["1"], other: null })}>choice</button>
  ),
}));

import { useDeskInterrupt } from "./useDeskInterrupt";

function Harness({ onPendingChange }: { onPendingChange: (pending: boolean) => void }) {
  useDeskInterrupt(onPendingChange);
  return null;
}

describe("useDeskInterrupt", () => {
  it("reports typed approval mount and unmount to the composer gate", () => {
    const onPendingChange = vi.fn();
    render(<Harness onPendingChange={onPendingChange} />);

    const card = render(
      interruptConfig.render({
        interrupt: null,
        resolve: vi.fn(),
        cancel: vi.fn(),
      }),
    );
    expect(onPendingChange).toHaveBeenLastCalledWith(true);

    card.unmount();
    expect(onPendingChange).toHaveBeenLastCalledWith(false);
  });

  it("renders the choice card for user_choice interrupts and resumes with the answer", () => {
    render(<Harness onPendingChange={vi.fn()} />);
    const resolve = vi.fn();
    const card = render(
      interruptConfig.render({
        interrupt: { metadata: { langgraph: { raw: { type: "user_choice", question: "Q", multi: false, allow_other: false,
          options: [{ id: "0", label: "A" }, { id: "1", label: "B" }] } } } },
        resolve,
        cancel: vi.fn(),
      }),
    );
    fireEvent.click(card.getByText("choice"));
    expect(resolve).toHaveBeenCalledWith({ selected: ["1"], other: null });
    expect(card.queryByText("approval")).toBeNull();
  });
});
