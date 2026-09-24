"""Offline chat model for create_agent tests: replays scripted AIMessages,
accepts bind_tools, and records the messages of every call."""
import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field


class FakeToolModel(GenericFakeChatModel):
    seen: list = Field(default_factory=list)

    def __init__(self, responses, **kwargs):
        super().__init__(messages=iter(responses), **kwargs)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


class StreamingFakeToolModel(FakeToolModel):
    """FakeToolModel whose stream carries tool calls. GenericFakeChatModel only
    streams text content, so a tool-call-only reply streams as nothing — and
    AG-UI (astream_events) always streams."""

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs).generations[0].message
        yield ChatGenerationChunk(message=AIMessageChunk(
            content=message.content,
            id=message.id,
            tool_call_chunks=[
                {"name": tc["name"], "args": json.dumps(tc["args"]), "id": tc["id"], "index": i, "type": "tool_call_chunk"}
                for i, tc in enumerate(message.tool_calls)
            ],
        ))
