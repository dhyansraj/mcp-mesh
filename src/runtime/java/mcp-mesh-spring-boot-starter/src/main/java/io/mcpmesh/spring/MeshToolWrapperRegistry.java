package io.mcpmesh.spring;

import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.lang.reflect.Type;
import java.util.Collection;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry for MeshToolWrapper and other McpToolHandler instances.
 *
 * <p>Stores wrappers by function ID and handles dependency updates using
 * composite keys (funcId:dep_N format).
 *
 * <p>This registry is the bridge between:
 * <ul>
 *   <li>MCP SDK registration (getAllHandlers)</li>
 *   <li>Heartbeat dependency updates (updateDependency)</li>
 *   <li>Tool invocation (getHandler)</li>
 * </ul>
 *
 * <p>Supports both @MeshTool methods (via MeshToolWrapper) and @MeshLlmProvider
 * classes (via LlmProviderToolWrapper from spring-ai module).
 *
 * @see MeshToolWrapper
 * @see McpToolHandler
 */
public class MeshToolWrapperRegistry {

    private static final Logger log = LoggerFactory.getLogger(MeshToolWrapperRegistry.class);

    private static final String DEP_SEPARATOR = ":dep_";
    private static final String LLM_SEPARATOR = ":llm_";

    // funcId → wrapper (MeshToolWrapper only, for dependency updates)
    private final Map<String, MeshToolWrapper> wrappers = new ConcurrentHashMap<>();

    /**
     * Handler {@link Method} → wrapper: the exact identity, qualified by
     * declaring class AND parameter types (issue #1437). Used by callers that
     * hold the method — they should never have to degrade to a name.
     *
     * <p>{@link Method#equals} is value-based, so a fresh copy from a later
     * reflective lookup hits the entry registration wrote.
     */
    private final Map<Method, MeshToolWrapper> wrappersByMethod = new ConcurrentHashMap<>();

    /**
     * Bare {@code methodName} → wrapper. The weakest key in the package: no
     * class qualifier at all, so two {@code @MeshTool} methods named
     * {@code analyze} in different classes collide (issue #1437). It has to stay
     * addressable by bare name — this is the wire-facing fallback for a core that
     * names a slot by function name alone ({@link #resolveWrapper}) — so instead
     * of a qualifier it gets a collision guard: a name claimed by more than one
     * wrapper is recorded in {@link #ambiguousMethodNames} and refused at lookup,
     * rather than resolving to whichever registered last and wiring one tool's
     * dependency resolution into the other's slot.
     */
    private final Map<String, MeshToolWrapper> wrappersByMethodName = new ConcurrentHashMap<>();

    /** Bare method names claimed by more than one registered wrapper. */
    private final Set<String> ambiguousMethodNames = ConcurrentHashMap.newKeySet();

    // funcId → handler (all handlers including LLM providers)
    private final Map<String, McpToolHandler> handlers = new ConcurrentHashMap<>();

    // capability → handler (for MCP SDK tool lookup by name)
    private final Map<String, McpToolHandler> handlersByCapability = new ConcurrentHashMap<>();

    private final McpMeshToolProxyFactory proxyFactory;

    // compositeKey (funcId:dep_N) → last-applied resolution signature.
    // Idempotency guard (#1314): the Rust core re-emits dependency_available
    // for every believed-delivered edge on an independent ~10s tick to
    // self-heal dropped applies. Those re-emits carry an identical resolution;
    // skipping them here avoids re-resolving the return type, re-fetching the
    // proxy, and rewriting the wrapper's injected slot (which re-counts the
    // settle latch) every 10s for a no-op.
    private final Map<String, DepSignature> lastAppliedByKey = new ConcurrentHashMap<>();

    /**
     * Per-slot last-applied resolution identity.
     *
     * <p>Includes {@code agentId} so the guard composes with #1315: an
     * agent_id-only change is a genuine update (different signature → applies),
     * while an unchanged reconcile re-emit carries the same agentId → skip.
     * {@code kwargs} is not part of the signature because it is not threaded to
     * this layer on {@link MeshEvent} today; if it becomes available it should
     * be added here. Record → value-based equals over all components.
     */
    private record DepSignature(String endpoint, String functionName, String agentId) {}

    public MeshToolWrapperRegistry(McpMeshToolProxyFactory proxyFactory) {
        this.proxyFactory = proxyFactory;
    }

    /**
     * Register a MeshToolWrapper (for @MeshTool methods).
     *
     * @param wrapper The wrapper to register
     */
    public void registerWrapper(MeshToolWrapper wrapper) {
        String funcId = wrapper.getFuncId();
        String capability = wrapper.getCapability();
        String methodName = wrapper.getMethodName();

        // Two DIFFERENT declarations must never share a funcId (issue #1448).
        // Checked HERE, immediately before the put that would evict the first
        // one — this is the only point that sees both declarations.
        assertNotAnOverload(funcId, wrapper);

        // Store in wrapper maps (for dependency updates)
        wrappers.put(funcId, wrapper);
        if (wrapper.getMethod() != null) {
            wrappersByMethod.put(wrapper.getMethod(), wrapper);
        }
        indexBareMethodName(methodName, wrapper);

        // Store in handler maps (for MCP server)
        handlers.put(funcId, wrapper);
        handlersByCapability.put(capability, wrapper);

        // Settling-window grace (#1193): declare this tool's dependency
        // slots with the process-wide settle state so the agent-level
        // "all declared deps resolved" latch can flip eagerly. Keys are
        // per-consumer-slot composites (funcId:dep_N) — capability-level
        // keying would let one consumer's resolution wake another
        // consumer's waiter before that consumer's slot is written.
        // MeshJob-backed dependencies are excluded (submitter is wired
        // locally; no resolution event ever lands for the slot).
        MeshSettleState settleState = MeshSettleState.getInstance();
        for (int depIndex : wrapper.getSettleDepIndices()) {
            settleState.registerDeclared(buildDependencyKey(funcId, depIndex));
        }

        log.info("Registered wrapper: {} (capability: {}, deps: {}, llm: {})",
            funcId, capability, wrapper.getDependencyCount(), wrapper.getLlmAgentCount());
    }

    /**
     * Register a generic McpToolHandler (for LLM providers, etc.).
     *
     * <p>Use this for handlers that don't need dependency injection.
     *
     * @param handler The handler to register
     */
    public void registerHandler(McpToolHandler handler) {
        String funcId = handler.getFuncId();
        String capability = handler.getCapability();
        String methodName = handler.getMethodName();

        handlers.put(funcId, handler);
        handlersByCapability.put(capability, handler);

        log.info("Registered handler: {} (capability: {}, method: {})",
            funcId, capability, methodName);
    }

    /**
     * Refuse to boot when two overloaded {@code @MeshTool} methods in ONE class
     * would share a funcId (issue #1448).
     *
     * <p>A funcId is {@code FQCN.methodName} with no parameter types
     * ({@code MeshToolBeanPostProcessor}), so {@code analyze(String)} and
     * {@code analyze(int)} on one class compute the same one and the second
     * registration silently EVICTS the first from every funcId-keyed map here.
     * Nothing downstream notices: the duplicate-capability guard in
     * {@link MeshToolRegistry#registerTool} is keyed by capability, so distinct
     * capabilities walk through it, and the heartbeat still advertises BOTH
     * tools — the evicted one with no MCP tool behind it. Worse, both advertise
     * the same {@code function_name}, so the registry merges their dependency
     * lists under that one key and an in-range {@code dep_index} can wire one
     * overload's dependency into the other's slot.
     *
     * <p>Widening the funcId to include parameter types would not fix it: the
     * bare method name is the wire name, and it keys three single-valued
     * namespaces — the MCP SDK tool table, the registry's
     * {@code dependencies_resolved} map, and {@link #wrappersByMethodName}.
     * {@code @MeshTool} has no name attribute, so two overloads cannot be given
     * distinct wire names and the declaration itself has to be rejected.
     *
     * <p>The discriminator is the handler {@link Method}, NOT wrapper identity,
     * mirroring the tolerance {@link #indexBareMethodName} expresses on funcId:
     * {@link Method#equals} is value-based and includes parameter types, so a
     * prototype-scoped bean instantiated twice, a context refresh, or a repeated
     * post-processing pass produces a fresh wrapper for an EQUAL Method and
     * replaces cleanly, exactly as before (issue #1445). Only a genuinely
     * different Method — a real overload — throws.
     *
     * <p>A {@code null} Method carries no identity to compare, so it falls back
     * to the replacing behaviour rather than guessing.
     */
    private void assertNotAnOverload(String funcId, MeshToolWrapper incoming) {
        MeshToolWrapper previous = wrappers.get(funcId);
        if (previous == null) {
            return;
        }
        Method previousMethod = previous.getMethod();
        Method incomingMethod = incoming.getMethod();
        if (previousMethod == null || incomingMethod == null
                || previousMethod.equals(incomingMethod)) {
            // Re-registration of the same declaration: replace, as before.
            return;
        }
        throw new IllegalStateException(String.format(
            "Overloaded @MeshTool methods share the function id '%s': %s and %s. "
                + "A @MeshTool is advertised on the wire by its bare method name, which "
                + "keys the MCP tool table, the registry's dependency resolutions and this "
                + "registry's by-name index — two overloads collapse onto that one name, "
                + "so one of them is unreachable and a dependency resolved for one can be "
                + "injected into the other. @MeshTool has no name attribute to tell them "
                + "apart: rename one of the methods, or move one to a separate class or agent.",
            funcId, previousMethod, incomingMethod));
    }

    /**
     * Index a wrapper under its bare method name, refusing to overwrite a name
     * another wrapper already claims (issue #1437).
     *
     * <p>The loser is not "the second one registered" — BOTH are dropped from
     * the bare-name index and the name is marked ambiguous, because there is no
     * defensible way to pick between them and answering with either one wires a
     * dependency resolution into the wrong tool's slot. Both remain fully
     * addressable by {@code funcId} and by {@link Method}, which is how they are
     * addressed in practice.
     *
     * <p>The collision discriminator is the <b>funcId</b>, not the wrapper
     * instance: {@link #registerWrapper} stores every other index ({@link #wrappers},
     * {@link #wrappersByMethod}, {@link #handlers}, {@link #handlersByCapability})
     * with a bare {@code put}, so re-registering the same funcId with a fresh
     * wrapper instance cleanly replaces the old one everywhere. Treating that as a
     * collision here — on instance identity — would permanently poison bare-name
     * resolution for a tool that never actually collided with anything.
     */
    private void indexBareMethodName(String methodName, MeshToolWrapper wrapper) {
        if (methodName == null) {
            return;
        }
        MeshToolWrapper previous = wrappersByMethodName.putIfAbsent(methodName, wrapper);
        if (previous == null) {
            return;
        }
        if (Objects.equals(previous.getFuncId(), wrapper.getFuncId())) {
            // Re-registration of the same tool: replace, exactly like every other index.
            wrappersByMethodName.put(methodName, wrapper);
            return;
        }
        ambiguousMethodNames.add(methodName);
        log.warn("Method name '{}' is registered by more than one @MeshTool ({} and {}) — "
                + "it no longer resolves a wrapper by name alone. Both remain addressable "
                + "by their function ids.",
            methodName, previous.getFuncId(), wrapper.getFuncId());
    }

    /**
     * Get a wrapper by function ID (for dependency updates).
     *
     * @param funcId The function ID
     * @return The wrapper, or null if not found
     */
    public MeshToolWrapper getWrapper(String funcId) {
        return wrappers.get(funcId);
    }

    /**
     * Get a wrapper by its handler {@link Method} — exact, qualified by
     * declaring class and parameter types.
     *
     * @param method The annotated {@code @MeshTool} method
     * @return The wrapper, or null if that method registered no wrapper
     */
    public MeshToolWrapper getWrapperByMethod(Method method) {
        return method == null ? null : wrappersByMethod.get(method);
    }

    /**
     * Get a wrapper by bare method name.
     *
     * <p><b>Best-effort.</b> The name carries no class, so it cannot name one of
     * several same-named {@code @MeshTool} methods; when more than one wrapper
     * claims it this returns {@code null} rather than an arbitrary one of them
     * (issue #1437). Prefer {@link #getWrapper(String)} with the function id, or
     * {@link #getWrapperByMethod(Method)}.
     *
     * @param methodName The short method name (e.g., "analyze")
     * @return The wrapper, or null if not found or the name is ambiguous
     */
    public MeshToolWrapper getWrapperByMethodName(String methodName) {
        if (methodName == null) {
            return null;
        }
        if (ambiguousMethodNames.contains(methodName)) {
            log.error("Method name '{}' names more than one @MeshTool wrapper — refusing to "
                + "resolve it to an arbitrary one. Address the tool by its function id.", methodName);
            return null;
        }
        return wrappersByMethodName.get(methodName);
    }

    /**
     * Get a handler by function ID.
     *
     * @param funcId The function ID
     * @return The handler, or null if not found
     */
    public McpToolHandler getHandler(String funcId) {
        return handlers.get(funcId);
    }

    /**
     * Get a handler by capability name.
     *
     * @param capability The capability name
     * @return The handler, or null if not found
     */
    public McpToolHandler getHandlerByCapability(String capability) {
        return handlersByCapability.get(capability);
    }

    /**
     * Get all registered handlers (for MCP server registration).
     *
     * @return Unmodifiable collection of all handlers
     */
    public Collection<McpToolHandler> getAllHandlers() {
        return Collections.unmodifiableCollection(handlers.values());
    }

    /**
     * Get all registered wrappers (MeshToolWrapper only, for backwards compat).
     *
     * @return Unmodifiable collection of MeshToolWrapper instances
     * @deprecated Use {@link #getAllHandlers()} instead
     */
    @Deprecated
    public Collection<MeshToolWrapper> getAllWrappers() {
        return Collections.unmodifiableCollection(wrappers.values());
    }

    /**
     * Get all handlers mapped by capability.
     *
     * @return Unmodifiable map of capability → handler
     */
    public Map<String, McpToolHandler> getHandlersByCapability() {
        return Collections.unmodifiableMap(handlersByCapability);
    }

    /**
     * Parse a composite key into its funcId and numeric index.
     *
     * @param compositeKey The composite key (e.g., "funcId:dep_0" or "funcId:llm_1")
     * @param separator    The separator string (DEP_SEPARATOR or LLM_SEPARATOR)
     * @return Two-element array [funcId, indexString], or null if the key is invalid
     */
    private static int parseKeyIndex(String compositeKey, String separator) {
        int sepIdx = compositeKey.lastIndexOf(separator);
        if (sepIdx < 0) return -1;
        try {
            return Integer.parseInt(compositeKey.substring(sepIdx + separator.length()));
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    private static String parseKeyFuncId(String compositeKey, String separator) {
        int sepIdx = compositeKey.lastIndexOf(separator);
        return sepIdx >= 0 ? compositeKey.substring(0, sepIdx) : null;
    }

    private MeshToolWrapper resolveWrapper(String funcId) {
        MeshToolWrapper wrapper = wrappers.get(funcId);
        if (wrapper == null) {
            // Bare-name fallback — collision-guarded (issue #1437).
            wrapper = getWrapperByMethodName(funcId);
        }
        return wrapper;
    }

    /**
     * Update a McpMeshTool dependency using composite key.
     *
     * <p>Composite key format: "funcId:dep_N" where N is the dependency index.
     * Example: "com.example.Calculator.add:dep_0"
     *
     * @param compositeKey The composite key (funcId:dep_N)
     * @param endpoint     The resolved endpoint URL
     * @param functionName The function name at the endpoint
     */
    public void updateDependency(String compositeKey, String endpoint, String functionName) {
        updateDependency(compositeKey, endpoint, functionName, null);
    }

    /**
     * Update a McpMeshTool dependency using composite key.
     *
     * <p>Idempotency guard (#1314): the Rust core re-emits
     * {@code dependency_available} for every believed-delivered edge on an
     * independent ~10s tick to self-heal dropped applies. When the incoming
     * resolution equals what is already wired for this slot
     * {@code (endpoint, functionName, agentId)} the apply is a no-op — skip it
     * so the proxy is not re-fetched and the wrapper slot is not rewritten. A
     * genuine change (different endpoint/function/agentId) still applies exactly
     * as before.
     *
     * @param compositeKey The composite key (funcId:dep_N)
     * @param endpoint     The resolved endpoint URL
     * @param functionName The function name at the endpoint
     * @param agentId      The providing agent id (part of the idempotency
     *                     signature; may be {@code null})
     */
    public void updateDependency(String compositeKey, String endpoint, String functionName, String agentId) {
        int depIndex = parseKeyIndex(compositeKey, DEP_SEPARATOR);
        if (depIndex < 0) {
            log.warn("Invalid composite key format (missing {}): {}", DEP_SEPARATOR, compositeKey);
            return;
        }

        String funcId = parseKeyFuncId(compositeKey, DEP_SEPARATOR);
        MeshToolWrapper wrapper = resolveWrapper(funcId);
        if (wrapper == null) {
            log.warn("No wrapper found for funcId: {} (also checked method name)", funcId);
            return;
        }

        // Idempotency guard (#1314): skip a re-emit that carries the identical
        // resolution already wired into this slot.
        DepSignature incoming = new DepSignature(endpoint, functionName, agentId);
        if (incoming.equals(lastAppliedByKey.get(compositeKey))) {
            log.debug("Skipping idempotent dependency apply {} for {} → {}:{} (agentId={})",
                depIndex, funcId, endpoint, functionName, agentId);
            return;
        }

        // Get the expected return type for this dependency (from McpMeshTool<T>)
        Type returnType = wrapper.getDependencyReturnType(depIndex);

        // Get or create typed proxy
        McpMeshTool<?> proxy = proxyFactory.getOrCreateProxy(endpoint, functionName, returnType);

        // Update wrapper's dependency array
        wrapper.updateDependency(depIndex, proxy);

        lastAppliedByKey.put(compositeKey, incoming);

        log.debug("Updated dependency {} for {} → {}:{} (returnType={}, agentId={})",
            depIndex, funcId, endpoint, functionName, returnType, agentId);
    }

    /**
     * Mark a dependency as unavailable.
     *
     * @param compositeKey The composite key (funcId:dep_N)
     */
    public void markDependencyUnavailable(String compositeKey) {
        int depIndex = parseKeyIndex(compositeKey, DEP_SEPARATOR);
        if (depIndex < 0) {
            return;
        }

        // Clear the idempotency signature (#1314) so a later re-add of the same
        // endpoint/function/agentId is treated as a genuine change and re-wires.
        lastAppliedByKey.remove(compositeKey);

        String funcId = parseKeyFuncId(compositeKey, DEP_SEPARATOR);
        MeshToolWrapper wrapper = resolveWrapper(funcId);
        if (wrapper != null) {
            wrapper.updateDependency(depIndex, null);
            log.debug("Marked dependency {} unavailable for {}", depIndex, funcId);
        }
    }

    /**
     * Update a MeshLlmAgent using composite key.
     *
     * <p>Composite key format: "funcId:llm_N" where N is the LLM agent index.
     *
     * @param compositeKey The composite key (funcId:llm_N)
     * @param agent        The configured LLM agent proxy
     */
    public void updateLlmAgent(String compositeKey, MeshLlmAgent agent) {
        int llmIndex = parseKeyIndex(compositeKey, LLM_SEPARATOR);
        if (llmIndex < 0) {
            log.warn("Invalid LLM composite key format (missing {}): {}", LLM_SEPARATOR, compositeKey);
            return;
        }

        String funcId = parseKeyFuncId(compositeKey, LLM_SEPARATOR);
        MeshToolWrapper wrapper = resolveWrapper(funcId);
        if (wrapper == null) {
            log.warn("No wrapper found for funcId: {} (also checked method name)", funcId);
            return;
        }

        log.info("updateLlmAgent: compositeKey='{}', funcId='{}', llmIndex={}, agent@{}",
            compositeKey, funcId, llmIndex, agent != null ? System.identityHashCode(agent) : "null");
        wrapper.updateLlmAgent(llmIndex, agent);
        log.debug("Updated LLM agent {} for {}", llmIndex, funcId);
    }

    /**
     * Build a composite key for a dependency.
     *
     * @param funcId   The function ID
     * @param depIndex The dependency index
     * @return The composite key
     */
    public static String buildDependencyKey(String funcId, int depIndex) {
        return funcId + DEP_SEPARATOR + depIndex;
    }

    /**
     * Build a composite key for an LLM agent.
     *
     * @param funcId   The function ID
     * @param llmIndex The LLM agent index
     * @return The composite key
     */
    public static String buildLlmKey(String funcId, int llmIndex) {
        return funcId + LLM_SEPARATOR + llmIndex;
    }

    /**
     * Get the number of registered wrappers.
     */
    public int size() {
        return wrappers.size();
    }

    /**
     * Check if a wrapper exists for the given function ID.
     */
    public boolean hasWrapper(String funcId) {
        return wrappers.containsKey(funcId);
    }

    /**
     * Check if a handler exists for the given capability.
     */
    public boolean hasCapability(String capability) {
        return handlersByCapability.containsKey(capability);
    }
}
