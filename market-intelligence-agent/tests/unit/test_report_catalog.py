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


def test_lists_all_generated_client_reports_newest_first(tmp_path):
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
    os.utime(other, (3, 3))

    items = list_generated_reports(
        db_path=db, workspace_root=tmp_path / "workspace"
    )

    assert [item.filename for item in items] == [other.name, newer.name, older.name]
    assert [item.client_name for item in items] == ["Jane Doe", "Margaret Collins", "Margaret Collins"]
    assert all(item.size_bytes > 0 for item in items)


def test_catalog_ignores_files_that_are_not_generated_client_reports(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    (reports / "notes.xlsx").write_bytes(b"not generated")

    assert list_generated_reports(db_path=db, workspace_root=tmp_path / "workspace") == []


def test_duplicate_client_names_fail_closed_for_ambiguous_reports(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO clients (name, email) VALUES (?, ?)",
            ("Margaret Collins", "other.margaret@example.com"),
        )
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    report = reports / "margaret-collins-portfolio-brief-2026-10-06.xlsx"
    report.write_bytes(b"report")

    assert list_generated_reports(db_path=db, workspace_root=tmp_path / "workspace") == []
    with pytest.raises(ValueError, match="ownership is ambiguous"):
        resolve_generated_report(
            report.name,
            db_path=db,
            workspace_root=tmp_path / "workspace",
        )


@pytest.mark.parametrize("filename", ["../secret.txt", "..\\secret.txt", "/tmp/secret.txt"])
def test_rejects_unsafe_names(tmp_path, filename):
    db = tmp_path / "customers.db"
    _db(db)
    with pytest.raises(ValueError, match="unsafe report filename"):
        resolve_generated_report(
            filename, db_path=db, workspace_root=tmp_path / "workspace"
        )


def test_resolves_any_generated_client_report_independent_of_email_recipient(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    filename = "jane-doe-portfolio-brief-2026-10-06.xlsx"
    (reports / filename).write_bytes(b"report")
    resolved = resolve_generated_report(
        filename, db_path=db, workspace_root=tmp_path / "workspace"
    )
    assert resolved == reports / filename


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
            filename, db_path=db, workspace_root=tmp_path / "workspace"
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
            link.name,
            db_path=db, workspace_root=tmp_path / "workspace",
        )


def test_rejects_existing_file_that_is_not_a_generated_client_report(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    filename = "arbitrary-upload.xlsx"
    (reports / filename).write_bytes(b"not generated")

    with pytest.raises(ValueError, match="not a generated client report"):
        resolve_generated_report(
            filename, db_path=db, workspace_root=tmp_path / "workspace"
        )
