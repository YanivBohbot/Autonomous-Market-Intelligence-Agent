from __future__ import annotations

import os
import sqlite3

import pytest

from app.report_catalog import list_generated_reports, resolve_generated_report


def _db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE clients (name TEXT NOT NULL, email TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO clients (name, email) VALUES (?, ?)",
        [("Margaret Collins", "margaret@example.com"), ("Jane Doe", "jane@example.com")],
    )
    conn.commit()
    conn.close()


def test_lists_only_recipient_reports_newest_first(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    older = reports / "margaret-collins-portfolio-brief-2026-10-01.xlsx"
    newer = reports / "margaret-collins-portfolio-brief-2026-10-06.xlsx"
    other = reports / "jane-doe-portfolio-brief-2026-10-06.xlsx"
    for path in (older, newer, other):
        path.write_bytes(path.name.encode())
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    items = list_generated_reports(
        "MARGARET@example.com", db_path=db, workspace_root=tmp_path / "workspace"
    )

    assert [item.filename for item in items] == [newer.name, older.name]
    assert all(item.size_bytes > 0 for item in items)


def test_unknown_recipient_has_empty_catalog(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    assert list_generated_reports(
        "unknown@example.com", db_path=db, workspace_root=tmp_path / "workspace"
    ) == []


@pytest.mark.parametrize("filename", ["../secret.txt", "..\\secret.txt", "/tmp/secret.txt"])
def test_rejects_unsafe_names(tmp_path, filename):
    db = tmp_path / "customers.db"
    _db(db)
    with pytest.raises(ValueError, match="unsafe report filename"):
        resolve_generated_report(
            "margaret@example.com", filename, db_path=db, workspace_root=tmp_path / "workspace"
        )


def test_rejects_another_clients_report(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    filename = "jane-doe-portfolio-brief-2026-10-06.xlsx"
    (reports / filename).write_bytes(b"report")
    with pytest.raises(ValueError, match="does not belong to recipient"):
        resolve_generated_report(
            "margaret@example.com", filename, db_path=db, workspace_root=tmp_path / "workspace"
        )


def test_rejects_a_report_deleted_after_listing(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    filename = "margaret-collins-portfolio-brief-2026-10-06.xlsx"
    path = reports / filename
    path.write_bytes(b"report")
    path.unlink()
    with pytest.raises(ValueError, match="report not found"):
        resolve_generated_report(
            "margaret@example.com", filename, db_path=db, workspace_root=tmp_path / "workspace"
        )


def test_rejects_symlink_escape(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"secret")
    link = reports / "margaret-collins-portfolio-brief-linked.xlsx"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="report escapes workspace"):
        resolve_generated_report(
            "margaret@example.com", link.name,
            db_path=db, workspace_root=tmp_path / "workspace",
        )
