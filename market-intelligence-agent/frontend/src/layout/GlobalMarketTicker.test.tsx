import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getMarketTicker, type MarketTickerItem } from "../lib/api";
import { GlobalMarketTicker } from "./GlobalMarketTicker";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, getMarketTicker: vi.fn() };
});

const ITEMS: MarketTickerItem[] = [
  { symbol: "^GSPC", name: "S&P 500", price: 6810.2, change_pct: 1.25 },
  { symbol: "^IXIC", name: "Nasdaq", price: 22800.4, change_pct: -0.5 },
  { symbol: "^DJI", name: "Dow Jones", price: 47110.1, change_pct: 0 },
  { symbol: "^GDAXI", name: "DAX", price: 24300.5, change_pct: 0.4 },
  { symbol: "^N225", name: "Nikkei 225", price: 52100.3, change_pct: -0.3 },
  { symbol: "BTC-USD", name: "Bitcoin", price: 120500, change_pct: 2.1 },
  { symbol: "EURUSD=X", name: "EUR/USD", price: 1.1625, change_pct: 0.1 },
  { symbol: "GC=F", name: "Gold", price: 4010.8, change_pct: 0.7 },
  { symbol: "CL=F", name: "Crude Oil", price: 73.4, change_pct: -1.2 },
];

const mockedGetMarketTicker = vi.mocked(getMarketTicker);

function setVisibility(value: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { configurable: true, value });
}

describe("GlobalMarketTicker", () => {
  beforeEach(() => {
    mockedGetMarketTicker.mockReset();
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
    setVisibility("visible");
  });

  it("shows a compact local skeleton while the first feed request is pending", () => {
    mockedGetMarketTicker.mockReturnValue(new Promise(() => undefined));
    render(<GlobalMarketTicker />);
    expect(screen.getByRole("status", { name: /loading market feed/i })).toBeInTheDocument();
  });

  it("renders all instruments, verbal change direction, and an aria-hidden loop copy", async () => {
    mockedGetMarketTicker.mockResolvedValue({ items: ITEMS });
    render(<GlobalMarketTicker />);

    const list = await screen.findByRole("list", { name: /world markets/i });
    expect(within(list).getAllByRole("listitem")).toHaveLength(9);
    expect(within(list).getByText("S&P 500")).toBeInTheDocument();
    expect(within(list).getByText(/up 1.25%/i)).toBeInTheDocument();
    expect(within(list).getByText(/down 0.50%/i)).toBeInTheDocument();
    expect(within(list).getByText(/unchanged 0.00%/i)).toBeInTheDocument();
    expect(screen.getByTestId("ticker-copy")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByTestId("ticker-track")).toHaveClass("market-ticker-track");
    expect(screen.getByTestId("ticker-copy")).toHaveClass("market-ticker-copy");
    expect(screen.getByText(/updated/i)).toBeInTheDocument();
  });

  it("collapses to a quiet unavailable state when the first request fails", async () => {
    mockedGetMarketTicker.mockRejectedValue(new Error("offline"));
    render(<GlobalMarketTicker />);
    expect(await screen.findByText("Market feed unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: /world markets/i })).not.toBeInTheDocument();
  });

  it("keeps the last successful rows when a background refresh fails", async () => {
    vi.useFakeTimers();
    mockedGetMarketTicker
      .mockResolvedValueOnce({ items: ITEMS })
      .mockRejectedValueOnce(new Error("refresh failed"));
    render(<GlobalMarketTicker />);
    await act(async () => undefined);
    expect(screen.getByRole("list", { name: /world markets/i })).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });

    expect(screen.getByRole("list", { name: /world markets/i })).toBeInTheDocument();
    expect(screen.queryByText("Market feed unavailable")).not.toBeInTheDocument();
  });

  it("polls every 60 seconds only while visible and refreshes when visibility returns", async () => {
    vi.useFakeTimers();
    mockedGetMarketTicker.mockResolvedValue({ items: ITEMS });
    render(<GlobalMarketTicker />);
    await act(async () => undefined);
    expect(mockedGetMarketTicker).toHaveBeenCalledTimes(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(mockedGetMarketTicker).toHaveBeenCalledTimes(2);

    setVisibility("hidden");
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(mockedGetMarketTicker).toHaveBeenCalledTimes(2);

    setVisibility("visible");
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(mockedGetMarketTicker).toHaveBeenCalledTimes(3);
  });
});
