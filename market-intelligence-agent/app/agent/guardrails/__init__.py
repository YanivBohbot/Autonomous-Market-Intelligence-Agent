"""Sensitive-data guard (SensitiveDataGuard middleware) for the multi-agent specialists.

Blocks before any model call if the user's message contains a credit card
number or an email address, instead of letting a scrubbed version through
like the existing `PIIMiddleware` mask/redact strategies in
`app/agent/middleware.py` do. Room to grow: more detectors, more guard points.
"""

from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING, contains_sensitive_data
from app.agent.guardrails.middleware import SensitiveDataGuard

__all__ = [
    "SENSITIVE_DATA_WARNING",
    "SensitiveDataGuard",
    "contains_sensitive_data",
]
