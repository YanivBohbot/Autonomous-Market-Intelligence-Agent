import { useRef, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { ResponsiveRail } from "./ResponsiveRail";

function RailHarness() {
  const [open, setOpen] = useState(false);
  const openerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button ref={openerRef} type="button" onClick={() => setOpen(true)}>Open navigation</button>
      <ResponsiveRail open={open} side="left" title="Navigation" onClose={() => setOpen(false)} openerRef={openerRef}>
        <a href="/briefing">Briefing</a>
        <button type="button">Last action</button>
      </ResponsiveRail>
    </>
  );
}

describe("ResponsiveRail", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("keeps a closed rail invisible off-canvas on mobile but visible on desktop", async () => {
    const user = userEvent.setup();
    render(<RailHarness />);
    const rail = screen.getByText("Briefing").closest("aside");
    expect(rail).toHaveClass("invisible", "xl:visible");

    await user.click(screen.getByRole("button", { name: "Open navigation" }));

    expect(rail).toHaveClass("visible");
    expect(rail).not.toHaveClass("invisible");
  });

  it("closes on Escape, restores opener focus, and unlocks body scroll", async () => {
    const user = userEvent.setup();
    render(<RailHarness />);
    const opener = screen.getByRole("button", { name: "Open navigation" });

    await user.click(opener);
    expect(screen.getByRole("dialog", { name: "Navigation" })).toHaveClass("left-0", "translate-x-0");
    expect(screen.getByRole("button", { name: "Close Navigation" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });

  it("cycles Tab and Shift+Tab inside the open rail", async () => {
    const user = userEvent.setup();
    render(<RailHarness />);
    await user.click(screen.getByRole("button", { name: "Open navigation" }));

    const close = screen.getByRole("button", { name: "Close Navigation" });
    const last = screen.getByRole("button", { name: "Last action" });
    expect(close).toHaveFocus();

    await user.tab({ shift: true });
    expect(last).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
  });

  it("closes when the mobile overlay is clicked", async () => {
    const user = userEvent.setup();
    render(<RailHarness />);
    const opener = screen.getByRole("button", { name: "Open navigation" });
    await user.click(opener);

    await user.click(screen.getByTestId("navigation-overlay"));

    expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});
