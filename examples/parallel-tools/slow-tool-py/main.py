#!/usr/bin/env python3
"""
slow-tool-py - MCP Mesh Agent

A MCP Mesh agent that provides slow mock financial data tools.
Each tool sleeps 3 seconds to simulate latency, enabling parallel execution testing.
"""

import asyncio
import random
from typing import Any

import mesh
from fastmcp import FastMCP

app = FastMCP("SlowToolPy Service")


@app.tool()
@mesh.tool(
    capability="get_stock_price",
    description="Get current stock price for a ticker symbol",
    tags=["financial", "slow-tool", "parallel-test"],
)
async def get_stock_price(ticker: str) -> dict[str, Any]:
    """Get current stock price for a ticker symbol."""
    await asyncio.sleep(3)
    price = round(random.uniform(50, 500), 2)
    change = round(random.uniform(-5, 5), 2)
    return {
        "ticker": ticker,
        "price": price,
        "change": change,
        "change_pct": f"{change / price * 100:.2f}%",
        "currency": "USD",
    }


@app.tool()
@mesh.tool(
    capability="get_company_info",
    description="Get company information for a ticker symbol",
    tags=["financial", "slow-tool", "parallel-test"],
)
async def get_company_info(ticker: str) -> dict[str, Any]:
    """Get company information for a ticker symbol."""
    await asyncio.sleep(3)
    sectors = ["Technology", "Healthcare", "Finance", "Energy", "Consumer"]
    return {
        "ticker": ticker,
        "name": f"{ticker} Corporation",
        "sector": random.choice(sectors),
        "market_cap": f"${random.randint(10, 500)}B",
        "employees": random.randint(1000, 100000),
    }


@app.tool()
@mesh.tool(
    capability="get_market_sentiment",
    description="Get market sentiment analysis for a ticker symbol",
    tags=["financial", "slow-tool", "parallel-test"],
)
async def get_market_sentiment(ticker: str) -> dict[str, Any]:
    """Get market sentiment analysis for a ticker symbol."""
    await asyncio.sleep(3)
    sentiments = ["Bullish", "Bearish", "Neutral", "Very Bullish", "Very Bearish"]
    return {
        "ticker": ticker,
        "sentiment": random.choice(sentiments),
        "score": round(random.uniform(-1, 1), 2),
        "analyst_count": random.randint(5, 30),
        "recommendation": random.choice(["Buy", "Hold", "Sell"]),
    }


@mesh.agent(
    name="slow-tool-py",
    version="1.0.0",
    description="Slow financial data tools for parallel execution testing",
    http_port=9000,
    enable_http=True,
    auto_run=True,
)
class SlowToolPyAgent:
    pass
