"""Sensitive-data detection built on LangChain's documented PII detectors
(`langchain.agents.middleware.pii`), the same ones PIIMiddleware uses."""

from typing import Any

from langchain.agents.middleware.pii import detect_credit_card, detect_email

SENSITIVE_DATA_WARNING = (
    "This message appears to contain a credit card number. Sharing this kind "
    "of information in chat is not allowed, so I can't process this request "
    "— please resend your question without it."
)

Content = str | list[str | dict[str, Any]] | None


def _text(content: Content) -> str:
    """Flatten a message's content (a string or a content-block list) to its text."""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return " ".join(parts)


def contains_credit_card(content: Content) -> bool:
    """True if `content` contains a Luhn-valid credit card number."""
    return bool(detect_credit_card(_text(content)))


def contains_email(content: Content) -> bool:
    """True if `content` contains an email address."""
    return bool(detect_email(_text(content)))


def contains_sensitive_data(content: Content, *, check_email: bool = True) -> bool:
    """True if `content` contains a credit card number, or — when
    `check_email` — an email address."""
    if contains_credit_card(content):
        return True
    return check_email and contains_email(content)
