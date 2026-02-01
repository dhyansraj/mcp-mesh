package io.mcpmesh.spring;

import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshCore;
import io.mcpmesh.core.MeshEvent;
import io.mcpmesh.core.MeshHandle;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Core mesh runtime that manages the agent lifecycle via Rust FFI.
 *
 * <p>This class wraps the native Rust core and provides a Java-friendly
 * interface for starting agents, receiving events, and shutting down.
 *
 * <p>Implements {@link SmartLifecycle} for proper Spring container integration.
 */
public class MeshRuntime implements SmartLifecycle {

    private static final Logger log = LoggerFactory.getLogger(MeshRuntime.class);
    private static final int LIFECYCLE_PHASE = Integer.MAX_VALUE - 100; // Start late, stop early

    private final AgentSpec agentSpec;
    private final ObjectMapper objectMapper;
    private final AtomicBoolean running = new AtomicBoolean(false);

    private MeshHandle handle;

    public MeshRuntime(AgentSpec agentSpec) {
        this.agentSpec = agentSpec;
        this.objectMapper = new ObjectMapper();
    }

    @Override
    public void start() {
        if (running.compareAndSet(false, true)) {
            log.info("Starting MCP Mesh runtime for agent '{}'", agentSpec.getName());
            try {
                handle = MeshHandle.start(agentSpec);
                log.info("MCP Mesh runtime started successfully");
            } catch (Exception e) {
                running.set(false);
                throw new RuntimeException("Failed to start mesh runtime", e);
            }
        }
    }

    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("Stopping MCP Mesh runtime");
            if (handle != null) {
                try {
                    handle.close();
                } catch (Exception e) {
                    log.warn("Error closing mesh handle", e);
                }
                handle = null;
            }
            log.info("MCP Mesh runtime stopped");
        }
    }

    @Override
    public boolean isRunning() {
        return running.get() && handle != null && handle.isRunning();
    }

    @Override
    public int getPhase() {
        return LIFECYCLE_PHASE;
    }

    /**
     * Get the next event from the runtime.
     *
     * <p>Blocks until an event is available or timeout expires.
     *
     * @param timeoutMs Timeout in milliseconds (-1 for infinite, 0 for non-blocking)
     * @return The next event, or null on timeout
     */
    public MeshEvent nextEvent(long timeoutMs) {
        if (handle == null || !isRunning()) {
            return null;
        }
        return handle.nextEvent(timeoutMs).orElse(null);
    }

    /**
     * Report agent health status to the registry.
     *
     * @param status Health status: "healthy", "degraded", or "unhealthy"
     */
    public void reportHealth(String status) {
        if (handle != null && isRunning()) {
            handle.reportHealth(status);
        }
    }

    /**
     * Request graceful shutdown.
     */
    public void shutdown() {
        if (handle != null) {
            handle.shutdown();
        }
    }

    /**
     * Get the agent specification.
     *
     * @return The agent spec
     */
    public AgentSpec getAgentSpec() {
        return agentSpec;
    }

    /**
     * Update tool specifications at runtime.
     *
     * @param tools Updated tool specs
     */
    public void updateTools(List<AgentSpec.ToolSpec> tools) {
        // This would require adding a mesh_update_tools FFI function
        // For now, tools are set at startup
        log.debug("Tool updates at runtime not yet supported");
    }
}
