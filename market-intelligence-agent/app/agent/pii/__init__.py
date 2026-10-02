"""Sensitive-data guard shared by the single-agent and multi-agent graphs.

Blocks before any model call if the user's message contains a credit card
number or an email address, instead of letting a scrubbed version through
like the existing `PIIMiddleware` mask/redact strategies in
`app/agent/common.py` do. Room to grow: more detectors, more guard points.
"""

from app.agent.pii.detection import SENSITIVE_DATA_WARNING, contains_sensitive_data
from app.agent.pii.middleware import SensitiveDataGuard
from app.agent.pii.node import pii_guard_node, route_after_pii_guard

__all__ = [
    "SENSITIVE_DATA_WARNING",
    "SensitiveDataGuard",
    "contains_sensitive_data",
    "pii_guard_node",
    "route_after_pii_guard",
]
