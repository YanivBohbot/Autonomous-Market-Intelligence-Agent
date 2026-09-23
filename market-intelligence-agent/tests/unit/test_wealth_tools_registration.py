import asyncio

from app.agent.tools import (
    READ_ONLY_TOOLS,
    TOOLS,
    crm_describe_table_tool,
    crm_list_tables_tool,
    is_read_only,
)

NEW_TOOLS = {"list_tables", "describe_table", "portfolio_metrics", "pct_change"}


def _names():
    return {t.name.rsplit("___", 1)[-1] for t in TOOLS}


def test_new_tools_are_registered():
    assert NEW_TOOLS <= _names()


def test_new_tools_are_read_only_including_gateway_prefix():
    assert NEW_TOOLS <= READ_ONLY_TOOLS
    for name in NEW_TOOLS:
        assert is_read_only(name)
        assert is_read_only(f"sqlite-crm___{name}")


def test_write_capable_sqlite_tools_are_not_exposed():
    assert not {"write_query", "create_table", "append_insight"} & _names()


def test_list_tables_reads_the_wealth_schema():
    out = str(asyncio.run(crm_list_tables_tool.ainvoke({})))
    for table in ("companies", "clients", "transactions", "holdings", "watchlists"):
        assert table in out


def test_describe_table_returns_columns():
    out = str(asyncio.run(crm_describe_table_tool.ainvoke({"table_name": "holdings"})))
    for column in ("client_id", "ticker", "shares", "avg_cost"):
        assert column in out
