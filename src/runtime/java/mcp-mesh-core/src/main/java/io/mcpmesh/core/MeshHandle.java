package io.mcpmesh.core;

import tools.jackson.databind.ObjectMapper;
import jnr.ffi.Pointer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.Closeable;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Handle to a running MCP Mesh agent.
 *
 * <p>This class wraps the native agent handle and provides a Java-friendly API
 * for interacting with the Rust core runtime.
 *
 * <p>Implements {@link Closeable} for use with try-with-resources.
 *
 * <h2>Usage Example</h2>
 * <pre>{@code
 * AgentSpec spec = new AgentSpec("my-agent", "http://localhost:8000");
 * try (MeshHandle handle = MeshHandle.start(spec)) {
 *     while (handle.isRunning()) {
 *         Optional<MeshEvent> event = handle.nextEvent(5000);
 *         event.ifPresent(this::handleEvent);
 *     }
 * }
 * }</pre>
 */
public class MeshHandle implements Closeable {

    private static final Logger log = LoggerFactory.getLogger(MeshHandle.class);
    private static final ObjectMapper objectMapper = MeshObjectMappers.create();

    private final MeshCore core;
    private final Pointer handle;
    private final AtomicBoolean closed = new AtomicBoolean(false);

    private MeshHandle(MeshCore core, Pointer handle) {
        this.core = core;
        this.handle = handle;
    }

    /**
     * Start an agent from the given specification.
     *
     * @param spec The agent specification
     * @return A handle to the running agent
     * @throws MeshException if the agent fails to start
     */
    public static MeshHandle start(AgentSpec spec) {
        MeshCore core = MeshCore.load();

        try {
            String specJson = objectMapper.writeValueAsString(spec);
            log.debug("Starting agent with spec: {}", specJson);

            Pointer handle = core.mesh_start_agent(specJson);
            if (handle == null) {
                String error = getLastError(core);
                throw new MeshException("Failed to start agent: " + error);
            }

            log.info("Agent '{}' started successfully", spec.getName());
            return new MeshHandle(core, handle);
        } catch (Exception e) {
            throw new MeshException("Failed to serialize AgentSpec", e);
        }
    }

    /**
     * Check if the agent is still running.
     *
     * @return true if running, false if shutdown
     */
    public boolean isRunning() {
        if (closed.get()) {
            return false;
        }
        return core.mesh_is_running(handle) == 1;
    }

    /**
     * Get the next event from the agent runtime.
     *
     * <p>Blocks until an event is available or the timeout expires.
     *
     * @param timeoutMs Timeout in milliseconds (-1 for infinite, 0 for non-blocking)
     * @return The event, or empty if timeout/shutdown
     */
    public Optional<MeshEvent> nextEvent(long timeoutMs) {
        if (closed.get()) {
            return Optional.empty();
        }

        Pointer eventPtr = core.mesh_next_event(handle, timeoutMs);
        if (eventPtr == null) {
            return Optional.empty();
        }

        try {
            String eventJson = eventPtr.getString(0);
            log.debug("Received event: {}", eventJson);
            MeshEvent event = objectMapper.readValue(eventJson, MeshEvent.class);
            return Optional.of(event);
        } catch (Exception e) {
            log.error("Failed to parse event JSON", e);
            return Optional.empty();
        } finally {
            core.mesh_free_string(eventPtr);
        }
    }

    /**
     * Report the agent's health status.
     *
     * @param status The health status ("healthy", "degraded", or "unhealthy")
     * @throws MeshException if the status report fails
     */
    public void reportHealth(String status) {
        if (closed.get()) {
            throw new MeshException("Handle is closed");
        }

        int result = core.mesh_report_health(handle, status);
        if (result != 0) {
            String error = getLastError(core);
            throw new MeshException("Failed to report health: " + error);
        }
    }

    /**
     * Report the agent as healthy.
     */
    public void reportHealthy() {
        reportHealth("healthy");
    }

    /**
     * Report the agent as degraded.
     */
    public void reportDegraded() {
        reportHealth("degraded");
    }

    /**
     * Report the agent as unhealthy.
     */
    public void reportUnhealthy() {
        reportHealth("unhealthy");
    }

    /**
     * Update the HTTP port after auto-detection.
     *
     * <p>Call this after the HTTP server starts with port=0 to update
     * the registry with the actual assigned port. This triggers a full
     * heartbeat to re-register with the correct endpoint.
     *
     * @param port The actual port the HTTP server is listening on
     * @return true if the update was sent successfully
     */
    public boolean updatePort(int port) {
        if (closed.get()) {
            throw new MeshException("Handle is closed");
        }

        int result = core.mesh_update_port(handle, port);
        if (result != 0) {
            String error = getLastError(core);
            log.warn("Failed to update port to {}: {}", port, error);
            return false;
        }
        log.info("Port updated to {}", port);
        return true;
    }

    /**
     * Request graceful shutdown of the agent.
     *
     * <p>This is non-blocking. Use {@link #nextEvent(long)} to wait for the
     * shutdown event.
     */
    public void shutdown() {
        if (!closed.get()) {
            log.info("Requesting agent shutdown");
            core.mesh_shutdown(handle);
        }
    }

    /**
     * Close the handle and free associated resources.
     *
     * <p>If the agent is still running, this will trigger graceful shutdown
     * and wait briefly for cleanup.
     */
    @Override
    public void close() {
        if (closed.compareAndSet(false, true)) {
            log.info("Closing agent handle");
            core.mesh_free_handle(handle);
        }
    }

    private static String getLastError(MeshCore core) {
        Pointer errorPtr = core.mesh_last_error();
        if (errorPtr == null) {
            return "Unknown error";
        }
        try {
            return errorPtr.getString(0);
        } finally {
            core.mesh_free_string(errorPtr);
        }
    }
}
