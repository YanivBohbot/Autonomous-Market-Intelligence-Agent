from app.agent.prompts.system import SYSTEM_PROMPT


def test_legacy_customers_schema_removed():
    assert "total_spend" not in SYSTEM_PROMPT
    assert "table: `customers`" not in SYSTEM_PROMPT


def test_describes_wealth_tables_and_new_tools():
    for text in ("companies", "clients", "holdings", "transactions", "watchlists", "kb_document",
                 "list_tables", "describe_table", "portfolio_metrics", "pct_change"):
        assert text in SYSTEM_PROMPT


def test_portfolio_recipe_and_no_arithmetic_rule():
    assert "Portfolio recipe" in SYSTEM_PROMPT
    assert "Never do arithmetic" in SYSTEM_PROMPT
