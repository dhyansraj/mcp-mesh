package io.mcpmesh.spring;

import io.mcpmesh.core.MeshEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Processes events from the Rust core runtime.
 *
 * <p>Runs an event loop that polls for events and dispatches them
 * to the appropriate handlers (dependency updates, LLM tool updates, etc.).
 *
 * <p>For dependency events, this processor updates both:
 * <ul>
 *   <li>Legacy {@link MeshDependencyInjector} for backward compatibility</li>
 *   <li>{@link MeshToolWrapperRegistry} for MCP SDK wrapper-based injection</li>
 * </ul>
 *
 * @see MeshToolWrapperRegistry
 */
public class MeshEventProcessor implements SmartLifecycle {

    private static final Logger log = LoggerFactory.getLogger(MeshEventProcessor.class);
    private static final int LIFECYCLE_PHASE = Integer.MAX_VALUE - 50; // After MeshRuntime
    private static final long EVENT_POLL_TIMEOUT_MS = 5000;

    private final MeshRuntime runtime;
    private final MeshDependencyInjector injector;
    private final MeshToolWrapperRegistry wrapperRegistry;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final ExecutorService executor;

    public MeshEventProcessor(
            MeshRuntime runtime,
            MeshDependencyInjector injector,
            MeshToolWrapperRegistry wrapperRegistry) {
        this.runtime = runtime;
        this.injector = injector;
        this.wrapperRegistry = wrapperRegistry;
        this.executor = Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "mesh-event-processor");
            t.setDaemon(true);
            return t;
        });
    }

    @Override
    public void start() {
        if (running.compareAndSet(false, true)) {
            log.info("Starting mesh event processor");
            executor.submit(this::eventLoop);
        }
    }

    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("Stopping mesh event processor");
            executor.shutdown();
            try {
                if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                    executor.shutdownNow();
                }
            } catch (InterruptedException e) {
                executor.shutdownNow();
                Thread.currentThread().interrupt();
            }
        }
    }

    @Override
    public boolean isRunning() {
        return running.get();
    }

    @Override
    public int getPhase() {
        return LIFECYCLE_PHASE;
    }

    private void eventLoop() {
        log.debug("Event loop started");

        while (running.get() && runtime.isRunning()) {
            try {
                MeshEvent event = runtime.nextEvent(EVENT_POLL_TIMEOUT_MS);
                if (event != null) {
                    processEvent(event);
                }
            } catch (Exception e) {
                if (running.get()) {
                    log.error("Error processing mesh event", e);
                }
            }
        }

        log.debug("Event loop stopped");
    }

    private void processEvent(MeshEvent event) {
        log.debug("Processing event: {}", event.getEventType());

        switch (event.getEventType()) {
            case AGENT_REGISTERED -> handleAgentRegistered(event);
            case DEPENDENCY_AVAILABLE -> handleDependencyAvailable(event);
            case DEPENDENCY_UNAVAILABLE -> handleDependencyUnavailable(event);
            case DEPENDENCY_CHANGED -> handleDependencyChanged(event);
            case LLM_TOOLS_UPDATED -> handleLlmToolsUpdated(event);
            case LLM_PROVIDER_AVAILABLE -> handleLlmProviderAvailable(event);
            case SHUTDOWN -> handleShutdown(event);
            case REGISTRATION_FAILED -> handleRegistrationFailed(event);
            default -> log.debug("Unhandled event type: {}", event.getEventType());
        }
    }

    private void handleAgentRegistered(MeshEvent event) {
        log.info("Agent registered with mesh: {}", event.getAgentId());
    }

    private void handleDependencyAvailable(MeshEvent event) {
        log.info("Dependency available: {} at {} (requestingFunction={}, depIndex={})",
            event.getCapability(), event.getEndpoint(),
            event.getRequestingFunction(), event.getDepIndex());

        // Update legacy injector
        injector.updateToolDependency(
            event.getCapability(),
            event.getEndpoint(),
            event.getFunctionName()
        );

        // Update wrapper registry with composite key
        if (event.getRequestingFunction() != null && event.getDepIndex() != null) {
            String compositeKey = MeshToolWrapperRegistry.buildDependencyKey(
                event.getRequestingFunction(),
                event.getDepIndex()
            );
            wrapperRegistry.updateDependency(
                compositeKey,
                event.getEndpoint(),
                event.getFunctionName()
            );
        }
    }

    private void handleDependencyUnavailable(MeshEvent event) {
        log.info("Dependency unavailable: {} (requestingFunction={}, depIndex={})",
            event.getCapability(), event.getRequestingFunction(), event.getDepIndex());

        // Update legacy injector
        injector.updateToolDependency(
            event.getCapability(),
            null,
            null
        );

        // Mark wrapper dependency as unavailable
        if (event.getRequestingFunction() != null && event.getDepIndex() != null) {
            String compositeKey = MeshToolWrapperRegistry.buildDependencyKey(
                event.getRequestingFunction(),
                event.getDepIndex()
            );
            wrapperRegistry.markDependencyUnavailable(compositeKey);
        }
    }

    private void handleLlmToolsUpdated(MeshEvent event) {
        log.info("LLM tools updated for function: {}", event.getFunctionId());

        if (event.getTools() != null) {
            injector.updateLlmTools(event.getFunctionId(), event.getTools());
        }
    }

    private void handleDependencyChanged(MeshEvent event) {
        log.debug("Dependency changed: {}", event.getCapability());
        // Re-fetch endpoint info
        if (event.getEndpoint() != null) {
            handleDependencyAvailable(event);
        } else {
            handleDependencyUnavailable(event);
        }
    }

    private void handleLlmProviderAvailable(MeshEvent event) {
        MeshEvent.LlmProviderInfo providerInfo = event.getProviderInfo();
        if (providerInfo != null) {
            log.info("LLM provider available: {} at {}",
                providerInfo.getModel(), providerInfo.getEndpoint());

            // Update the LLM proxy with provider endpoint
            injector.updateLlmProvider(
                providerInfo.getFunctionId(),
                providerInfo.getEndpoint(),
                providerInfo.getFunctionName(),
                providerInfo.getModel()
            );
        } else {
            log.debug("LLM provider event without provider info");
        }
    }

    private void handleShutdown(MeshEvent event) {
        log.info("Shutdown event received: {}", event.getReason());
        running.set(false);
    }

    private void handleRegistrationFailed(MeshEvent event) {
        log.error("Registration failed: {}", event.getError());
    }
}
