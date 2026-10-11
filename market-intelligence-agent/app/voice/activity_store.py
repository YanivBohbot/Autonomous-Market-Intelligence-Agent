from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Literal


VoicePhase = Literal[
    "connecting",
    "listening",
    "analyzing",
    "speaking",
    "approval_required",
    "disconnected",
    "error",
]
VoiceActivityKind = Literal[
    "specialist_started",
    "tool_started",
    "tool_finished",
    "approval_required",
    "run_finished",
    "run_error",
]

_MAX_EVENTS = 200
_PROCESSING_ERROR = "Voice processing failed"
_DISCONNECTED_ERROR = "Voice session disconnected"


@dataclass
class _VoiceRecord:
    phase: VoicePhase = "disconnected"
    sequence: int = 0
    events: deque[dict] = field(
        default_factory=lambda: deque(maxlen=_MAX_EVENTS)
    )
    pending: dict | None = None
    error: str | None = None


class VoiceActivityStore:
    """Bounded, process-local presentation state for Research voice."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, _VoiceRecord] = {}

    def begin_session(self, thread_id: str) -> None:
        with self._lock:
            self._records[thread_id] = _VoiceRecord(phase="connecting")

    def set_phase(
        self,
        thread_id: str,
        phase: VoicePhase,
        *,
        error: object | None = None,
    ) -> None:
        with self._lock:
            record = self._record(thread_id)
            record.phase = phase
            if phase == "error":
                record.error = _PROCESSING_ERROR
            elif error is not None:
                record.error = _DISCONNECTED_ERROR
            else:
                record.error = None

    def append_event(
        self,
        thread_id: str,
        *,
        run_id: str,
        kind: VoiceActivityKind,
        name: str | None = None,
        tool_call_id: str | None = None,
        duration_ms: int | None = None,
        message: str | None = None,
    ) -> dict:
        with self._lock:
            record = self._record(thread_id)
            record.sequence += 1
            event = {
                "sequence": record.sequence,
                "run_id": run_id,
                "kind": kind,
                "name": name,
                "tool_call_id": tool_call_id,
                "duration_ms": duration_ms,
                "message": _PROCESSING_ERROR if kind == "run_error" else message,
            }
            record.events.append(event)
            return deepcopy(event)

    def set_pending(self, thread_id: str, pending: dict | None) -> None:
        with self._lock:
            self._record(thread_id).pending = deepcopy(pending)

    def snapshot(self, thread_id: str, *, after: int = 0) -> dict:
        with self._lock:
            record = self._records.get(thread_id) or _VoiceRecord()
            return {
                "phase": record.phase,
                "sequence": record.sequence,
                "events": deepcopy(
                    [event for event in record.events if event["sequence"] > after]
                ),
                "pending": deepcopy(record.pending),
                "error": record.error,
            }

    def end_session(self, thread_id: str, *, error: object | None = None) -> None:
        with self._lock:
            record = self._record(thread_id)
            record.phase = "disconnected"
            record.error = _DISCONNECTED_ERROR if error is not None else None

    def _record(self, thread_id: str) -> _VoiceRecord:
        return self._records.setdefault(thread_id, _VoiceRecord())
