"""Offline chat model for create_agent tests: replays scripted AIMessages,
accepts bind_tools, and records the messages of every call."""
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
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
