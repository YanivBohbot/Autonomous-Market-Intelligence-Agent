import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SectorAllocationChart } from "./SectorAllocationChart";

describe("SectorAllocationChart", () => {
  it("renders a bar per sector", () => {
    render(<SectorAllocationChart sectorAllocation={{ Technology: 58.5, ETF: 13.4 }} />);
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("ETF")).toBeInTheDocument();
  });

  it("renders nothing when sectorAllocation is null", () => {
    const { container } = render(<SectorAllocationChart sectorAllocation={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
