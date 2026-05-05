import os
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from app.core.config import settings


def create_checkpointer(db_path: str | None = None) -> SqliteSaver:
    path = db_path or settings.CHECKPOINT_DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn)
