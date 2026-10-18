"""_run_async: the sync bridge get_mcp_tools() uses at import/startup time."""
import asyncio
import gc
import warnings

import pytest

from app.agent.mcp_clients.registry import _run_async


async def _answer():
    return 42


def test_runs_without_a_loop():
    assert _run_async(_answer) == 42


def test_runs_inside_a_running_loop_without_leaking_a_coroutine():
    # Regression: the factory was called once for asyncio.run(), which refused
    # (loop already running), leaving that coroutine never awaited.
    async def caller():
        return _run_async(_answer)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        assert asyncio.run(caller()) == 42
        gc.collect()


def test_real_errors_propagate():
    async def boom():
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        _run_async(boom)
