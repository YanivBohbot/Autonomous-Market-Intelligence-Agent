from __future__ import annotations

import re
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
    client_name: str


def _paths(
    db_path: str | Path | None,
    workspace_root: str | Path | None,
) -> tuple[Path, Path]:
    return Path(db_path or DB_PATH), Path(workspace_root or settings.WORKSPACE_ROOT)


def _client_prefixes(db_path: Path) -> tuple[dict[str, str], set[str]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM clients").fetchall()

    owners: dict[str, list[str]] = {}
    for row in rows:
        name = str(row[0]).strip()
        if not name:
            continue
        prefix = f"{slugify(name)}-portfolio-brief-"
        owners.setdefault(prefix, []).append(name)

    unique = {
        prefix: names[0]
        for prefix, names in owners.items()
        if len(names) == 1
    }
    ambiguous = {prefix for prefix, names in owners.items() if len(names) != 1}
    return unique, ambiguous


def _report_owner(
    filename: str,
    owners: dict[str, str],
    ambiguous: set[str],
) -> str | None:
    if any(filename.startswith(prefix) for prefix in ambiguous):
        raise ValueError("client report ownership is ambiguous")

    matches = [
        (prefix, client_name)
        for prefix, client_name in owners.items()
        if filename.startswith(prefix)
    ]
    if len(matches) > 1:
        raise ValueError("client report ownership is ambiguous")
    if not matches:
        return None

    prefix, client_name = matches[0]
    suffix = filename[len(prefix):]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.xlsx", suffix) is None:
        return None
    return client_name


def list_generated_reports(
    *,
    db_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> list[GeneratedReport]:
    database, workspace = _paths(db_path, workspace_root)
    owners, ambiguous = _client_prefixes(database)

    root = (workspace / "reports").resolve()
    if not root.is_dir():
        return []

    items: list[GeneratedReport] = []
    for candidate in root.iterdir():
        resolved = candidate.resolve()
        if resolved.parent != root or not resolved.is_file():
            continue
        try:
            client_name = _report_owner(candidate.name, owners, ambiguous)
        except ValueError:
            continue
        if client_name is None:
            continue
        stat = resolved.stat()
        items.append(GeneratedReport(
            filename=candidate.name,
            generated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            size_bytes=stat.st_size,
            client_name=client_name,
        ))
    return sorted(items, key=lambda item: item.generated_at, reverse=True)


def resolve_generated_report(
    filename: str,
    *,
    db_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> Path:
    database, workspace = _paths(db_path, workspace_root)
    if not filename or "/" in filename or "\\" in filename or Path(filename).name != filename:
        raise ValueError("unsafe report filename")

    root = (workspace / "reports").resolve()
    resolved = (root / filename).resolve()
    if resolved.parent != root:
        raise ValueError("report escapes workspace")

    owners, ambiguous = _client_prefixes(database)
    if _report_owner(filename, owners, ambiguous) is None:
        raise ValueError("not a generated client report")
    if not resolved.is_file():
        raise ValueError("report not found")
    return resolved
