import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TickerNewsList } from "./TickerNewsList";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "ticker_news" }> = {
  type: "ticker_news",
  items: [
    { title: "Apple stock ticks up", summary: "Shares rose 1%.", source: "Reuters",
      url: "https://finance.yahoo.com/b", published_at: "2026-09-27T10:00:00Z" },
  ],
};

describe("TickerNewsList", () => {
  it("shows the headline as a link to the article", () => {
    render(<TickerNewsList display={display} />);
    const link = screen.getByRole("link", { name: /Apple stock ticks up/ });
    expect(link).toHaveAttribute("href", "https://finance.yahoo.com/b");
  });

  it("shows the source", () => {
    render(<TickerNewsList display={display} />);
    expect(screen.getByText("Reuters")).toBeInTheDocument();
  });
});
