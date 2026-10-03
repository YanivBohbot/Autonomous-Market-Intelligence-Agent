"""Read-only clients/holdings/documents view, plus PDF->RAG and
Excel->DB imports, for the React console's /data section. Deliberately
NOT wired into the agent graph: this is deterministic CRUD and ingestion,
not an agent capability -- see docs/superpowers/specs/
2026-10-03-data-import-and-view-design.md Decision 9."""

import json
import sqlite3

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.data_import.db import (
    DB_PATH,
    client_id_by_email,
    existing_client_emails,
    known_tickers,
    list_clients_with_holdings,
    write_clients,
    write_holdings,
)
from app.data_import.pdf_ingest import ingest_single_pdf
from app.data_import.validation import (
    detect_import_type,
    validate_clients_rows,
    validate_holdings_rows,
)

router = APIRouter(prefix="/data")


class ImportRowsRequest(BaseModel):
    rows: list[dict]


class ImportConfirmRequest(BaseModel):
    type: str
    rows: list[dict]


def _validate(conn: sqlite3.Connection, rows: list[dict]):
    kind = detect_import_type(rows)
    if kind is None:
        return None, None
    if kind == "clients":
        return kind, validate_clients_rows(rows, existing_emails=existing_client_emails(conn))
    return kind, validate_holdings_rows(
        rows, client_id_by_email=client_id_by_email(conn), known_tickers=known_tickers(conn)
    )


@router.get("/clients")
async def get_clients() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        return list_clients_with_holdings(conn)
    finally:
        conn.close()


@router.get("/documents")
async def get_documents() -> list[str]:
    if not KB_MANIFEST_PATH.exists():
        return []
    return json.loads(KB_MANIFEST_PATH.read_text())


@router.post("/import/preview")
async def import_preview(payload: ImportRowsRequest) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        kind, result = _validate(conn, payload.rows)
    finally:
        conn.close()
    if kind is None:
        raise HTTPException(status_code=400, detail="unrecognized file format")
    return {"type": kind, **result}


@router.post("/import/confirm")
async def import_confirm(payload: ImportConfirmRequest) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        kind, result = _validate(conn, payload.rows)
        if kind != payload.type or not result["valid"]:
            raise HTTPException(status_code=409, detail="validation changed since preview, please re-upload")
        try:
            with conn:
                if kind == "clients":
                    write_clients(conn, result["rows"])
                else:
                    write_holdings(conn, result["rows"])
        except sqlite3.DatabaseError as exc:
            raise HTTPException(status_code=500, detail=f"write failed: {exc}") from exc
        return {"written": len(result["rows"])}
    finally:
        conn.close()


@router.post("/import/pdf")
async def import_pdf(file: UploadFile = File(...)) -> dict:
    body = await file.read()
    filename = file.filename or "upload.pdf"
    if not body.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="invalid PDF")
    # Any failure past this point (a real PDF that OpenAI/Pinecone fails to
    # embed/upsert) is a 500, not a 400 -- it's not the user's input that's
    # wrong. Caught explicitly (rather than left to propagate) because
    # Starlette's TestClient defaults to raise_server_exceptions=True, which
    # would otherwise re-raise instead of yielding a 500 response.
    try:
        chunk_count = ingest_single_pdf(body, filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ingestion failed: {exc}") from exc
    return {"filename": filename, "chunks_added": chunk_count}
