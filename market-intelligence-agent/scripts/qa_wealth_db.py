"""Live grounded QA for the wealth-management DB (network + API keys).
Expected values come from customers.db and from the tool outputs of the
same run — never from the agent. Run: PYTHONPATH=. uv run python scripts/qa_wealth_db.py"""
import asyncio
import json
import re
import sqlite3
import uuid
from datetime import date

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

import create_db as seed
from app.agent.multi_agent import build_multi_agent_app

if not seed.DB_PATH.exists():
    raise FileNotFoundError(
        f"customers.db not found at {seed.DB_PATH} — run `uv run python create_db.py` first"
    )
DB = sqlite3.connect(seed.DB_PATH)
RESULTS = []


def holders(ticker):
    return {r[0] for r in DB.execute(
        "SELECT c.name FROM holdings h JOIN clients c USING (client_id) WHERE h.ticker = ?", (ticker,))}


def all_client_names():
    return {r[0] for r in DB.execute("SELECT name FROM clients")}


def record(case, ok, detail):
    RESULTS.append((case, ok))
    print(f"{'PASS' if ok else 'FAIL'} | {case} | {detail}", flush=True)


def calls(msgs):
    return [tc for m in msgs if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]


def answer(msgs):
    return next((m.content for m in reversed(msgs) if isinstance(m, AIMessage) and not m.tool_calls and m.content), "")


def tool_outputs(msgs, name):
    return [m.content if isinstance(m.content, str) else json.dumps(m.content)
            for m in msgs if isinstance(m, ToolMessage) and (m.name or "").endswith(name)]


def money_variants(x):
    return {f"{x:,.2f}", f"{x:.2f}", f"{x:,.0f}", f"{round(x):,}"}


def _extract_price(content):
    """Pull a current-price float out of a yfinance_get_ticker_info
    ToolMessage.content, which may be a plain string or a list of content
    blocks like [{"type": "text", "text": "<json>"}]."""
    blocks = content if isinstance(content, list) else [content]
    for block in blocks:
        text = block.get("text") if isinstance(block, dict) else block
        if not isinstance(text, str):
            continue
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("currentPrice", "regularMarketPrice", "price"):
            if data.get(key) is not None:
                try:
                    return float(data[key])
                except (TypeError, ValueError):
                    continue
    return None


def prices_from_ticker_info(msgs):
    """{ticker: price} built from this run's yfinance_get_ticker_info tool
    calls/results — the same data the agent itself saw, never a fresh fetch."""
    id_to_symbol = {
        tc["id"]: (tc["args"] or {}).get("symbol")
        for tc in calls(msgs)
        if (tc.get("name") or "").endswith("yfinance_get_ticker_info")
    }
    prices = {}
    for m in msgs:
        if not (isinstance(m, ToolMessage) and (m.name or "").endswith("yfinance_get_ticker_info")):
            continue
        symbol = id_to_symbol.get(m.tool_call_id)
        price = _extract_price(m.content)
        if symbol and price is not None:
            prices[symbol.upper()] = price
    return prices


def expected_w3_concentration(prices):
    """Conservative clients with a non-ETF position >30% of their portfolio,
    computed by code from customers.db holdings x prices (falling back to
    create_db.price_at at the 2026 anchor for any ticker this run never
    fetched). This is the grounding for W3 — never the agent's own answer."""
    sectors = {r[0]: r[1] for r in DB.execute("SELECT ticker, sector FROM companies")}
    conservative = DB.execute("SELECT client_id, name FROM clients WHERE risk_profile = 'conservative'").fetchall()
    anchor = date(2026, 7, 1)
    expected = set()
    for client_id, name in conservative:
        rows = DB.execute("SELECT ticker, shares FROM holdings WHERE client_id = ?", (client_id,)).fetchall()
        values = {}
        for ticker, shares in rows:
            price = prices.get(ticker.upper())
            if price is None:
                price = seed.price_at(ticker, anchor)
            values[ticker] = shares * price
        total = sum(values.values())
        if total <= 0:
            continue
        for ticker, mv in values.items():
            if sectors.get(ticker) != "ETF" and mv / total > 0.30:
                expected.add(name)
                break
    return expected



async def multi():
    app = build_multi_agent_app(InMemorySaver(), InMemoryStore())
    cfg = {"configurable": {"thread_id": str(uuid.uuid4()), "actor_id": "qa"}, "recursion_limit": 80}
    routed, used = [], set()
    async for ns, upd in app.astream({"question": "What is the total market value of Martin Levy's portfolio today?",
                                      "messages": [], "documents": [], "next_agent": None, "agent_hops": 0},
                                     cfg, stream_mode="updates", subgraphs=True):
        for node, val in upd.items():
            if not isinstance(val, dict):
                continue
            if node == "supervisor" and val.get("next_agent"):
                routed.append(val["next_agent"])
            used |= {tc["name"].rsplit("___", 1)[-1] for tc in calls(val.get("messages", []))}
    record("W5 multi: portfolio_agent computes value", routed[:1] == ["portfolio_agent"] and "portfolio_metrics" in used,
           f"routed={routed} tools={sorted(used)}")


async def main():
    await multi()
    print(f"\nSUMMARY {sum(ok for _, ok in RESULTS)}/{len(RESULTS)} passed")


if __name__ == "__main__":
    asyncio.run(main())
