"""In-process store of voice-session transcript turns, keyed by thread_id.

`worker.py` appends each turn (greeting, user question, agent reply) as it
produces the text; `GET /voice/{thread_id}/transcript` (in
`gptlive_session.py`) lets the Streamlit frontend poll for new turns and
render them alongside the text-mode chat. Single-process, in-memory — fine
for this app's demo-scale deployment (same assumption as the rest of the
voice stack); a multi-worker deployment would need a shared store instead.
"""
import itertools
import threading

_lock = threading.Lock()
_next_id = itertools.count(1)
_threads: dict[str, list[dict]] = {}


def append(thread_id: str, role: str, content: str) -> None:
    with _lock:
        _threads.setdefault(thread_id, []).append(
            {"id": next(_next_id), "role": role, "content": content}
        )


def get_after(thread_id: str, after_id: int) -> list[dict]:
    with _lock:
        return [m for m in _threads.get(thread_id, []) if m["id"] > after_id]
