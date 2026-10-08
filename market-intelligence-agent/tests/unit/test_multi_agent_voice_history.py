from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END

from app.agent.multi_agent.graph import (
    _build_workflow,
    finalize_turn,
    record_multi_agent_question,
)
from app.agent.multi_agent.supervisor import _finish


def test_record_multi_agent_question_defaults_to_text_source():
    result = record_multi_agent_question(
        {"question": "What is moving markets today?"},
        {"configurable": {}},
    )

    assert result["turn_source"] == "text"
    assert result["messages"][0].content == "What is moving markets today?"
    assert result["messages"][0].additional_kwargs["source"] == "text"


def test_record_multi_agent_question_tags_voice_source_from_metadata():
    result = record_multi_agent_question(
        {"question": "Give me the latest market news"},
        {"metadata": {"input_source": "voice"}},
    )

    assert result["turn_source"] == "voice"
    assert result["messages"][0].additional_kwargs["source"] == "voice"


def test_finalize_turn_replaces_voice_ai_messages_by_id_and_preserves_metadata():
    result = finalize_turn(
        {
            "turn_source": "voice",
            "messages": [
                HumanMessage(content="typed", id="typed-human"),
                AIMessage(content="typed answer", id="typed-ai"),
                HumanMessage(
                    content="spoken",
                    id="voice-human",
                    additional_kwargs={"source": "voice"},
                ),
                AIMessage(
                    content="working",
                    id="voice-tool-call",
                    additional_kwargs={"trace": "kept"},
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "web_search",
                            "args": {"query": "markets"},
                        }
                    ],
                ),
                AIMessage(content="spoken answer", id="voice-ai"),
            ],
        }
    )

    replacements = result["messages"]
    assert [message.id for message in replacements] == ["voice-tool-call", "voice-ai"]
    assert replacements[0].additional_kwargs == {"trace": "kept", "source": "voice"}
    assert replacements[1].additional_kwargs["source"] == "voice"


def test_finalize_turn_leaves_text_turn_unchanged():
    assert finalize_turn(
        {
            "turn_source": "text",
            "messages": [HumanMessage(content="typed"), AIMessage(content="answer")],
        }
    ) == {}


def test_workflow_finalizes_before_end():
    workflow = _build_workflow()
    assert "finalize_turn" in workflow.nodes
    assert ("finalize_turn", END) in workflow.edges
    assert _finish().goto == "finalize_turn"
