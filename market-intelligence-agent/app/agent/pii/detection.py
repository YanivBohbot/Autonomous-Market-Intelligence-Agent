"""Sensitive-data detection shared by the single-agent and multi-agent guards.

Reuses `PIIMiddleware` itself in `block` mode: its public `before_model` hook
raises `PIIDetectionError` the moment it finds a match, so detection (and
content-shape handling — str or content-block list) stays in sync with
`mask_credit_cards()` / `redact_emails()` in `app/agent/common.py` without
duplicating any regex or message-parsing logic.
"""

from typing import Any

from langchain.agents.middleware import PIIDetectionError, PIIMiddleware
from langchain_core.messages import HumanMessage

SENSITIVE_DATA_WARNING = (
    "This message appears to contain sensitive personal data (a credit card "
    "number or an email address). Sharing this kind of information in chat "
    "is not allowed, so I can't process this request — please resend your "
    "question without it."
)

_CREDIT_CARD_GUARD = PIIMiddleware("credit_card", strategy="block")
_EMAIL_GUARD = PIIMiddleware("email", strategy="block")


def contains_sensitive_data(content: str | list[str | dict[str, Any]] | None) -> bool:
    """True if `content` (a message's content) contains a credit card number
    or an email address."""
    if not content:
        return False
    probe_state = {"messages": [HumanMessage(content=content)]}
    for guard in (_CREDIT_CARD_GUARD, _EMAIL_GUARD):
        try:
            guard.before_model(probe_state, None)
        except PIIDetectionError:
            return True
    return False
