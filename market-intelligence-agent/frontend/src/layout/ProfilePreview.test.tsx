import { useRef, useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Theme } from "../theme";
import { ProfilePreview } from "./ProfilePreview";

function ProfileHarness({ theme = "dark" }: { theme?: Theme }) {
  const [open, setOpen] = useState(false);
  const openerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button ref={openerRef} type="button" onClick={() => setOpen(true)}>Profile</button>
      <ProfilePreview open={open} onClose={() => setOpen(false)} theme={theme} openerRef={openerRef} />
    </>
  );
}

describe("ProfilePreview", () => {
  it("shows the operator, active theme, and disabled future settings", async () => {
    const user = userEvent.setup();
    render(<ProfileHarness theme="dark" />);
    await user.click(screen.getByRole("button", { name: "Profile" }));

    const dialog = screen.getByRole("dialog", { name: "Profile" });
    expect(within(dialog).getByText("Desk Operator")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Theme")).toHaveValue("dark");
    expect(within(dialog).getByLabelText("Language")).toHaveValue("English");
    expect(within(dialog).getByLabelText("Default market")).toHaveValue("United States");
    expect(within(dialog).getByLabelText("Refresh interval")).toHaveValue("60 seconds");
    expect(within(dialog).getByLabelText("Notifications")).not.toBeChecked();
    expect(within(dialog).getAllByText("Coming soon")).toHaveLength(5);

    for (const control of within(dialog).getAllByRole("combobox")) {
      expect(control).toBeDisabled();
    }
    const notifications = within(dialog).getByLabelText("Notifications");
    expect(notifications).toBeDisabled();
    await user.click(notifications);
    expect(notifications).not.toBeChecked();
  });

  it("traps focus, closes on Escape, and restores focus to Profile", async () => {
    const user = userEvent.setup();
    render(<ProfileHarness />);
    const opener = screen.getByRole("button", { name: "Profile" });
    await user.click(opener);

    const close = screen.getByRole("button", { name: "Close Profile" });
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "Profile" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});
