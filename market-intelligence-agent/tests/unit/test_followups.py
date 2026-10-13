import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.orchestration import followups
from app.agent.orchestration.followups import FollowUps, Suggestion, suggest_followups
from app.agent.orchestration.state import SupervisorState

AG_UI = {"ag-ui": {"context": []}}


def _state(**extra):
    return {"messages": [HumanMessage("Compare NVDA vs AMD"), AIMessage("Here's the comparison.")], **extra}


def test_skips_without_ag_ui():
    with patch.object(followups, "_ask_model", AsyncMock()) as fake:
        assert asyncio.run(suggest_followups(_state())) == {}
    fake.assert_not_called()


def test_writes_three_suggestions():
    fake = AsyncMock(return_value=FollowUps(suggestions=[Suggestion(title=f"t{i}", message=f"m{i}") for i in range(3)]))
    with patch.object(followups, "_ask_model", fake):
        out = asyncio.run(suggest_followups(_state(**AG_UI)))
    assert out == {"suggestions": [{"title": f"t{i}", "message": f"m{i}"} for i in range(3)]}
    fake.assert_awaited_once_with("Compare NVDA vs AMD", "Here's the comparison.")


def test_model_error_writes_empty_list():
    with patch.object(followups, "_ask_model", AsyncMock(side_effect=RuntimeError("boom"))):
        assert asyncio.run(suggest_followups(_state(**AG_UI))) == {"suggestions": []}


def test_no_answer_yet_writes_empty_list():
    state = {"messages": [HumanMessage("hi")], **AG_UI}
    assert asyncio.run(suggest_followups(state)) == {"suggestions": []}


def test_suggestions_is_a_graph_state_key():
    assert "suggestions" in SupervisorState.__annotations__


def test_graph_runs_suggest_followups_last():
    from app.agent.orchestration.graph import _build_workflow

    wf = _build_workflow()
    assert ("finalize_turn", "suggest_followups") in wf.edges
    assert ("suggest_followups", "__end__") in wf.edges
