#!/usr/bin/env npx tsx
/**
 * slow-tool-ts - MCP Mesh Agent
 *
 * A MCP Mesh agent that provides slow mock financial data tools.
 * Each tool sleeps 3 seconds to simulate latency, enabling parallel execution testing.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "SlowToolTs Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "slow-tool-ts",
  httpPort: 9000,
});

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomFloat(min: number, max: number, decimals: number = 2): number {
  return parseFloat((Math.random() * (max - min) + min).toFixed(decimals));
}

// ===== TOOLS =====

agent.addTool({
  name: "get_stock_price",
  capability: "get_stock_price",
  description: "Get current stock price for a ticker symbol",
  tags: ["financial", "slow-tool", "parallel-test"],
  parameters: z.object({
    ticker: z.string().describe("The stock ticker symbol (e.g., 'AAPL', 'GOOGL')"),
  }),
  execute: async (args): Promise<Record<string, unknown>> => {
    await sleep(3000);
    const price = randomFloat(50, 500);
    const change = randomFloat(-5, 5);
    return {
      ticker: args.ticker,
      price,
      change,
      change_pct: `${((change / price) * 100).toFixed(2)}%`,
      currency: "USD",
    };
  },
});

agent.addTool({
  name: "get_company_info",
  capability: "get_company_info",
  description: "Get company information for a ticker symbol",
  tags: ["financial", "slow-tool", "parallel-test"],
  parameters: z.object({
    ticker: z.string().describe("The stock ticker symbol (e.g., 'AAPL', 'GOOGL')"),
  }),
  execute: async (args): Promise<Record<string, unknown>> => {
    await sleep(3000);
    const sectors = ["Technology", "Healthcare", "Finance", "Energy", "Consumer"];
    return {
      ticker: args.ticker,
      name: `${args.ticker} Corporation`,
      sector: sectors[randomInt(0, sectors.length - 1)],
      market_cap: `$${randomInt(10, 500)}B`,
      employees: randomInt(1000, 100000),
    };
  },
});

agent.addTool({
  name: "get_market_sentiment",
  capability: "get_market_sentiment",
  description: "Get market sentiment analysis for a ticker symbol",
  tags: ["financial", "slow-tool", "parallel-test"],
  parameters: z.object({
    ticker: z.string().describe("The stock ticker symbol (e.g., 'AAPL', 'GOOGL')"),
  }),
  execute: async (args): Promise<Record<string, unknown>> => {
    await sleep(3000);
    const sentiments = ["Bullish", "Bearish", "Neutral", "Very Bullish", "Very Bearish"];
    const recommendations = ["Buy", "Hold", "Sell"];
    return {
      ticker: args.ticker,
      sentiment: sentiments[randomInt(0, sentiments.length - 1)],
      score: randomFloat(-1, 1),
      analyst_count: randomInt(5, 30),
      recommendation: recommendations[randomInt(0, recommendations.length - 1)],
    };
  },
});

console.log("slow-tool-ts agent defined. Waiting for auto-start...");
