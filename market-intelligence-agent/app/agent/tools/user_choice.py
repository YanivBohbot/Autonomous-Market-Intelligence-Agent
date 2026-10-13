"""`ask_user_choice` — pause the run and ask the user to pick from options.

Uses LangGraph interrupt(): the run stops, Market Desk renders a choice card
(useDeskInterrupt), and Command(resume={"selected": [...], "other": ...})
continues the SAME tool call through the checkpointer -- same mechanism as
HITL approvals. Only offered on the Market Desk AG-UI transport (see
middleware.OnlyOnAgUi). Deliberately NOT in READ_ONLY_TOOLS: tool_retry wraps
read-only tools and would catch the GraphInterrupt."""

from __future__ import annotations

import json

from langchain_core.tools import tool
from langgraph.config import get_config
from langgraph.types import interrupt
from pydantic import BaseModel, Field


def build_choice_payload(question: str, options: list[str], *, multi: bool, allow_other: bool) -> dict:
    labels = [o.strip() for o in options if o and o.strip()]
    if len(labels) < 2:
        raise ValueError("ask_user_choice needs at least 2 options")
    return {
        "type": "user_choice",
        "question": question,
        "options": [{"id": str(i), "label": label} for i, label in enumerate(labels)],
        "multi": multi,
        "allow_other": allow_other,
    }


class AskUserChoiceInput(BaseModel):
    question: str = Field(description="The question to show, e.g. 'Which client did you mean?'.")
    options: list[str] = Field(min_length=2, max_length=12, description="The choices to show as buttons.")
    multi: bool = Field(default=False, description="True to let the user tick several options.")
    allow_other: bool = Field(default=False, description="True to add a free-text 'Other' answer.")


@tool("ask_user_choice", args_schema=AskUserChoiceInput)
def ask_user_choice_tool(question: str, options: list[str], multi: bool = False, allow_other: bool = False) -> str:
    """Ask the user to choose between options shown as buttons (or checkboxes
    when multi=True), and wait for the answer. Use it instead of asking in
    plain text when the choice is between known options: an ambiguous client
    name, a missing trade size, or which clients to include."""
    from app.agent.orchestration.state import is_ag_ui_run

    if not is_ag_ui_run(get_config()):
        # Voice / /stream / AgentCore resume only HITL decisions: never pause there.
        return "ask_user_choice is not available here: ask the user in plain text instead."
    payload = build_choice_payload(question, options, multi=multi, allow_other=allow_other)
    answer = interrupt(payload)
    answer = answer if isinstance(answer, dict) else {}
    by_id = {o["id"]: o["label"] for o in payload["options"]}
    result = {
        "selected": [by_id[i] for i in answer.get("selected") or [] if i in by_id],
        "other": answer.get("other") or None,
    }
    if answer.get("cancelled"):
        result["cancelled"] = True
    return json.dumps(result)
