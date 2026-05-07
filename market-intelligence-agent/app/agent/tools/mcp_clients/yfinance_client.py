import asyncio
import logging
import os
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_core.tools import Tool
from app.core.config import settings

logger = logging.getLogger(__name__)

server_params = StdioServerParameters(
    command="uv",
    args=["run", "yfmcp"],
    env=os.environ,
)


async def _call_yfmcp(tool_name: str, arguments: dict) -> str:
    """Invoke a single tool on the yfmcp stdio server and return its text result."""
    logger.info("YFMCP: %s args=%s", tool_name, arguments)
    async with AsyncExitStack() as stack:
        read_stream, write_stream = await stack.enter_async_context(
            stdio_client(server_params)
        )
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        result = await session.call_tool(tool_name, arguments=arguments)
        if result.content and len(result.content) > 0:
            return result.content[0].text
        return f"No data returned by {tool_name}."


def _sync_call(tool_name: str, arguments: dict) -> str:
    """Sync shim with timeout + error envelope. Returns a string the LLM can read."""
    timeout = settings.YFINANCE_TIMEOUT_S
    try:
        return asyncio.run(asyncio.wait_for(_call_yfmcp(tool_name, arguments), timeout))
    except asyncio.TimeoutError:
        logger.error("YFMCP: timeout after %ss for %s", timeout, tool_name)
        return "Error: Yahoo Finance request timed out"
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                asyncio.wait_for(_call_yfmcp(tool_name, arguments), timeout)
            )
        except asyncio.TimeoutError:
            return "Error: Yahoo Finance request timed out"
        except Exception as e:
            logger.error("YFMCP: error — %s", e)
            return f"Error: Yahoo Finance service unavailable: {e}"
        finally:
            loop.close()
    except Exception as e:
        logger.error("YFMCP: error — %s", e)
        return f"Error: Yahoo Finance service unavailable: {e}"


def _quote(ticker: str) -> str:
    return _sync_call("get_quote", {"ticker": ticker})


def _history(ticker: str, period: str = "1mo") -> str:
    return _sync_call("get_history", {"ticker": ticker, "period": period})


def _news(ticker: str, limit: int = 5) -> str:
    return _sync_call("get_news", {"ticker": ticker, "limit": limit})


yf_quote_tool = Tool(
    name="yf_quote",
    func=_quote,
    description=(
        "Get the current price and day statistics for a stock ticker from "
        "Yahoo Finance. Args: ticker (str, e.g. 'AAPL')."
    ),
)

yf_history_tool = Tool(
    name="yf_history",
    func=_history,
    description=(
        "Get historical prices for a stock ticker from Yahoo Finance. "
        "Args: ticker (str), period (str, optional, default '1mo'; e.g. '1mo', '3mo', '1y', '5y')."
    ),
)

yf_news_tool = Tool(
    name="yf_news",
    func=_news,
    description=(
        "Get recent news headlines for a stock ticker from Yahoo Finance. "
        "Args: ticker (str), limit (int, optional, default 5)."
    ),
)
