import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("renders a chart container for non-empty points", () => {
    const { container } = render(
      <Sparkline points={[{ date: "2026-09-21", close: 338.98 }, { date: "2026-09-22", close: 340.0 }]} />,
    );
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });

  it("renders nothing for empty points", () => {
    const { container } = render(<Sparkline points={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
