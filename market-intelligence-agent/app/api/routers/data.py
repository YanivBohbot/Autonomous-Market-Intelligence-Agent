"""Read-only clients/holdings/documents view, plus PDF->RAG and
Excel->DB imports, for the React console's /data section. Deliberately
NOT wired into the agent graph: this is deterministic CRUD and ingestion,
not an agent capability -- see docs/superpowers/specs/
2026-10-03-data-import-and-view-design.md Decision 9."""

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.agent.tools.concentration import parse_tool_payload, price_from_quote
from app.agent.tools.finance_calc import (
    LabeledPortfolio,
    Position,
    compute_concentration_screen,
    compute_portfolio_metrics,
)
from app.agent.tools.knowledge_base import KB_MANIFEST_PATH
from app.agent.tools.portfolio_report import build_portfolio_report_xlsx, slugify
from app.core.config import settings
from app.data_import.client_summary import build_client_summary
from app.data_import.db import (
    DB_PATH,
    client_id_by_email,
    existing_client_emails,
    get_client_with_holdings,
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


async def _live_price(ticker: str) -> float:
    # Deferred import: avoids connecting to the yfinance MCP server at
    # module import time for every test that imports this router, same
    # convention as client_portfolio_tool / concentration_screen_tool.
    from app.agent.tools.mcp_clients.yfinance_client import yf_quote_tool

    symbol_arg = "symbol" if "symbol" in yf_quote_tool.args else "ticker"
    return price_from_quote(parse_tool_payload(await yf_quote_tool.ainvoke({symbol_arg: ticker})))


@router.get("/clients/{client_id}/summary")
async def get_client_summary(client_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, client_id)
    finally:
        conn.close()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    return await build_client_summary(client=client, get_price=_live_price)


def _tool_content_text(result) -> str:
    # Same content-block-joining step parse_tool_payload does, stopped
    # before its JSON/literal_eval attempt -- yfinance_get_price_history's
    # raw text is a markdown table, not JSON, and would fail both.
    if isinstance(result, list) and result and all(isinstance(b, dict) and "type" in b for b in result):
        return "".join(b.get("text", "") for b in result if b.get("type") == "text")
    return str(result)


async def _price_history(ticker: str) -> list[dict]:
    from app.agent.multi_agent.display import normalize_price_history
    from app.agent.tools.mcp_clients.yfinance_client import yf_history_tool

    symbol_arg = "symbol" if "symbol" in yf_history_tool.args else "ticker"
    raw = await yf_history_tool.ainvoke({symbol_arg: ticker, "period": "3mo"})
    text = _tool_content_text(raw)
    displays = normalize_price_history(text, {symbol_arg: ticker})
    return displays[0]["points"] if displays else []


@router.get("/clients/{client_id}/report")
async def get_client_report(client_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, client_id)
    finally:
        conn.close()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")

    holdings = client["holdings"]
    tickers = [h["ticker"] for h in holdings]
    price_results = await asyncio.gather(*(_live_price(t) for t in tickers), return_exceptions=True)

    priced_positions: list[Position] = []
    unpriced_tickers: list[str] = []
    for holding, result in zip(holdings, price_results):
        if isinstance(result, BaseException):
            unpriced_tickers.append(holding["ticker"])
            continue
        priced_positions.append(Position(
            ticker=holding["ticker"], shares=holding["shares"], avg_cost=holding["avg_cost"],
            price=float(result), sector=holding.get("sector"),
        ))

    totals: dict | None = None
    positions: list[dict] = []
    sector_allocation: dict | None = None
    concentration: dict | None = None
    price_history: dict[str, list[dict]] = {}

    if priced_positions:
        metrics = compute_portfolio_metrics(priced_positions)
        totals = metrics["totals"]
        positions = metrics["positions"]
        sector_allocation = metrics["sector_allocation"]
        concentration = compute_concentration_screen(
            [LabeledPortfolio(label=client["name"], positions=priced_positions)],
            threshold_pct=30.0,
        )
        top = sorted(positions, key=lambda p: -p["weight_pct"])[:3]
        history_results = await asyncio.gather(
            *(_price_history(p["ticker"]) for p in top), return_exceptions=True,
        )
        for p, result in zip(top, history_results):
            if not isinstance(result, BaseException) and result:
                price_history[p["ticker"]] = result

    reports_dir = settings.WORKSPACE_ROOT.resolve() / "reports"
    prefix = f"{slugify(client['name'])}-portfolio-brief-"
    files = sorted(
        (f for f in reports_dir.glob(f"{prefix}*.xlsx") if f.is_file()),
        key=lambda f: f.stat().st_mtime, reverse=True,
    ) if reports_dir.is_dir() else []
    generated_reports = [
        {
            "filename": f.name,
            "generated_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            "download_url": f"/workspace/files/{f.name}",
        }
        for f in files
    ]

    return {
        "client_id": client["client_id"], "name": client["name"], "email": client["email"],
        "segment": client["segment"], "risk_profile": client["risk_profile"],
        "advisor": client["advisor"], "city": client["city"],
        "totals": totals, "positions": positions, "sector_allocation": sector_allocation,
        "concentration": concentration, "price_history": price_history,
        "unpriced_tickers": unpriced_tickers, "generated_reports": generated_reports,
    }


@router.post("/clients/{client_id}/report/generate")
async def generate_client_report(client_id: int) -> dict:
    if settings.MCP_TRANSPORT.lower() == "gateway":
        raise HTTPException(
            status_code=503,
            detail="save_portfolio_report is not available in this deployment "
            "(MCP_TRANSPORT=gateway has no S3 write path for this tool yet).",
        )
    conn = sqlite3.connect(DB_PATH)
    try:
        client = get_client_with_holdings(conn, client_id)
    finally:
        conn.close()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")

    holdings = client["holdings"]
    if not holdings:
        raise HTTPException(status_code=400, detail="build_portfolio_report_xlsx needs at least one position")

    tickers = [h["ticker"] for h in holdings]
    price_results = await asyncio.gather(*(_live_price(t) for t in tickers), return_exceptions=True)
    failed = [t for t, r in zip(tickers, price_results) if isinstance(r, BaseException)]
    if failed:
        raise HTTPException(status_code=502, detail=f"could not price: {', '.join(failed)}")

    positions = [
        Position(ticker=h["ticker"], shares=h["shares"], avg_cost=h["avg_cost"], price=float(r))
        for h, r in zip(holdings, price_results)
    ]
    portfolio = compute_portfolio_metrics(positions)
    portfolio["client_name"] = client["name"]

    xlsx_bytes = await asyncio.to_thread(build_portfolio_report_xlsx, portfolio)
    today = datetime.now(timezone.utc).date().isoformat()
    filename = f"{slugify(client['name'])}-portfolio-brief-{today}.xlsx"
    reports_dir = settings.WORKSPACE_ROOT.resolve() / "reports"

    def _write() -> None:
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / filename).write_bytes(xlsx_bytes)

    await asyncio.to_thread(_write)
    return {"filename": filename}


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
    filename = os.path.basename(file.filename) if file.filename else "upload.pdf"
    if not body.startswith(b"%PDF") or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="invalid PDF")
    # Any failure past this point (a real PDF that OpenAI/Pinecone fails to
    # embed/upsert) is a 500, not a 400 -- it's not the user's input that's
    # wrong. Caught explicitly (rather than left to propagate) because
    # Starlette's TestClient defaults to raise_server_exceptions=True, which
    # would otherwise re-raise instead of yielding a 500 response.
    # ingest_single_pdf makes real network-bound OpenAI/Pinecone calls that
    # can take tens of seconds -- run it off the event loop so it doesn't
    # freeze /stream, the voice worker, or Market Desk for other users.
    try:
        chunk_count = await run_in_threadpool(ingest_single_pdf, body, filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ingestion failed: {exc}") from exc
    return {"filename": filename, "chunks_added": chunk_count}
