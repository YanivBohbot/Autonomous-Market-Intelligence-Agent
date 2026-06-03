import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalCard } from "./ApprovalCard";
import * as api from "../lib/api";

describe("ApprovalCard", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("approves and reports completion", async () => {
    vi.spyOn(api, "postApprove").mockResolvedValue({
      response: "Email sent.",
      status: "completed",
      next_step: null,
    });
    const onResolved = vi.fn();
    render(
      <ApprovalCard
        threadId="t1"
        pending={{ action: "send_email to vip@example.com", nextStep: "('tools',)" }}
        onResolved={onResolved}
      />,
    );
    expect(screen.getByText(/send_email/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(api.postApprove).toHaveBeenCalledWith("t1", true);
    expect(onResolved).toHaveBeenCalledWith("Email sent.", null);
  });

  it("rejects and reports completion", async () => {
    vi.spyOn(api, "postApprove").mockResolvedValue({
      response: "Action cancelled.",
      status: "completed",
      next_step: null,
    });
    const onResolved = vi.fn();
    render(
      <ApprovalCard
        threadId="t1"
        pending={{ action: "write_file report.md", nextStep: "('tools',)" }}
        onResolved={onResolved}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(api.postApprove).toHaveBeenCalledWith("t1", false);
    expect(onResolved).toHaveBeenCalledWith("Action cancelled.", null);
  });

  it("surfaces a chained interrupt as still-pending", async () => {
    vi.spyOn(api, "postApprove").mockResolvedValue({
      response: "Next action required: save_memory",
      status: "interrupted",
      next_step: "('tools',)",
    });
    const onResolved = vi.fn();
    render(
      <ApprovalCard
        threadId="t1"
        pending={{ action: "first action", nextStep: "('tools',)" }}
        onResolved={onResolved}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(onResolved).toHaveBeenCalledWith(
      "Next action required: save_memory",
      { action: "Next action required: save_memory", nextStep: "('tools',)" },
    );
  });
});
