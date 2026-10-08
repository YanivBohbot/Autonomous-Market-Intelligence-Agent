import pytest

from app.agent.turn_coordinator import ThreadTurnCoordinator, TurnLease


@pytest.mark.anyio
async def test_first_owner_acquires_and_second_owner_is_rejected():
    coordinator = ThreadTurnCoordinator()

    lease = await coordinator.try_acquire("thread-1", "text:run-1")

    assert lease is not None
    assert await coordinator.owner("thread-1") == "text:run-1"
    assert await coordinator.try_acquire("thread-1", "voice:session-1") is None


@pytest.mark.anyio
async def test_release_requires_the_exact_lease_token():
    coordinator = ThreadTurnCoordinator()
    lease = await coordinator.try_acquire("thread-1", "voice:session-1")
    assert lease is not None

    stale = TurnLease(
        thread_id=lease.thread_id,
        owner=lease.owner,
        token="stale-token",
    )
    await coordinator.release(stale)
    assert await coordinator.owner("thread-1") == "voice:session-1"

    await coordinator.release(lease)
    assert await coordinator.owner("thread-1") is None


@pytest.mark.anyio
async def test_threads_are_coordinated_independently():
    coordinator = ThreadTurnCoordinator()

    first = await coordinator.try_acquire("thread-1", "text:run-1")
    second = await coordinator.try_acquire("thread-2", "voice:session-2")

    assert first is not None
    assert second is not None
    assert await coordinator.owner("thread-1") == "text:run-1"
    assert await coordinator.owner("thread-2") == "voice:session-2"
