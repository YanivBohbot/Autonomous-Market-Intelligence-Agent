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

Content = str | list[str | dict[str, Any]] | None


def _trips(guard: PIIMiddleware, content: Content) -> bool:
    if not content:
        return False
    try:
        guard.before_model({"messages": [HumanMessage(content=content)]}, None)
    except PIIDetectionError:
        return True
    return False


def contains_credit_card(content: Content) -> bool:
    """True if `content` contains a credit card number."""
    return _trips(_CREDIT_CARD_GUARD, content)


def contains_email(content: Content) -> bool:
    """True if `content` contains an email address."""
    return _trips(_EMAIL_GUARD, content)


def contains_sensitive_data(content: Content, *, check_email: bool = True) -> bool:
    """True if `content` contains a credit card number, or — when
    `check_email` — an email address.

    `check_email=False` for graphs/specialists that need a real address to
    work (send_email, and anything that saves a report/fact tied to a
    client): mirrors `redact_emails()`'s existing scoping in
    `app/agent/common.py`, which is never applied to `email`/`portfolio`/
    `memory`/`filesystem` either, for the same reason.
    """
    if contains_credit_card(content):
        return True
    return check_email and contains_email(content)
