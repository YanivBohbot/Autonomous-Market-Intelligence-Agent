import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScreenshotCard } from "./ScreenshotCard";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "screenshot" }> = { type: "screenshot", url: "/workspace/screenshots/evidence.png" };

describe("ScreenshotCard", () => {
  it("renders an image pointing at the workspace route", () => {
    render(<ScreenshotCard display={display} />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/workspace/screenshots/evidence.png");
  });
});
