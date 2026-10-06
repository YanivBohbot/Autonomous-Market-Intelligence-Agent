import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getBriefingClientAlerts = vi.hoisted(() => vi.fn());

vi.mock("../lib/api", () => ({ getBriefingClientAlerts }));

import { ClientAlertsPanel } from "./ClientAlertsPanel";

describe("ClientAlertsPanel", () => {
  beforeEach(() => {
    getBriefingClientAlerts.mockReset();
  });

  it("shows shared local skeletons while concentration data loads", () => {
    getBriefingClientAlerts.mockReturnValue(new Promise(() => undefined));

    const { container } = render(<ClientAlertsPanel />);

    expect(screen.getAllByRole("status")).toHaveLength(3);
    expect(container.querySelector("section")).toHaveAttribute("data-tone", "default");
  });

  it("renders breach cards with warning badges and sans-serif presentation", async () => {
    getBriefingClientAlerts.mockResolvedValue({
      available: true,
      threshold_pct: 30,
      breaches: [
        { label: "Avery Morgan", ticker: "NVDA", weight_pct: 42.4, market_value: 525000 },
        { label: "Riley Chen", ticker: "AAPL", weight_pct: 34.1, market_value: 318000 },
      ],
    });

    const { container } = render(<ClientAlertsPanel />);

    const heading = await screen.findByRole("heading", { name: "Client concentration alerts" });
    expect(heading.closest("section")).toHaveAttribute("data-tone", "default");
    expect(screen.getByText("2 flagged")).toHaveAttribute("data-tone", "warning");
    expect(screen.getByText("42.4%")).toHaveAttribute("data-tone", "warning");
    expect(screen.getByText("Avery Morgan")).toBeInTheDocument();
    expect(screen.getByText("Riley Chen")).toBeInTheDocument();
    expect(container.querySelector(".font-mono")).toBeNull();
  });

  it("shows an all-clear state with a success badge", async () => {
    getBriefingClientAlerts.mockResolvedValue({ available: true, threshold_pct: 30, breaches: [] });

    render(<ClientAlertsPanel />);

    expect(await screen.findByText("No concentration breaches")).toBeInTheDocument();
    expect(screen.getByText("All clear")).toHaveAttribute("data-tone", "success");
    expect(screen.getByText(/within the configured limit/i)).toBeInTheDocument();
  });

  it("shows a neutral unavailable state when the alerts request fails", async () => {
    getBriefingClientAlerts.mockRejectedValue(new Error("offline"));

    render(<ClientAlertsPanel />);

    expect(await screen.findByText("Concentration data unavailable")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toHaveAttribute("data-tone", "neutral");
    expect(screen.getByText(/could not be reached/i)).toBeInTheDocument();
  });
});
