import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { HoldingsStrip } from "./HoldingsStrip";

const positions = [{ ticker: "NVDA", weight_pct: 57.5 }, { ticker: "BND", weight_pct: 42.5 }];

describe("HoldingsStrip", () => {
  it("selects and unselects a position", () => {
    const onSelect = vi.fn();
    const { rerender } = render(<HoldingsStrip positions={positions} selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /NVDA/ }));
    expect(onSelect).toHaveBeenLastCalledWith("NVDA");
    rerender(<HoldingsStrip positions={positions} selected="NVDA" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: /NVDA/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /NVDA/ }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("renders nothing without positions", () => {
    const { container } = render(<HoldingsStrip positions={[]} selected={null} onSelect={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
