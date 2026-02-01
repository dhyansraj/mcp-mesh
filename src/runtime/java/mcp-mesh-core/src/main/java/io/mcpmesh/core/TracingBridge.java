package io.mcpmesh.core;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Static bridge to Rust core tracing functions.
 *
 * <p>This class provides static methods for tracing operations, handling
 * the native library loading and initialization automatically.
 *
 * <p>Usage:
 * <pre>
 * if (TracingBridge.isTracingEnabled()) {
 *     TracingBridge.publishSpan(spanJson);
 * }
 * </pre>
 */
public final class TracingBridge {

    private static final Logger log = LoggerFactory.getLogger(TracingBridge.class);

    private static volatile MeshCore core;
    private static volatile boolean initialized = false;
    private static volatile boolean available = false;

    // Private constructor to prevent instantiation
    private TracingBridge() {
    }

    /**
     * Check if tracing is enabled.
     *
     * <p>Checks the MCP_MESH_TRACING environment variable via Rust core.
     *
     * @return true if tracing is enabled
     */
    public static boolean isTracingEnabled() {
        try {
            ensureLoaded();
            return core != null && core.mesh_is_tracing_enabled() == 1;
        } catch (Exception e) {
            log.debug("Failed to check tracing status: {}", e.getMessage());
            return false;
        }
    }

    /**
     * Initialize the trace publisher.
     *
     * <p>Must be called before publishSpan(). Connects to Redis.
     * Safe to call multiple times - only initializes once.
     *
     * @return true if publisher is ready
     */
    public static boolean initPublisher() {
        if (initialized) {
            return available;
        }

        synchronized (TracingBridge.class) {
            if (initialized) {
                return available;
            }

            try {
                ensureLoaded();
                if (core == null) {
                    log.debug("Rust core not available for tracing");
                    initialized = true;
                    available = false;
                    return false;
                }

                int result = core.mesh_init_trace_publisher();
                available = result == 1;
                initialized = true;

                if (available) {
                    log.info("Trace publisher initialized successfully");
                } else {
                    log.warn("Failed to initialize trace publisher");
                }

                return available;

            } catch (Exception e) {
                log.warn("Failed to initialize trace publisher: {}", e.getMessage());
                initialized = true;
                available = false;
                return false;
            }
        }
    }

    /**
     * Check if the trace publisher is available.
     *
     * @return true if publisher is initialized and ready
     */
    public static boolean isPublisherAvailable() {
        if (!initialized) {
            return initPublisher();
        }
        return available;
    }

    /**
     * Publish a trace span to Redis.
     *
     * <p>Non-blocking - returns immediately after queueing.
     * Silently fails if publisher not initialized or unavailable.
     *
     * @param spanJson JSON string containing span data
     * @return true if span was queued successfully
     */
    public static boolean publishSpan(String spanJson) {
        if (!available) {
            if (!initialized) {
                initPublisher();
            }
            if (!available) {
                return false;
            }
        }

        try {
            int result = core.mesh_publish_span(spanJson);
            return result == 1;
        } catch (Exception e) {
            log.debug("Failed to publish span: {}", e.getMessage());
            return false;
        }
    }

    /**
     * Ensure the native library is loaded.
     */
    private static void ensureLoaded() {
        if (core == null) {
            synchronized (TracingBridge.class) {
                if (core == null) {
                    try {
                        core = MeshCore.load();
                    } catch (UnsatisfiedLinkError e) {
                        log.debug("Failed to load Rust core library: {}", e.getMessage());
                    }
                }
            }
        }
    }
}
