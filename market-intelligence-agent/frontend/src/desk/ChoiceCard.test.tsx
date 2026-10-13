import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ChoiceCard, readChoice } from "./ChoiceCard";

const raw = { type: "user_choice", question: "Which client?", multi: false, allow_other: false,
  options: [{ id: "0", label: "Ann Lee" }, { id: "1", label: "Ann Moss" }] };
const interrupt = { metadata: { langgraph: { raw } } };

describe("ChoiceCard", () => {
  it("reads only user_choice interrupts", () => {
    expect(readChoice(interrupt)?.question).toBe("Which client?");
    expect(readChoice({ metadata: { langgraph: { raw: { action_requests: [] } } } })).toBeNull();
    expect(readChoice(null)).toBeNull();
  });

  it("single choice submits on click", () => {
    const onSubmit = vi.fn();
    render(<ChoiceCard request={readChoice(interrupt)!} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: "Ann Moss" }));
    expect(onSubmit).toHaveBeenCalledWith({ selected: ["1"], other: null });
  });

  it("multi choice submits the ticked options and other text", () => {
    const onSubmit = vi.fn();
    render(<ChoiceCard request={{ ...readChoice(interrupt)!, multi: true, allow_other: true }} onSubmit={onSubmit} />);
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Ann Lee" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Other" }), { target: { value: "Bob" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onSubmit).toHaveBeenCalledWith({ selected: ["0"], other: "Bob" });
  });
});
