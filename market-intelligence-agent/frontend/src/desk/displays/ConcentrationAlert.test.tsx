import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConcentrationAlert } from "./ConcentrationAlert";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "concentration_alert" }> = {
  type: "concentration_alert", threshold_pct: 30,
  breaches: [{ label: "Margaret Collins", ticker: "NVDA", weight_pct: 57.5, market_value: 89436 }],
};

describe("ConcentrationAlert", () => {
  it("shows the client, ticker and weight for each breach", () => {
    render(<ConcentrationAlert display={display} />);
    expect(screen.getByText(/Margaret Collins/)).toBeInTheDocument();
    expect(screen.getByText(/NVDA/)).toBeInTheDocument();
    expect(screen.getByText(/57.5%/)).toBeInTheDocument();
  });
});
