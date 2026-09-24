import { describe, it, expect, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";

type Subscriber = {
  onEvent?: (p: { event: unknown }) => void;
  onRunFailed?: (p: { error: Error }) => void;
};
const subscribers: Subscriber[] = [];
const fakeAgent = {
  subscribe: (s: Subscriber) => {
    subscribers.push(s);
    return { unsubscribe: () => undefined };
  },
};
vi.mock("@copilotkit/react-core/v2", () => ({ useAgent: () => ({ agent: fakeAgent }) }));

import { DeskActivityRail } from "./DeskActivityRail";

describe("DeskActivityRail", () => {
  it("shows a transport failure (HTTP error, dropped stream) as an error row", () => {
    // These never arrive as a RUN_ERROR event: @ag-ui/client reports them
    // through onRunFailed only.
    render(<DeskActivityRail />);
    act(() => subscribers[subscribers.length - 1]?.onRunFailed?.({ error: new Error("HTTP 404: Not Found") }));
    expect(screen.getByText(/error · HTTP 404: Not Found/)).toBeInTheDocument();
  });
});
