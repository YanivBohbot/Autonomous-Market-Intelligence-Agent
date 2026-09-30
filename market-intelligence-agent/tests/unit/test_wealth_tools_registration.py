import asyncio

from app.agent.tools import (
    READ_ONLY_TOOLS,
    TOOLS,
    crm_describe_table_tool,
    crm_list_tables_tool,
    is_read_only,
)

NEW_TOOLS = {"list_tables", "describe_table", "portfolio_metrics", "pct_change", "concentration_screen"}


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


def test_save_portfolio_report_is_registered_but_not_read_only():
    # Regression risk this plan introduces: generate_portfolio_report (the
    # tool this replaces) WAS read-only, since it never wrote anything
    # itself. save_portfolio_report DOES write to disk now -- if it were
    # ever added to READ_ONLY_TOOLS (by habit, copying the old entry), the
    # single-agent graph's approval_node would skip the HITL interrupt
    # entirely and the tool would execute with no approval gate at all.
    assert "save_portfolio_report" in _names()
    assert "save_portfolio_report" not in READ_ONLY_TOOLS
    assert not is_read_only("save_portfolio_report")
    assert not is_read_only("sqlite-crm___save_portfolio_report")
