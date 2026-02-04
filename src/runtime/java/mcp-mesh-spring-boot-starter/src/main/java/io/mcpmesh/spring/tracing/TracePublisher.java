package io.mcpmesh.spring.tracing;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.core.TracingBridge;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Publishes trace spans to Redis via Rust FFI.
 *
 * <p>TracePublisher handles:
 * <ul>
 *   <li>Async publishing (never blocks agent execution)</li>
 *   <li>Converting complex types to Redis-compatible strings</li>
 *   <li>Silent error handling (tracing failures never break agents)</li>
 * </ul>
 *
 * <p>Spans are published to the Redis stream "mesh:trace" where the registry
 * consumes them and forwards to Tempo.
 */
public class TracePublisher {

    private static final Logger log = LoggerFactory.getLogger(TracePublisher.class);

    private final ObjectMapper objectMapper;
    private final ExecutorService executor;
    private volatile boolean shutdown = false;

    /**
     * Create a TracePublisher with the given ObjectMapper.
     *
     * @param objectMapper ObjectMapper for JSON serialization
     */
    public TracePublisher(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.executor = Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "trace-publisher");
            t.setDaemon(true);  // Don't prevent JVM shutdown
            return t;
        });
        log.debug("TracePublisher initialized with single-thread executor");
    }

    /**
     * Publish a trace span asynchronously.
     *
     * <p>This method returns immediately. The actual publishing happens
     * in a background thread to never block agent execution.
     *
     * @param traceData Map of trace data to publish
     */
    public void publish(Map<String, Object> traceData) {
        if (shutdown) {
            log.trace("TracePublisher is shut down, ignoring span");
            return;
        }

        executor.submit(() -> {
            try {
                // Convert to Redis-compatible format (all string values)
                Map<String, String> redisData = convertForRedis(traceData);
                String json = objectMapper.writeValueAsString(redisData);

                // Publish via Rust FFI
                boolean success = TracingBridge.publishSpan(json);

                if (success) {
                    log.trace("Published span: {}", traceData.get("span_id"));
                } else {
                    log.debug("Failed to publish span via Rust FFI");
                }

            } catch (JacksonException e) {
                // Never block agent execution due to serialization errors
                log.debug("Failed to serialize span: {}", e.getMessage());
            } catch (Exception e) {
                // Never block agent execution due to any error
                log.debug("Failed to publish span: {}", e.getMessage());
            }
        });
    }

    /**
     * Convert trace data to Redis-compatible format.
     *
     * <p>Redis XADD requires string values, so we convert:
     * <ul>
     *   <li>null → "null"</li>
     *   <li>String → as-is</li>
     *   <li>Collection/Map → JSON string</li>
     *   <li>Other → toString()</li>
     * </ul>
     *
     * @param data Map of trace data
     * @return Map with all string values
     */
    private Map<String, String> convertForRedis(Map<String, Object> data) {
        Map<String, String> result = new LinkedHashMap<>();

        for (Map.Entry<String, Object> entry : data.entrySet()) {
            Object value = entry.getValue();
            String stringValue;

            if (value == null) {
                stringValue = "null";
            } else if (value instanceof String) {
                stringValue = (String) value;
            } else if (value instanceof Collection || value instanceof Map) {
                try {
                    stringValue = objectMapper.writeValueAsString(value);
                } catch (JacksonException e) {
                    stringValue = value.toString();
                }
            } else if (value instanceof Number || value instanceof Boolean) {
                stringValue = value.toString();
            } else {
                stringValue = value.toString();
            }

            result.put(entry.getKey(), stringValue);
        }

        return result;
    }

    /**
     * Shutdown the publisher gracefully.
     *
     * <p>Waits up to 5 seconds for pending spans to be published.
     */
    public void shutdown() {
        shutdown = true;
        executor.shutdown();
        try {
            if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                executor.shutdownNow();
                log.debug("TracePublisher forced shutdown after timeout");
            } else {
                log.debug("TracePublisher shutdown gracefully");
            }
        } catch (InterruptedException e) {
            executor.shutdownNow();
            Thread.currentThread().interrupt();
        }
    }
}
