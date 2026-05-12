import os
import tempfile

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agent.memory.checkpointer import create_checkpointer


@pytest.mark.anyio
async def test_create_checkpointer_returns_async_sqlite_saver():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_checkpoints.db")
        async with create_checkpointer(db_path=db_path) as checkpointer:
            assert isinstance(checkpointer, AsyncSqliteSaver)


@pytest.mark.anyio
async def test_create_checkpointer_creates_parent_directory():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "nested", "dir", "checkpoints.db")
        async with create_checkpointer(db_path=db_path):
            assert os.path.isdir(os.path.join(tmpdir, "nested", "dir"))


@pytest.mark.anyio
async def test_create_checkpointer_uses_settings_path(monkeypatch, tmp_path):
    db_path = str(tmp_path / "settings_checkpoints.db")
    monkeypatch.setattr(
        "app.agent.memory.checkpointer.settings.CHECKPOINT_DB_PATH", db_path
    )
    async with create_checkpointer() as checkpointer:
        assert isinstance(checkpointer, AsyncSqliteSaver)
