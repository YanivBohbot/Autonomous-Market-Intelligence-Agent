import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalPanel } from "./ApprovalPanel";
import type { PendingApproval } from "./approvals";

const { getGeneratedReportsMock } = vi.hoisted(() => ({
  getGeneratedReportsMock: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  getGeneratedReports: (...args: unknown[]) => getGeneratedReportsMock(...args),
}));

const ALL = ["approve", "edit", "reject"] as const;
const email = { name: "send_email", args: { recipient: "a@x.com", subject: "Hi", body: "Body" } };
const file = { name: "write_file", args: { path: "notes.md", content: "text" } };
const memory = { name: "save_memory", args: { key: "risk", value: "low" } };
const other = { name: "mystery_tool", args: { x: 1 } };
const REPORT = {
  filename: "margaret-collins-portfolio-brief-2026-10-06.xlsx",
  generated_at: "2026-10-06T09:30:00+00:00",
  size_bytes: 24832,
  client_name: "Margaret Collins",
};

function setup(approval: PendingApproval) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  render(<ApprovalPanel approval={approval} onSubmit={onSubmit} onCancel={onCancel} />);
  return { onSubmit, onCancel, user: userEvent.setup() };
}

describe("ApprovalPanel", () => {
  beforeEach(() => {
    getGeneratedReportsMock.mockReset();
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
  });

  it.each([
    [email, ["Recipient", "Subject", "Message"]],
    [file, ["path", "content"]],
    [memory, ["key", "value"]],
  ])("shows the fields of %s", (req, fields) => {
    setup({ requests: [req], allowed: [[...ALL]] });
    for (const f of fields) expect(screen.getByLabelText(f)).toBeInTheDocument();
  });

  it("shows raw JSON and no Edit for an unknown tool", () => {
    setup({ requests: [other], allowed: [[...ALL]] });
    expect(screen.getByText(/"x": 1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("presents email approval as a clear business action", async () => {
    setup({ requests: [email], allowed: [[...ALL]] });

    expect(screen.getByRole("heading", { name: "Review email before sending" })).toBeInTheDocument();
    expect(screen.getByText("Approval required")).toBeInTheDocument();
    expect(screen.getByText("Nothing is sent until you approve.")).toBeInTheDocument();
    expect(screen.getByLabelText("Recipient")).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeInTheDocument();
    expect(screen.queryByText("send_email")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve & send" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit email" })).toBeInTheDocument();
  });

  it("Approve & send submits an approve decision", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await user.click(screen.getByRole("button", { name: "Approve & send" }));
    expect(onSubmit).toHaveBeenCalledWith([{ type: "approve" }]);
  });

  it("keeps approve unchanged when no report is selected", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await screen.findByRole("option", { name: /margaret-collins/ });
    await user.click(screen.getByRole("button", { name: "Approve & send" }));
    expect(onSubmit).toHaveBeenCalledWith([{ type: "approve" }]);
  });

  it("submits a selected report as an edited email action", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await screen.findByRole("option", { name: /margaret-collins/ });
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Attachment (optional)" }),
      REPORT.filename,
    );
    await user.click(screen.getByRole("button", { name: "Approve & send" }));
    expect(onSubmit).toHaveBeenCalledWith([{
      type: "edit",
      edited_action: {
        name: "send_email",
        args: { ...email.args, attachment_filename: REPORT.filename },
      },
    }]);
  });

  it("keeps a selected client report when the advisor recipient is edited", async () => {
    const advisorEmail = {
      ...email,
      args: { ...email.args, recipient: "advisor@firm.com" },
    };
    const { user, onSubmit } = setup({ requests: [advisorEmail], allowed: [[...ALL]] });
    await screen.findByRole("option", { name: /Margaret Collins/ });
    await user.selectOptions(screen.getByRole("combobox"), REPORT.filename);
    await user.click(screen.getByRole("button", { name: "Edit email" }));
    await user.clear(screen.getByLabelText("Recipient"));
    await user.type(screen.getByLabelText("Recipient"), "other.advisor@firm.com");
    await user.click(screen.getByRole("button", { name: "Approve changes & send" }));

    expect(onSubmit.mock.calls[0][0][0].edited_action.args).toMatchObject({
      recipient: "other.advisor@firm.com",
      attachment_filename: REPORT.filename,
    });
    expect(getGeneratedReportsMock).toHaveBeenCalledWith();
  });

  it("keeps the selected report when sending edited fields", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await screen.findByRole("option", { name: /margaret-collins/ });
    await user.selectOptions(screen.getByRole("combobox"), REPORT.filename);
    await user.click(screen.getByRole("button", { name: "Edit email" }));
    await user.clear(screen.getByLabelText("Subject"));
    await user.type(screen.getByLabelText("Subject"), "Updated report");
    await user.click(screen.getByRole("button", { name: "Approve changes & send" }));
    expect(onSubmit.mock.calls[0][0][0].edited_action.args).toMatchObject({
      subject: "Updated report",
      attachment_filename: REPORT.filename,
    });
  });

  it("clears a pre-proposed attachment through an edit decision", async () => {
    const request = { ...email, args: { ...email.args, attachment_filename: REPORT.filename } };
    const { user, onSubmit } = setup({ requests: [request], allowed: [[...ALL]] });
    await screen.findByRole("option", { name: /margaret-collins/ });
    await user.selectOptions(screen.getByRole("combobox"), "");
    await user.click(screen.getByRole("button", { name: "Approve & send" }));
    expect(onSubmit.mock.calls[0][0][0].edited_action.args.attachment_filename).toBeNull();
  });

  it("disables attachment changes when edit is not allowed", async () => {
    setup({ requests: [email], allowed: [["approve", "reject"]] });
    expect(await screen.findByRole("combobox", { name: "Attachment (optional)" })).toBeDisabled();
  });

  it("approves an unchanged proposed attachment when edit is not allowed", async () => {
    const request = { ...email, args: { ...email.args, attachment_filename: REPORT.filename } };
    const { user, onSubmit } = setup({ requests: [request], allowed: [["approve", "reject"]] });

    expect(await screen.findByRole("combobox", { name: "Attachment (optional)" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Approve & send" }));

    expect(onSubmit).toHaveBeenCalledWith([{ type: "approve" }]);
  });

  it("Edit email then Approve changes & send submits the edited args", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await user.click(screen.getByRole("button", { name: "Edit email" }));
    const subject = screen.getByLabelText("Subject");
    await user.clear(subject);
    await user.type(subject, "Weekly report");
    await user.click(screen.getByRole("button", { name: "Approve changes & send" }));
    expect(onSubmit).toHaveBeenCalledWith([
      {
        type: "edit",
        edited_action: {
          name: "send_email",
          args: { ...email.args, subject: "Weekly report", attachment_filename: null },
        },
      },
    ]);
  });

  it("Cancel changes restores the original email and exits edit mode", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await screen.findByRole("option", { name: /Margaret Collins/ });
    await user.selectOptions(screen.getByRole("combobox"), REPORT.filename);
    await user.click(screen.getByRole("button", { name: "Edit email" }));
    await user.clear(screen.getByLabelText("Subject"));
    await user.type(screen.getByLabelText("Subject"), "Changed subject");

    await user.click(screen.getByRole("button", { name: "Cancel changes" }));

    expect(screen.getByLabelText("Subject")).toHaveValue("Hi");
    expect(screen.getByLabelText("Subject")).toHaveAttribute("readonly");
    expect(screen.getByRole("combobox")).toHaveValue(REPORT.filename);
    expect(screen.getByRole("button", { name: "Edit email" })).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("Reject without a reason submits a bare reject", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.click(screen.getByRole("button", { name: "Confirm reject" }));
    expect(onSubmit).toHaveBeenCalledWith([{ type: "reject" }]);
  });

  it("Reject with a reason carries the message", async () => {
    const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.type(screen.getByLabelText("reason"), "not now");
    await user.click(screen.getByRole("button", { name: "Confirm reject" }));
    expect(onSubmit).toHaveBeenCalledWith([{ type: "reject", message: "not now" }]);
  });

  it("waits for every request, then submits decisions in request order", async () => {
    const { user, onSubmit } = setup({ requests: [email, file], allowed: [[...ALL], [...ALL]] });
    await user.click(screen.getByRole("button", { name: "Approve" })); // decide the file request first
    expect(onSubmit).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.click(screen.getByRole("button", { name: "Confirm reject" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith([{ type: "reject" }, { type: "approve" }]);
  });

  it("submits once even when clicked twice", () => {
    const { onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
    const approve = screen.getByRole("button", { name: "Approve & send" });
    // fireEvent (not user-event): dispatches even if the button was already
    // removed by the first click, which is exactly the race we guard against.
    fireEvent.click(approve);
    fireEvent.click(approve);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Approve & send" })).not.toBeInTheDocument();
  });

  it("hides buttons the review config does not allow", () => {
    setup({ requests: [email], allowed: [["approve", "reject"]] });
    expect(screen.queryByRole("button", { name: "Edit email" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve & send" })).toBeInTheDocument();
  });

  it("renders a cancel-only card when there are no requests", async () => {
    const { user, onCancel, onSubmit } = setup({ requests: [], allowed: [] });
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
