import { render } from "@testing-library/react";
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
});
