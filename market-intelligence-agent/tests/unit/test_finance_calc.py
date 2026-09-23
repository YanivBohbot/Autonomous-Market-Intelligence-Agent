import pytest

from app.agent.tools.finance_calc import (
    LabeledPortfolio,
    Position,
    compute_concentration_screen,
    compute_pct_change,
    compute_portfolio_metrics,
    concentration_screen_tool,
    pct_change_tool,
    portfolio_metrics_tool,
)


def _positions(with_sector=True):
    return [
        Position(ticker="AAA", shares=10, avg_cost=50, price=60, sector="Tech" if with_sector else None),
        Position(ticker="BBB", shares=5, avg_cost=100, price=80, sector="Energy" if with_sector else None),
    ]


def test_per_position_metrics():
    result = compute_portfolio_metrics(_positions())
    aaa, bbb = result["positions"]
    assert (aaa["market_value"], aaa["cost_basis"], aaa["unrealized_pnl"], aaa["unrealized_pnl_pct"], aaa["weight_pct"]) == (600.0, 500.0, 100.0, 20.0, 60.0)
    assert (bbb["market_value"], bbb["cost_basis"], bbb["unrealized_pnl"], bbb["unrealized_pnl_pct"], bbb["weight_pct"]) == (400.0, 500.0, -100.0, -20.0, 40.0)


def test_totals():
    assert compute_portfolio_metrics(_positions())["totals"] == {
        "market_value": 1000.0, "cost_basis": 1000.0, "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0,
    }


def test_sector_allocation_when_every_position_has_a_sector():
    assert compute_portfolio_metrics(_positions())["sector_allocation"] == {"Tech": 60.0, "Energy": 40.0}


def test_sector_allocation_is_none_when_a_sector_is_missing():
    assert compute_portfolio_metrics(_positions(with_sector=False))["sector_allocation"] is None


def test_rounding_to_two_decimals():
    result = compute_portfolio_metrics([Position(ticker="X", shares=3, avg_cost=10.006, price=33.333)])
    p = result["positions"][0]
    assert p["market_value"] == 100.0
    assert p["cost_basis"] == 30.02
    assert p["weight_pct"] == 100.0


def test_duplicate_ticker_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        compute_portfolio_metrics([Position(ticker="X", shares=1, avg_cost=1, price=1), Position(ticker="x", shares=1, avg_cost=1, price=1)])


def test_empty_positions_rejected():
    with pytest.raises(ValueError, match="at least one"):
        compute_portfolio_metrics([])


def test_non_positive_values_rejected_by_schema():
    with pytest.raises(ValueError):
        Position(ticker="X", shares=0, avg_cost=1, price=1)
    with pytest.raises(ValueError):
        Position(ticker="X", shares=1, avg_cost=1, price=-5)


def test_pct_change():
    assert compute_pct_change(22387, 28236) == {"old": 22387.0, "new": 28236.0, "change": 5849.0, "pct_change": 26.13}
    assert compute_pct_change(-100, -50)["pct_change"] == 50.0


def test_pct_change_rejects_zero_base():
    with pytest.raises(ValueError, match="old"):
        compute_pct_change(0, 10)


def test_tools_accept_plain_dicts_from_the_llm():
    out = portfolio_metrics_tool.invoke({"positions": [
        {"ticker": "AAA", "shares": 10, "avg_cost": 50, "price": 60, "sector": "Tech"},
        {"ticker": "BBB", "shares": 5, "avg_cost": 100, "price": 80, "sector": "Energy"},
    ]})
    assert out["totals"]["market_value"] == 1000.0
    assert pct_change_tool.invoke({"old": 100, "new": 110})["pct_change"] == 10.0


def test_tool_names():
    assert portfolio_metrics_tool.name == "portfolio_metrics"
    assert pct_change_tool.name == "pct_change"


# --- concentration_screen -----------------------------------------------
# Regression fixture for a real bug: given several labeled portfolios, the
# LLM's own prose enumeration of "which ones breach X%" intermittently
# dropped a qualifying portfolio even though every portfolio_metrics result
# had the right weight_pct. concentration_screen makes that list-building
# step deterministic code instead of LLM synthesis.

def _margaret_collins():
    # Mirrors the real fixture: NVDA bought cheap (avg_cost 30.7), now
    # dominates the portfolio at the current price -- the concentrated case.
    return LabeledPortfolio(label="Margaret Collins", positions=[
        Position(ticker="BND", shares=300, avg_cost=73.33, price=71.41, sector="Intermediate Core Bond"),
        Position(ticker="JNJ", shares=100, avg_cost=175, price=269.19, sector="Healthcare"),
        Position(ticker="KO", shares=200, avg_cost=62, price=88.61, sector="Consumer Defensive"),
        Position(ticker="NVDA", shares=400, avg_cost=30.7, price=228.87, sector="Technology"),
    ])


def _susan_grant():
    # Top position (BND) is 33.28% -- concentrated at a 30% threshold, but
    # well under 50%, so this fixture is used to test the 50%-threshold
    # "no breach" case below.
    return LabeledPortfolio(label="Susan Grant", positions=[
        Position(ticker="BND", shares=250, avg_cost=72.45, price=71.41, sector="Intermediate Core Bond"),
        Position(ticker="JNJ", shares=60, avg_cost=175, price=269.19, sector="Healthcare"),
        Position(ticker="KO", shares=150, avg_cost=62, price=88.61, sector="Consumer Defensive"),
        Position(ticker="XOM", shares=40, avg_cost=110.42, price=158.71, sector="Energy"),
    ])


def test_concentration_screen_flags_only_the_breaching_position():
    result = compute_concentration_screen([_margaret_collins()], threshold_pct=30.0)
    assert result["breach_count"] == 1
    breach = result["breaches"][0]
    assert breach["label"] == "Margaret Collins"
    assert breach["ticker"] == "NVDA"
    assert breach["weight_pct"] == 58.08


def test_concentration_screen_no_breach_when_nothing_exceeds_threshold():
    result = compute_concentration_screen([_susan_grant()], threshold_pct=50.0)
    assert result["breach_count"] == 0
    assert result["breaches"] == []
    assert result["screened_labels"] == ["Susan Grant"]


def test_concentration_screen_multiple_portfolios_never_drops_a_qualifying_one():
    # This is the exact shape of the real failure: several labeled
    # portfolios screened together, one of which (Margaret Collins) must
    # appear in `breaches` -- the caller no longer has to enumerate this
    # from several separate portfolio_metrics results itself. Threshold 50%:
    # Susan Grant's top position (33.28%) does not qualify, Margaret
    # Collins' NVDA (58.08%) does.
    result = compute_concentration_screen(
        [_susan_grant(), _margaret_collins()], threshold_pct=50.0
    )
    assert result["screened_count"] == 2
    labels_with_breaches = {b["label"] for b in result["breaches"]}
    assert labels_with_breaches == {"Margaret Collins"}
    assert result["breaches"][0]["ticker"] == "NVDA"


def test_concentration_screen_sorted_by_weight_desc_for_determinism():
    heavy = LabeledPortfolio(label="Heavy", positions=[Position(ticker="X", shares=1, avg_cost=1, price=1, sector="A")])
    # 100% weight since it's the only position -- always a breach at any threshold < 100.
    light = LabeledPortfolio(label="Light", positions=[
        Position(ticker="Y", shares=1, avg_cost=1, price=1, sector="A"),
        Position(ticker="Z", shares=1, avg_cost=1, price=3, sector="A"),
    ])
    result = compute_concentration_screen([light, heavy], threshold_pct=50.0)
    weights = [b["weight_pct"] for b in result["breaches"]]
    assert weights == sorted(weights, reverse=True)


def test_concentration_screen_rejects_empty_portfolio_list():
    with pytest.raises(ValueError, match="at least one"):
        compute_concentration_screen([], threshold_pct=30.0)


def test_concentration_screen_rejects_non_positive_threshold():
    with pytest.raises(ValueError, match="threshold_pct"):
        compute_concentration_screen([_susan_grant()], threshold_pct=0)


def test_concentration_screen_tool_accepts_plain_dicts_from_the_llm():
    out = concentration_screen_tool.invoke({
        "portfolios": [
            {"label": "Margaret Collins", "positions": [
                {"ticker": "BND", "shares": 300, "avg_cost": 73.33, "price": 71.41, "sector": "Intermediate Core Bond"},
                {"ticker": "NVDA", "shares": 400, "avg_cost": 30.7, "price": 228.87, "sector": "Technology"},
            ]},
        ],
        "threshold_pct": 30,
    })
    assert out["breach_count"] == 1
    assert out["breaches"][0]["ticker"] == "NVDA"


def test_concentration_screen_default_threshold_is_30_pct():
    out = concentration_screen_tool.invoke({"portfolios": [
        {"label": "Margaret Collins", "positions": [
            {"ticker": "BND", "shares": 300, "avg_cost": 73.33, "price": 71.41, "sector": "Intermediate Core Bond"},
            {"ticker": "NVDA", "shares": 400, "avg_cost": 30.7, "price": 228.87, "sector": "Technology"},
        ]},
    ]})
    assert out["threshold_pct"] == 30.0
    assert out["breach_count"] == 1


def test_concentration_screen_tool_name():
    assert concentration_screen_tool.name == "concentration_screen"


def test_concentration_screen_portfolios_field_tells_caller_to_include_every_position():
    # Regression: live grounded QA (W3) caught the LLM omitting ETF positions
    # entirely from the `positions` list it sent -- reasoning that since
    # exclude_sectors keeps them out of `breaches` anyway, they weren't worth
    # sending. That shrinks the portfolio total the tool computes from,
    # which inflates every remaining position's weight_pct (one client's KO
    # position came back as "100% of the portfolio" once BND was dropped).
    # exclude_sectors must only affect which positions can appear in
    # `breaches`, never which positions are supplied as input.
    from app.agent.tools.finance_calc import ConcentrationScreenInput
    description = ConcentrationScreenInput.model_fields["portfolios"].description
    assert "every position" in description.lower()
    assert "etf" in description.lower()


# --- concentration_screen: exclude_sectors (ETF false-positive fix) -----
# Regression: an ETF (e.g. BND, SPY) legitimately dominates a conservative
# client's portfolio by design (it's a diversified bond/index fund, not a
# concentrated single-stock bet). Flagging it as a "concentration breach"
# alongside a real single-stock overweight is a false positive that dilutes
# the signal for the advisor. exclude_sectors lets the caller keep those
# positions in totals/weights (so weight_pct for every position is still
# computed over the whole portfolio) while never listing them in `breaches`.

def _etf_heavy_portfolio():
    return LabeledPortfolio(label="ETF Heavy", positions=[
        Position(ticker="BND", shares=100, avg_cost=70, price=74, sector="ETF"),
        Position(ticker="JNJ", shares=10, avg_cost=150, price=190, sector="Health Care"),
    ])


def test_concentration_screen_default_excludes_etf_from_breaches():
    result = compute_concentration_screen([_etf_heavy_portfolio()], threshold_pct=30.0)
    # BND is 79.57% of the portfolio (well over 30%) but is sector "ETF", so
    # it must not appear in breaches under the default exclude_sectors=["ETF"].
    tickers_in_breaches = {b["ticker"] for b in result["breaches"]}
    assert "BND" not in tickers_in_breaches
    assert result["breach_count"] == 0


def test_concentration_screen_exclude_sectors_empty_list_flags_etf_too():
    result = compute_concentration_screen([_etf_heavy_portfolio()], threshold_pct=30.0, exclude_sectors=[])
    tickers_in_breaches = {b["ticker"] for b in result["breaches"]}
    assert "BND" in tickers_in_breaches


def test_concentration_screen_excluded_sector_still_counted_in_weights():
    # Excluding a sector from breaches must not remove it from the portfolio
    # total/weights: JNJ's weight_pct is unaffected by exclude_sectors and is
    # computed over the full portfolio market value, including BND.
    excluded = compute_concentration_screen([_etf_heavy_portfolio()], threshold_pct=1.0, exclude_sectors=["ETF"])
    included = compute_concentration_screen([_etf_heavy_portfolio()], threshold_pct=1.0, exclude_sectors=[])
    jnj_weight_excluded = next(b["weight_pct"] for b in excluded["breaches"] if b["ticker"] == "JNJ")
    jnj_weight_included = next(b["weight_pct"] for b in included["breaches"] if b["ticker"] == "JNJ")
    assert jnj_weight_excluded == jnj_weight_included == pytest.approx(20.43, abs=0.01)


def test_concentration_screen_tool_accepts_exclude_sectors():
    out = concentration_screen_tool.invoke({
        "portfolios": [{"label": "ETF Heavy", "positions": [
            {"ticker": "BND", "shares": 100, "avg_cost": 70, "price": 74, "sector": "ETF"},
            {"ticker": "JNJ", "shares": 10, "avg_cost": 150, "price": 190, "sector": "Health Care"},
        ]}],
        "threshold_pct": 30,
        "exclude_sectors": [],
    })
    assert out["breach_count"] == 1
    assert out["breaches"][0]["ticker"] == "BND"


# --- concentration_screen: duplicate labels rejected --------------------

def test_concentration_screen_rejects_duplicate_labels():
    with pytest.raises(ValueError, match="duplicate"):
        compute_concentration_screen(
            [_susan_grant(), LabeledPortfolio(label="Susan Grant", positions=[
                Position(ticker="X", shares=1, avg_cost=1, price=1, sector="A"),
            ])],
            threshold_pct=30.0,
        )
