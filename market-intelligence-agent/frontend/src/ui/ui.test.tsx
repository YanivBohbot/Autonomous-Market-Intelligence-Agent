import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EmptyState, ErrorState, Skeleton } from "./FeedbackStates";
import { Icon } from "./Icon";
import { MetricCard } from "./MetricCard";
import { PageHeader } from "./PageHeader";
import { SectionHeader } from "./SectionHeader";
import { StatusBadge } from "./StatusBadge";
import { SurfaceCard } from "./SurfaceCard";

describe("shared UI primitives", () => {
  it("gives a page an accessible title, context, actions, and optional content", () => {
    render(
      <PageHeader
        eyebrow="Client intelligence"
        title="Clients"
        description="Monitor every relationship."
        actions={<button type="button">Add client</button>}
      >
        <span>Secondary navigation</span>
      </PageHeader>,
    );

    expect(screen.getByRole("heading", { name: "Clients" })).toBeInTheDocument();
    expect(screen.getByText("Client intelligence")).toBeInTheDocument();
    expect(screen.getByText("Monitor every relationship.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add client" })).toBeInTheDocument();
    expect(screen.getByText("Secondary navigation")).toBeInTheDocument();
  });

  it("exposes surface and status variants without changing their content", () => {
    render(
      <SurfaceCard tone="gradient" padding="lg">
        <StatusBadge tone="success">Operational</StatusBadge>
      </SurfaceCard>,
    );

    expect(screen.getByText("Operational")).toHaveAttribute("data-tone", "success");
    expect(screen.getByText("Operational").closest("section")).toHaveAttribute("data-tone", "gradient");
  });

  it("renders section and metric context with semantic state text", () => {
    render(
      <>
        <SectionHeader title="Portfolio" description="Current allocation" action={<a href="/reports">Open</a>} />
        <MetricCard label="Return" value="+4.8%" detail="Year to date" tone="success" />
      </>,
    );

    expect(screen.getByRole("heading", { name: "Portfolio" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/reports");
    expect(screen.getByText("+4.8%").closest("article")).toHaveAttribute("data-tone", "success");
    expect(screen.getByText("Year to date")).toBeInTheDocument();
  });

  it("announces skeleton loading and renders useful empty state copy", () => {
    render(
      <>
        <Skeleton label="Loading client metrics" />
        <EmptyState title="No documents" description="Import a PDF or workbook to begin." icon="document" />
      </>,
    );

    expect(screen.getByRole("status", { name: "Loading client metrics" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No documents" })).toBeInTheDocument();
    expect(screen.getByText("Import a PDF or workbook to begin.")).toBeInTheDocument();
  });

  it("runs an error recovery action", async () => {
    const retry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorState title="Clients unavailable" actionLabel="Retry" onAction={retry} />);

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("hides decorative icons and labels meaningful icons", () => {
    const { rerender } = render(<Icon name="briefing" />);
    expect(document.querySelector("svg")).toHaveAttribute("aria-hidden", "true");

    rerender(<Icon name="warning" title="Warning" />);
    expect(screen.getByRole("img", { name: "Warning" })).toBeInTheDocument();
  });
});
