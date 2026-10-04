import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ComingSoonPage } from "./ComingSoonPage";

describe("ComingSoonPage", () => {
  it("renders the given title and description", () => {
    render(<ComingSoonPage title="Briefing" description="Résumé quotidien à venir." />);
    expect(screen.getByRole("heading", { name: "Briefing" })).toBeInTheDocument();
    expect(screen.getByText("Résumé quotidien à venir.")).toBeInTheDocument();
  });
});
