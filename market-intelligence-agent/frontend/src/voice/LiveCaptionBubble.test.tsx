import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveCaptionBubble } from "./LiveCaptionBubble";

describe("LiveCaptionBubble", () => {
  it("renders the live text with an accessible label", () => {
    render(<LiveCaptionBubble text="Which clients are" />);
    const bubble = screen.getByRole("status", { name: "You are speaking" });
    expect(bubble).toHaveTextContent("Which clients are");
  });

  it("renders nothing for empty text", () => {
    const { container } = render(<LiveCaptionBubble text="" />);
    expect(container).toBeEmptyDOMElement();
  });
});
