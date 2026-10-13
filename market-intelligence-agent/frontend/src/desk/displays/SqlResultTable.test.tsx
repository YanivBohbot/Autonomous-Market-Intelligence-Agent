import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SqlResultTable } from "./SqlResultTable";

describe("SqlResultTable", () => {
  it("renders headers, cells and the truncation note", () => {
    render(<SqlResultTable display={{ type: "sql_table", columns: ["name", "shares"], rows: [["Ann", 10], ["Bob", null]], truncated: true }} />);
    expect(screen.getByRole("columnheader", { name: "name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Ann" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "10" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "—" })).toBeInTheDocument();
    expect(screen.getByText(/first 50 rows/)).toBeInTheDocument();
  });
});
