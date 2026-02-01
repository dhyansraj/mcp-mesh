package com.example.calculator;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Java Calculator Agent - demonstrates distributed tracing across agents.
 *
 * This agent provides a 'calculate' tool that:
 * 1. Performs repeated addition (a + a + a... b times) using injected add tool
 * 2. Performs direct multiplication using injected multiply tool
 * 3. Compares both results
 *
 * This creates a trace with multiple spans for testing distributed tracing.
 */
@SpringBootApplication
@MeshAgent(
    name = "java-calculator",
    version = "1.0.0",
    description = "Calculator that compares repeated addition vs multiplication",
    port = 9011
)
public class CalculatorAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(CalculatorAgentApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(CalculatorAgentApplication.class, args);
    }

    /**
     * Calculate using both repeated addition and direct multiplication.
     *
     * Multiply two numbers using two methods:
     * 1. Repeated addition: add 'a' to itself 'b' times using injected add tool
     * 2. Direct multiplication: call injected multiply tool directly
     *
     * @param a First number (will be added repeatedly)
     * @param b Second number (number of times to add, and multiplier)
     * @param add Injected add tool from mesh
     * @param multiply Injected multiply tool from mesh
     * @return Results from both methods for comparison
     */
    @MeshTool(
        capability = "calculate",
        description = "Multiply two numbers using both repeated addition and direct multiplication",
        tags = {"calculator", "math"},
        dependencies = {
            @Selector(capability = "add", tags = {"math"}),
            @Selector(capability = "multiply", tags = {"math"})
        }
    )
    public Map<String, Object> calculate(
            @Param(value = "a", description = "First number (will be added repeatedly)") int a,
            @Param(value = "b", description = "Second number (number of times to add, and multiplier)") int b,
            McpMeshTool add,
            McpMeshTool multiply
    ) {
        log.info("[calculate] Starting calculation: a={}, b={}", a, b);

        Map<String, Object> results = new LinkedHashMap<>();
        results.put("a", a);
        results.put("b", b);
        results.put("repeated_addition", null);
        results.put("direct_multiply", null);
        results.put("match", false);

        // Method 1: Repeated addition (a + a + a... b times)
        if (add != null) {
            try {
                double total = 0;
                for (int i = 0; i < b; i++) {
                    log.debug("[calculate] Calling add: total={} + a={}", total, a);
                    Object addResult = add.call("a", total, "b", (double) a);
                    total = extractNumericResult(addResult);
                }
                results.put("repeated_addition", total);
                log.info("[calculate] Repeated addition result: {}", total);
            } catch (Exception e) {
                log.error("[calculate] Error in repeated addition: {}", e.getMessage());
                results.put("repeated_addition", "error: " + e.getMessage());
            }
        } else {
            results.put("repeated_addition", "add tool not available");
        }

        // Method 2: Direct multiplication
        if (multiply != null) {
            try {
                log.debug("[calculate] Calling multiply: {} * {}", a, b);
                Object multiplyResult = multiply.call("a", (double) a, "b", (double) b);
                double multiplyValue = extractNumericResult(multiplyResult);
                results.put("direct_multiply", multiplyValue);
                log.info("[calculate] Direct multiply result: {}", multiplyValue);
            } catch (Exception e) {
                log.error("[calculate] Error in multiplication: {}", e.getMessage());
                results.put("direct_multiply", "error: " + e.getMessage());
            }
        } else {
            results.put("direct_multiply", "multiply tool not available");
        }

        // Compare results
        Object repeatedAddition = results.get("repeated_addition");
        Object directMultiply = results.get("direct_multiply");

        if (repeatedAddition instanceof Number && directMultiply instanceof Number) {
            double addVal = ((Number) repeatedAddition).doubleValue();
            double mulVal = ((Number) directMultiply).doubleValue();
            results.put("match", Math.abs(addVal - mulVal) < 0.001);
        }

        log.info("[calculate] Calculation complete: {}", results);
        return results;
    }

    /**
     * Extract numeric result from tool call response.
     */
    @SuppressWarnings("unchecked")
    private double extractNumericResult(Object result) {
        if (result instanceof Number) {
            return ((Number) result).doubleValue();
        }
        if (result instanceof Map) {
            Map<String, Object> map = (Map<String, Object>) result;
            if (map.containsKey("result")) {
                Object value = map.get("result");
                if (value instanceof Number) {
                    return ((Number) value).doubleValue();
                }
                return Double.parseDouble(value.toString());
            }
        }
        if (result instanceof String) {
            return Double.parseDouble((String) result);
        }
        throw new IllegalArgumentException("Cannot extract numeric result from: " + result);
    }
}
