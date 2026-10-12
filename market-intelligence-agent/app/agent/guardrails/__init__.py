"""Guardrails: sensitive-data detection and the supervisor's card guard.

Request-level blocking happens in `block_credit_cards`, a @before_agent
middleware on the supervisor's router agent. Specialists add LangChain's
prebuilt PIIMiddleware / OpenAIModerationMiddleware (see
`app/agent/middleware.py`)."""

from app.agent.guardrails.card_guard import block_credit_cards
from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING, contains_sensitive_data

__all__ = [
    "SENSITIVE_DATA_WARNING",
    "block_credit_cards",
    "contains_sensitive_data",
]
