import os
import tempfile
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from app.agent.memory.checkpointer import create_checkpointer


def test_create_checkpointer_returns_sqlite_saver():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_checkpoints.db")
        checkpointer = create_checkpointer(db_path=db_path)
        assert isinstance(checkpointer, SqliteSaver)
        checkpointer.conn.close()


def test_create_checkpointer_creates_parent_directory():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "nested", "dir", "checkpoints.db")
        checkpointer = create_checkpointer(db_path=db_path)
        assert os.path.isdir(os.path.join(tmpdir, "nested", "dir"))
        checkpointer.conn.close()
