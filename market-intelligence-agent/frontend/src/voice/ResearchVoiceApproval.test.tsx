import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  ResearchVoiceContext,
  type ResearchVoiceContextValue,
} from "./ResearchVoiceContext";
import { ResearchVoiceApproval } from "./ResearchVoiceApproval";
import type { VoicePendingApproval } from "./types";

const { getGeneratedReportsMock } = vi.hoisted(() => ({
  getGeneratedReportsMock: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  getGeneratedReports: (...args: unknown[]) => getGeneratedReportsMock(...args),
}));

const REPORT = {
  filename: "margaret-collins-portfolio-brief-2026-10-06.xlsx",
  generated_at: "2026-10-06T09:30:00+00:00",
  size_bytes: 24832,
  client_name: "Margaret Collins",
};

const pending: VoicePendingApproval = {
  interrupt_id: "interrupt-voice-1",
  action_requests: [
    {
      name: "send_email",
      args: {
        recipient: "margaret@example.com",
        subject: "Portfolio report",
        body: "Please find your report attached.",
      },
    },
  ],
  review_configs: [
    {
      action_name: "send_email",
      allowed_decisions: ["approve", "edit", "reject"],
    },
  ],
};

function renderApproval(submitDecision = vi.fn().mockResolvedValue({
  status: "applied",
  response: null,
})) {
  const value: ResearchVoiceContextValue = {
    enabled: true,
    phase: "approval_required",
    active: true,
    events: [],
    pending,
    error: null,
    typedApprovalPending: false,
    start: vi.fn(),
    end: vi.fn(),
    submitDecision,
    setTypedApprovalPending: vi.fn(),
  };
  render(
    <ResearchVoiceContext.Provider value={value}>
      <ResearchVoiceApproval pending={pending} />
    </ResearchVoiceContext.Provider>,
  );
  return { submitDecision };
}

describe("ResearchVoiceApproval", () => {
  beforeEach(() => {
    getGeneratedReportsMock.mockReset();
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
  });

  it("keeps the generated-report selector and visual edit workflow", async () => {
    const { submitDecision } = renderApproval();

    await screen.findByRole("option", { name: /margaret collins/i });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Attachment (optional)" }),
      { target: { value: REPORT.filename } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit email" }));
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "Updated portfolio report" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Approve changes & send" }),
    );

    await waitFor(() => expect(submitDecision).toHaveBeenCalledTimes(1));
    expect(submitDecision).toHaveBeenCalledWith(
      "interrupt-voice-1",
      [
        {
          type: "edit",
          edited_action: {
            name: "send_email",
            args: expect.objectContaining({
              subject: "Updated portfolio report",
              attachment_filename: REPORT.filename,
            }),
          },
        },
      ],
    );
  });

  it("submits the stable interrupt exactly once on a double click", async () => {
    const { submitDecision } = renderApproval();
    const approve = screen.getByRole("button", { name: "Approve & send" });

    fireEvent.click(approve);
    fireEvent.click(approve);

    await waitFor(() => expect(submitDecision).toHaveBeenCalledTimes(1));
    expect(submitDecision).toHaveBeenCalledWith("interrupt-voice-1", [
      { type: "approve" },
    ]);
  });

  it("unlocks the approval card so a failed decision can be retried", async () => {
    const submitDecision = vi
      .fn()
      .mockRejectedValueOnce(new Error("Decision service unavailable"))
      .mockResolvedValueOnce({ status: "applied", response: null });
    renderApproval(submitDecision);

    fireEvent.click(screen.getByRole("button", { name: "Approve & send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Decision service unavailable",
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve & send" }));

    await waitFor(() => expect(submitDecision).toHaveBeenCalledTimes(2));
  });
});
