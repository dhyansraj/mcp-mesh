package com.example.slowtool;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Random;

/**
 * Slow financial data tools for parallel execution testing.
 *
 * <p>Each tool sleeps 3 seconds to simulate latency, making it easy to verify
 * that parallel tool execution is working correctly (3 tools in ~3s vs ~9s sequential).
 *
 * <h2>Tools Provided</h2>
 * <ul>
 *   <li>get_stock_price - Get current stock price for a ticker symbol</li>
 *   <li>get_company_info - Get company information for a ticker symbol</li>
 *   <li>get_market_sentiment - Get market sentiment analysis for a ticker symbol</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this agent
 * meshctl start examples/parallel-tools/slow-tool-java -d
 *
 * # Test tools
 * meshctl list -t
 * meshctl call get_stock_price '{"ticker": "AAPL"}'
 * </pre>
 */
@SpringBootApplication
@MeshAgent(
    name = "slow-tool-java",
    version = "1.0.0",
    description = "Slow financial data tools for parallel execution testing",
    port = 9000
)
public class SlowToolApplication {

    private static final Logger log = LoggerFactory.getLogger(SlowToolApplication.class);
    private static final Random random = new Random();

    public static void main(String[] args) {
        log.info("Starting Slow Tool (financial data with simulated latency)...");
        SpringApplication.run(SlowToolApplication.class, args);
    }

    /**
     * Get current stock price for a ticker symbol.
     *
     * @param ticker Stock ticker symbol (e.g., "AAPL", "GOOGL")
     * @return Stock price information including price, change, and currency
     */
    @MeshTool(
        capability = "get_stock_price",
        description = "Get current stock price for a ticker symbol",
        tags = {"financial", "slow-tool", "parallel-test"}
    )
    public Map<String, Object> getStockPrice(
        @Param(value = "ticker", description = "Stock ticker symbol") String ticker
    ) {
        log.info("[get_stock_price] Getting stock price for: {}", ticker);
        sleep(3000);

        double price = 50 + random.nextDouble() * 450;
        double change = -5 + random.nextDouble() * 10;

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("ticker", ticker);
        result.put("price", Math.round(price * 100.0) / 100.0);
        result.put("change", Math.round(change * 100.0) / 100.0);
        result.put("change_pct", String.format("%.2f%%", change / price * 100));
        result.put("currency", "USD");
        return result;
    }

    /**
     * Get company information for a ticker symbol.
     *
     * @param ticker Stock ticker symbol (e.g., "AAPL", "GOOGL")
     * @return Company information including name, sector, market cap, and employees
     */
    @MeshTool(
        capability = "get_company_info",
        description = "Get company information for a ticker symbol",
        tags = {"financial", "slow-tool", "parallel-test"}
    )
    public Map<String, Object> getCompanyInfo(
        @Param(value = "ticker", description = "Stock ticker symbol") String ticker
    ) {
        log.info("[get_company_info] Getting company info for: {}", ticker);
        sleep(3000);

        String[] sectors = {"Technology", "Healthcare", "Finance", "Energy", "Consumer"};

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("ticker", ticker);
        result.put("name", ticker + " Corporation");
        result.put("sector", sectors[random.nextInt(sectors.length)]);
        result.put("market_cap", "$" + (10 + random.nextInt(490)) + "B");
        result.put("employees", 1000 + random.nextInt(99000));
        return result;
    }

    /**
     * Get market sentiment analysis for a ticker symbol.
     *
     * @param ticker Stock ticker symbol (e.g., "AAPL", "GOOGL")
     * @return Sentiment analysis including sentiment, score, and recommendation
     */
    @MeshTool(
        capability = "get_market_sentiment",
        description = "Get market sentiment analysis for a ticker symbol",
        tags = {"financial", "slow-tool", "parallel-test"}
    )
    public Map<String, Object> getMarketSentiment(
        @Param(value = "ticker", description = "Stock ticker symbol") String ticker
    ) {
        log.info("[get_market_sentiment] Getting market sentiment for: {}", ticker);
        sleep(3000);

        String[] sentiments = {"Bullish", "Bearish", "Neutral", "Very Bullish", "Very Bearish"};
        String[] recommendations = {"Buy", "Hold", "Sell"};

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("ticker", ticker);
        result.put("sentiment", sentiments[random.nextInt(sentiments.length)]);
        result.put("score", Math.round((-1 + random.nextDouble() * 2) * 100.0) / 100.0);
        result.put("analyst_count", 5 + random.nextInt(25));
        result.put("recommendation", recommendations[random.nextInt(recommendations.length)]);
        return result;
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
