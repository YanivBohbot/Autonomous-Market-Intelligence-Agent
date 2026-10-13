import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { WatchlistAlertsCard } from "./WatchlistAlertsCard";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "watchlist_alerts" }> = {
  type: "watchlist_alerts", near_pct: 5, unpriced: ["XXXX"],
  rows: [
    { client: "Ann Lee", ticker: "TSLA", company: "Tesla", price: 460, alert_price: 450, direction: "above", status: "triggered", distance_pct: 2.22 },
    { client: "Bob Ray", ticker: "NVDA", company: "NVIDIA", price: 205, alert_price: 200, direction: "below", status: "near", distance_pct: 2.5 },
  ],
};

describe("WatchlistAlertsCard", () => {
  it("shows a status badge, the alert and the distance for each row", () => {
    render(<WatchlistAlertsCard display={display} />);
    expect(screen.getByText("Triggered")).toBeInTheDocument();
    expect(screen.getByText("Near")).toBeInTheDocument();
    expect(screen.getByText(/Ann Lee/)).toBeInTheDocument();
    expect(screen.getByText(/above \$450.00/)).toBeInTheDocument();
    expect(screen.getByText("+2.2%")).toBeInTheDocument();
    expect(screen.getByText(/No price for XXXX/)).toBeInTheDocument();
  });
});
