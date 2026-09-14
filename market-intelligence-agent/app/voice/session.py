"""Transport-agnostic helpers shared by the GPT-Live delegation worker.

The LLM is the compiled LangGraph workflow (`app.voice.graph`), invoked
directly by `app.voice.worker`, so voice turns run the same tools + HITL
flow as text turns.
"""
import re
import sys

from langchain_core.callbacks.base import BaseCallbackHandler

# Matches one or more leading `{"binary_score":"yes|no"}` JSON fragments that
# sometimes leak through when the LangGraph state has stale grader outputs.
# Without stripping, TTS literally reads the JSON aloud.
_BINARY_SCORE_PREFIX = re.compile(r'^\s*(\{"binary_score":"\w+"\}\s*)+')


def strip_binary_score_prefix(content: str) -> str:
    """Remove any leaked grader JSON prefix from a final assistant message."""
    return _BINARY_SCORE_PREFIX.sub("", content)


class _ToolCallLogger(BaseCallbackHandler):
    """Print every LangGraph tool invocation to stderr so a voice QA session
    can SEE which tool fired and what it returned. Visibility only."""

    def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        name = (serialized or {}).get("name", "?")
        print(f"[voice.tool] CALL  {name}  args={input_str}", file=sys.stderr, flush=True)

    def on_tool_end(self, output, **kwargs) -> None:
        print(f"[voice.tool] DONE  {str(output)[:240]}", file=sys.stderr, flush=True)


VOICE_INSTRUCTIONS = (
    "You are a market intelligence voice assistant speaking with the user. "
    "Personality: friendly, concise, professional. Keep replies under 30 words. "
    "Speak naturally — no markdown, bullet points, or numbered lists. Spell out "
    "numbers and acronyms when reading them.\n"
    "Backchannel policy: brief acknowledgements are fine while waiting on backend work.\n"
    "Interruption policy: stop speaking immediately if the user starts talking.\n"
    "Delegation policy: delegate every user question or request to the backend; "
    "never answer market, account, or file questions yourself.\n"
    "If the backend asks for a yes/no confirmation before an action (such as "
    "sending an email or saving data), relay that confirmation request verbatim "
    "and wait for the user's yes or no before delegating again.\n"
    "Respond in the same language the user speaks, including Hebrew."
)
