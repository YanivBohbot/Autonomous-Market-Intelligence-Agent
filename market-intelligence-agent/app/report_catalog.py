from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.data_import.db import DB_PATH
from app.report_names import slugify


@dataclass(frozen=True)
class GeneratedReport:
    filename: str
    generated_at: str
    size_bytes: int


def _paths(
    db_path: str | Path | None,
    workspace_root: str | Path | None,
) -> tuple[Path, Path]:
    return Path(db_path or DB_PATH), Path(workspace_root or settings.WORKSPACE_ROOT)


def _client_prefix(recipient: str, db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT name FROM clients WHERE lower(email) = lower(?)",
            (recipient.strip(),),
        ).fetchone()
    return None if row is None else f"{slugify(row[0])}-portfolio-brief-"


def list_generated_reports(
    recipient: str,
    *,
    db_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> list[GeneratedReport]:
    database, workspace = _paths(db_path, workspace_root)
    prefix = _client_prefix(recipient, database)
    if prefix is None:
        return []

    root = (workspace / "reports").resolve()
    if not root.is_dir():
        return []

    items: list[GeneratedReport] = []
    for candidate in root.glob(f"{prefix}*"):
        resolved = candidate.resolve()
        if resolved.parent != root or not resolved.is_file():
            continue
        stat = resolved.stat()
        items.append(GeneratedReport(
            filename=candidate.name,
            generated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            size_bytes=stat.st_size,
        ))
    return sorted(items, key=lambda item: item.generated_at, reverse=True)


def resolve_generated_report(
    recipient: str,
    filename: str,
    *,
    db_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> Path:
    database, workspace = _paths(db_path, workspace_root)
    if not filename or "/" in filename or "\\" in filename or Path(filename).name != filename:
        raise ValueError("unsafe report filename")

    prefix = _client_prefix(recipient, database)
    if prefix is None:
        raise ValueError("recipient is not a client")
    if not filename.startswith(prefix):
        raise ValueError("report does not belong to recipient")

    root = (workspace / "reports").resolve()
    resolved = (root / filename).resolve()
    if resolved.parent != root:
        raise ValueError("report escapes workspace")
    if not resolved.is_file():
        raise ValueError("report not found")
    return resolved
