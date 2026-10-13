import json

import pytest

from app.agent import display
from app.agent.tools.ticker_news import fetch_ticker_news, ticker_news_tool


def _item(n, title=None):
    return {
        "uuid": f"u{n}",
        "title": title or f"Apple headline {n}",
        "publisher": "Reuters",
        "link": f"https://finance.yahoo.com/{n}",
        "providerPublishTime": 1791909732,
    }


def _search(results, company="Apple Inc."):
    return lambda symbol, count: (results, company)


def test_only_stories_naming_the_ticker_or_company_are_kept_up_to_limit():
    results = [
        _item(1, "Domino's Pizza Q3 Earnings Call Summary"),
        _item(2, "Apple Unveils Smart Home Lineup"),
        _item(3, "Why AAPL stock rose today"),
        _item(4, "Pineapple prices spike"),
        _item(5, "Apple again"),
    ]

    news = fetch_ticker_news("aapl", limit=2, search=_search(results))

    assert [n["content"]["title"] for n in news] == [
        "Apple Unveils Smart Home Lineup",
        "Why AAPL stock rose today",
    ]


def test_no_story_about_the_company_returns_empty_list():
    news = fetch_ticker_news("NVDA", search=_search([_item(1, "Fed holds rates")], "NVIDIA Corporation"))

    assert news == []


def test_items_without_title_or_link_are_dropped():
    results = [{"uuid": "x", "title": "", "link": "https://a"}, _item(1)]

    news = fetch_ticker_news("AAPL", search=_search(results))

    assert len(news) == 1


def test_output_renders_through_the_existing_news_card_normalizer():
    news = fetch_ticker_news("AAPL", search=_search([_item(1)]))

    cards = display.DISPLAY_NORMALIZERS["yfinance_get_ticker_news"](json.dumps(news), {"symbol": "AAPL"})

    assert cards == [{"type": "ticker_news", "items": [{
        "title": "Apple headline 1", "summary": "", "source": "Reuters",
        "url": "https://finance.yahoo.com/1", "published_at": "2026-10-13T16:42:12Z",
    }]}]


def test_tool_keeps_the_yfmcp_name_and_args():
    assert ticker_news_tool.name == "yfinance_get_ticker_news"
    assert set(ticker_news_tool.args) == {"symbol", "limit"}
