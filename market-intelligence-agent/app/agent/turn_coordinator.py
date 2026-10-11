import asyncio
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class TurnLease:
    thread_id: str
    owner: str
    token: str


class ThreadTurnCoordinator:
    """Serialize graph turns across transports for each checkpoint thread."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._leases: dict[str, TurnLease] = {}

    async def try_acquire(self, thread_id: str, owner: str) -> TurnLease | None:
        async with self._lock:
            if thread_id in self._leases:
                return None
            lease = TurnLease(thread_id=thread_id, owner=owner, token=str(uuid4()))
            self._leases[thread_id] = lease
            return lease

    async def release(self, lease: TurnLease) -> None:
        async with self._lock:
            if self._leases.get(lease.thread_id) == lease:
                del self._leases[lease.thread_id]

    async def owner(self, thread_id: str) -> str | None:
        async with self._lock:
            lease = self._leases.get(thread_id)
            return lease.owner if lease is not None else None
