package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.SchemaMode;
import io.mcpmesh.Selector;
import io.mcpmesh.a2a.A2AConsumer;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshCoreBridge;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.BridgeMethodResolver;
import org.springframework.util.ClassUtils;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry for mesh tools discovered via annotation scanning.
 *
 * <p>Collects metadata from methods annotated with {@code @MeshTool}
 * and provides tool specifications for agent registration.
 */
public class MeshToolRegistry {

    private static final Logger log = LoggerFactory.getLogger(MeshToolRegistry.class);

    private final Map<String, ToolMetadata> tools = new ConcurrentHashMap<>();

    /**
     * Register a tool from an annotated method.
     *
     * @param bean       The bean containing the method
     * @param method     The annotated method
     * @param annotation The @MeshTool annotation
     */
    public void registerTool(Object bean, Method method, MeshTool annotation) {
        String capability = annotation.capability();

        Class<?> outputType = annotation.outputType();
        if (outputType == Void.class || outputType == void.class) {
            outputType = null;
        }

        ToolMetadata metadata = new ToolMetadata(
            capability,
            annotation.description(),
            annotation.version(),
            // Mutable list so the @A2AConsumer auto-tag injector
            // (issue #916) can append the surrounding agent name once
            // the @MeshAgent has been resolved. Kept as List<String>
            // on the record so existing readers (heartbeat builder,
            // tests) are unaffected.
            new ArrayList<>(Arrays.asList(annotation.tags())),
            extractAllDependencies(annotation, method),
            extractInputSchema(method),
            outputType,
            // Issue #547 Phase 4: per-tool override (default true = current behavior).
            annotation.outputSchemaStrict(),
            // Phase B MeshJob substrate: surfaced via kwargs JSON so the
            // registry / consumer SDK knows this is a task=true producer.
            annotation.task(),
            // Issue #895: per-tool retry-eligible exception whitelist. The
            // bean post-processor has already validated `retryOn requires
            // task=true` before this call, so we only need to capture it
            // here for downstream dispatch wiring.
            annotation.retryOn(),
            bean,
            method
        );

        // Issue #1164 LOW: duplicate capability names previously overwrote
        // last-wins, silently shadowing one tool with another. Fail fast at
        // boot with a descriptive error (mirrors the
        // MeshCapabilityBeanRegistrar.mergeDependency conflict style).
        // Tolerated as idempotent refreshes instead of conflicts:
        //   - the SAME method (prototype-scoped bean instantiated more than
        //     once, context refresh in the same JVM);
        //   - an OVERRIDE PAIR on the SAME bean instance — one method
        //     overrides the other in a class hierarchy (incl. generic
        //     bridges). External scanners may legitimately register both the
        //     superclass declaration and the subclass override of one logical
        //     tool; the most-derived declaration wins (#1164 review
        //     follow-up). The bean-identity guard keeps SIBLING beans honest:
        //     a BaseCalc bean AND a DerivedCalc bean sharing a capability are
        //     two tools, not one — without the guard the subclass bean
        //     silently masked the base bean.
        ToolMetadata existing = tools.putIfAbsent(capability, metadata);
        if (existing != null) {
            Method existingMethod = existing.method();
            if (existingMethod.equals(method)) {
                // Deliberately tolerant of a DIFFERENT bean instance here:
                // prototype-scoped beans and Spring context refresh re-run the
                // post-processor with NEW instances of the same class —
                // requiring bean identity would falsely boot-fail those paths.
                // Last-registered wins; logged at info (not debug) so the
                // replacement is visible when two live instances genuinely
                // compete (#1164 review follow-up).
                tools.put(capability, metadata);
                if (existing.bean() != bean) {
                    log.info("Mesh tool '{}' re-registered for the same method {} with a new bean "
                        + "instance — last registration wins (prototype scope / context refresh)",
                        capability, method);
                } else {
                    log.debug("Mesh tool '{}' re-registered for the same method {} — idempotent refresh",
                        capability, method);
                }
                return;
            }
            Method mostDerived = mostDerivedOverride(existingMethod, method);
            if (mostDerived != null && existing.bean() == bean) {
                if (mostDerived.equals(BridgeMethodResolver.findBridgedMethod(method))) {
                    tools.put(capability, metadata);
                    log.debug("Mesh tool '{}': {} overrides previously registered {} — most-derived wins",
                        capability, method, existingMethod);
                } else {
                    log.debug("Mesh tool '{}': keeping already-registered override {} over base declaration {}",
                        capability, existingMethod, method);
                }
                return;
            }
            String hint = mostDerived != null
                ? "The methods form an override pair but belong to two different bean "
                    + "instances — register only one of the beans."
                : "Capability names must be unique within an agent — rename one of "
                    + "the tools or remove the duplicate.";
            throw new IllegalStateException(String.format(
                "Duplicate @MeshTool capability '%s': already registered by %s.%s, "
                    + "declared again by %s.%s. %s",
                capability,
                existing.method().getDeclaringClass().getName(), existing.method().getName(),
                method.getDeclaringClass().getName(), method.getName(),
                hint));
        }

        log.info("Registered mesh tool: {} ({}, task={}, retryOn={})",
            capability, method, annotation.task(), annotation.retryOn().length);
    }

    /**
     * Detect whether two distinct {@link Method} objects describe ONE logical
     * tool — i.e. one overrides the other within a class hierarchy. Returns
     * the most-derived declaration (bridge-resolved), or {@code null} when
     * the methods are genuinely distinct (the caller then raises the
     * duplicate-capability boot error).
     *
     * <p>Handles generic overrides: a base declaration like
     * {@code T handle(T)} resolved against the subclass yields the bridge
     * {@code handle(Object)}, which {@link BridgeMethodResolver} maps back to
     * the user-declared {@code handle(String)} override.
     */
    private static Method mostDerivedOverride(Method a, Method b) {
        Method ra = BridgeMethodResolver.findBridgedMethod(a);
        Method rb = BridgeMethodResolver.findBridgedMethod(b);
        if (!ra.getName().equals(rb.getName())) {
            return null;
        }
        Class<?> da = ra.getDeclaringClass();
        Class<?> db = rb.getDeclaringClass();
        Method derived;
        Method base;
        if (da.equals(db)) {
            return null;
        } else if (da.isAssignableFrom(db)) {
            derived = rb;
            base = ra;
        } else if (db.isAssignableFrom(da)) {
            derived = ra;
            base = rb;
        } else {
            return null;
        }
        // Same logical method iff resolving the base declaration against the
        // derived class (then un-bridging) lands on the derived declaration.
        Method resolved = BridgeMethodResolver.findBridgedMethod(
            ClassUtils.getMostSpecificMethod(base, derived.getDeclaringClass()));
        return resolved.equals(derived) ? derived : null;
    }

    // Phase B MeshJob substrate: synthetic tool specs registered outside
    // the @MeshTool scan path (e.g. helper tools). Appended to the
    // heartbeat catalog after user tools so they advertise in the registry.
    private final List<AgentSpec.ToolSpec> syntheticTools = new java.util.concurrent.CopyOnWriteArrayList<>();

    /**
     * Add a synthetic tool spec to be merged into the heartbeat catalog.
     * Used by {@link JobsHelperToolsRegistrar} to advertise the three
     * MeshJob helper tools as registry-visible capabilities.
     *
     * <p>Idempotent by capability: if a synthetic tool with the same
     * capability is already registered the call is a no-op. Without
     * this guard a repeated {@code buildAgentSpec()} (e.g. test refresh
     * or context restart in the same JVM) would accumulate duplicate
     * helper specs in the heartbeat (PR review #874).
     */
    public void addSyntheticTool(AgentSpec.ToolSpec spec) {
        if (spec == null || spec.getCapability() == null) {
            return;
        }
        // Synchronize the check-then-add: CopyOnWriteArrayList serializes
        // mutations individually, but the iterate-then-add window is open
        // to concurrent registrations from two threads observing
        // "no existing capability" simultaneously and both appending.
        // (PR #891 review.)
        synchronized (syntheticTools) {
            for (AgentSpec.ToolSpec existing : syntheticTools) {
                if (spec.getCapability().equals(existing.getCapability())) {
                    return;
                }
            }
            syntheticTools.add(spec);
        }
    }

    /**
     * Get all registered tools as AgentSpec ToolSpecs.
     *
     * @return List of tool specifications
     */
    public List<AgentSpec.ToolSpec> getToolSpecs() {
        List<AgentSpec.ToolSpec> specs = new ArrayList<>();
        var jsonMapper = JsonMapper.builder().build();

        // Issue #547 Phase 4: cluster-wide strict knob (env var). Per-tool
        // override is read from each tool's metadata inside the loop.
        boolean clusterStrict = MeshSchemaSupport.clusterStrictEnabled();

        for (ToolMetadata meta : tools.values()) {
            AgentSpec.ToolSpec spec = new AgentSpec.ToolSpec();
            spec.setFunctionName(meta.method().getName());
            spec.setCapability(meta.capability());
            spec.setDescription(meta.description());
            spec.setVersion(meta.version());
            // Defensive copy: meta.tags() is the registry's mutable
            // source-of-truth (mutated by injectConsumerNameTags). Aliasing
            // it into the emitted ToolSpec would let downstream consumers
            // mutate the registry, and would expose a concurrent-iterate
            // window to the heartbeat thread while autoconfig appends.
            spec.setTags(new ArrayList<>(meta.tags()));

            // Convert input schema Map to JSON string. The input schema is built
            // from @Param annotations only, so mesh DI parameters (McpMeshTool /
            // MeshLlmAgent) are already excluded by construction (#547).
            String inputSchemaJson;
            try {
                inputSchemaJson = jsonMapper.writeValueAsString(meta.inputSchema());
            } catch (Exception e) {
                inputSchemaJson = "{}";
            }
            spec.setInputSchema(inputSchemaJson);

            // Issue #547 / Phase 4: normalize input + output schemas via Rust core
            // and apply the verdict policy (cluster strict + per-tool override).
            List<String> warnings = new ArrayList<>();
            String contextBase = "tool '" + meta.capability() + "'";
            boolean toolStrict = meta.outputSchemaStrict();

            MeshCoreBridge.NormalizeResult inputResult = MeshSchemaSupport.normalizeWithPolicy(
                inputSchemaJson, "java", contextBase + " input", clusterStrict, toolStrict);
            if (inputResult != null) {
                spec.setInputSchemaCanonical(inputResult.canonicalJson());
                spec.setInputSchemaHash(inputResult.hash());
                MeshSchemaSupport.mergeWarnings(warnings, inputResult.warnings());
            }

            if (meta.outputType() != null) {
                String outputSchemaJson = MeshSchemaSupport.generateRawSchemaJson(meta.outputType());
                if (outputSchemaJson != null) {
                    spec.setOutputSchema(outputSchemaJson);
                    MeshCoreBridge.NormalizeResult outputResult = MeshSchemaSupport.normalizeWithPolicy(
                        outputSchemaJson, "java", contextBase + " output", clusterStrict, toolStrict);
                    if (outputResult != null) {
                        spec.setOutputSchemaCanonical(outputResult.canonicalJson());
                        spec.setOutputSchemaHash(outputResult.hash());
                        MeshSchemaSupport.mergeWarnings(warnings, outputResult.warnings());
                    }
                }
            }

            if (!warnings.isEmpty()) {
                spec.setSchemaWarnings(warnings);
            }

            // Phase B MeshJob substrate: surface task=true through kwargs
            // so the registry / consumer SDK can detect this is a task tool
            // (matches Python's "kwargs spread of @mesh.tool decorator
            // metadata" wire — see rust_heartbeat.py kwargs_data block).
            if (meta.task()) {
                try {
                    Map<String, Object> kwargs = new LinkedHashMap<>();
                    kwargs.put("task", true);
                    spec.setKwargs(jsonMapper.writeValueAsString(kwargs));
                } catch (Exception e) {
                    log.warn("Failed to serialize kwargs for task tool '{}': {}",
                        meta.capability(), e.getMessage());
                }
            }

            // Add dependencies to the tool spec
            for (DependencyInfo dep : meta.dependencies()) {
                AgentSpec.DependencySpec depSpec = new AgentSpec.DependencySpec();
                depSpec.setCapability(dep.capability());
                try {
                    depSpec.setTags(jsonMapper.writeValueAsString(dep.tags()));
                } catch (Exception e) {
                    log.warn("Failed to serialize tags for dependency '{}' — registering with no tag constraint: {}",
                        dep.capability(), e.getMessage());
                    depSpec.setTags("[]");
                }
                depSpec.setVersion(dep.version());
                // Issue #1249: carry the required flag through to the spec JSON
                // (omitted when false via NON_DEFAULT on AgentSpec.DependencySpec).
                depSpec.setRequired(dep.required());
                applySchemaMatching(depSpec, dep, clusterStrict);
                spec.getDependencies().add(depSpec);
            }

            specs.add(spec);
        }

        // Phase B MeshJob substrate: append synthetic tools (helper tools).
        specs.addAll(syntheticTools);

        return specs;
    }

    /**
     * Get all registered tool metadata.
     *
     * @return Collection of tool metadata
     */
    public Collection<ToolMetadata> getAllTools() {
        return Collections.unmodifiableCollection(tools.values());
    }

    /**
     * Issue #916 Phase 1: append the surrounding {@code @MeshAgent} name
     * as a tag on every tool also annotated with
     * {@link io.mcpmesh.a2a.A2AConsumer @A2AConsumer}, idempotent.
     *
     * <p>Called from {@code MeshAutoConfiguration.buildAgentSpec} once
     * the agent name is resolved (env override, properties, or the
     * annotation literal) but BEFORE {@link #getToolSpecs()} is read
     * into the heartbeat catalog. Skipped silently when {@code agentName}
     * is null/blank — the consumer-only / nameless mode of the runtime
     * never reaches this code path with a real name, so we leave the
     * tool tags untouched and let the call go up unmodified.
     *
     * <p>Java equivalent of Python's
     * {@code _resolve_pending_consumer_self_tags} (mesh.decorators):
     * the annotation marker substitutes for the
     * {@code __MESH_CONSUMER_SELF__} sentinel, and this method takes
     * the role of the deferred substitution pass.
     *
     * @param agentName the resolved {@code @MeshAgent} name; no-op when
     *                  null or blank.
     */
    public void injectConsumerNameTags(String agentName) {
        if (agentName == null || agentName.isBlank()) {
            return;
        }
        for (ToolMetadata meta : tools.values()) {
            java.lang.reflect.Method method = meta.method();
            if (method == null) {
                continue;
            }
            if (!method.isAnnotationPresent(A2AConsumer.class)) {
                continue;
            }
            List<String> current = meta.tags();
            if (current == null) {
                continue;
            }
            // Idempotent: skip when the tag is already there. Repeated
            // calls (e.g. test refresh, context restart) must not
            // accumulate duplicates in the heartbeat tag list.
            if (current.contains(agentName)) {
                log.debug("@A2AConsumer tool '{}': consumer-name tag '{}' already present, skipping",
                    meta.capability(), agentName);
                continue;
            }
            try {
                current.add(agentName);
                log.info("@A2AConsumer tool '{}': injected consumer-name tag '{}'",
                    meta.capability(), agentName);
            } catch (UnsupportedOperationException e) {
                // Defensive: registerTool builds a mutable ArrayList,
                // but external callers using ToolMetadata's public
                // constructor could supply an immutable list. Surface
                // a warning instead of crashing the agent.
                log.warn("@A2AConsumer tool '{}': tags list is immutable, cannot inject "
                        + "consumer-name auto-tag '{}' — the tool will be missing this tag "
                        + "in the registry. Construct ToolMetadata with a mutable List<String> "
                        + "(e.g. new ArrayList<>(...)) to enable auto-tag injection.",
                    meta.capability(), agentName);
            }
        }
    }

    /**
     * Get tool metadata by capability name.
     *
     * @param capability The capability name
     * @return Tool metadata, or null if not found
     */
    public ToolMetadata getTool(String capability) {
        return tools.get(capability);
    }

    /**
     * Get all dependency specifications.
     *
     * @return List of dependency specs
     */
    public List<AgentSpec.DependencySpec> getDependencySpecs() {
        List<AgentSpec.DependencySpec> deps = new ArrayList<>();
        boolean clusterStrict = MeshSchemaSupport.clusterStrictEnabled();

        for (ToolMetadata meta : tools.values()) {
            for (DependencyInfo dep : meta.dependencies()) {
                AgentSpec.DependencySpec spec = new AgentSpec.DependencySpec();
                spec.setCapability(dep.capability());
                // Convert List<String> to JSON array string
                try {
                    spec.setTags(JsonMapper.builder().build()
                        .writeValueAsString(dep.tags()));
                } catch (Exception e) {
                    spec.setTags("[]");
                }
                spec.setVersion(dep.version());
                spec.setRequired(dep.required());
                applySchemaMatching(spec, dep, clusterStrict);
                deps.add(spec);
            }
        }

        return deps;
    }

    /**
     * RFC #1280 phase 2: the tool's full declared dependency list = explicit
     * {@code @Selector} deps FIRST, then each {@code @McpMeshService} view
     * parameter's method edges (parameter order, method-name order). This order
     * MUST match {@link MeshToolWrapper}'s declared-index space so the Rust
     * core's {@code funcId:dep_N} resolution events land on the right slot.
     */
    private List<DependencyInfo> extractAllDependencies(MeshTool annotation, Method method) {
        List<DependencyInfo> deps = extractDependencies(annotation.dependencies());
        for (McpMeshServiceToolSupport.ViewParamInfo vp
                : McpMeshServiceToolSupport.analyzeViewParams(method)) {
            for (McpMeshServiceRegistrar.ServiceMethodBinding b : vp.view().bindings()) {
                deps.add(new DependencyInfo(
                    b.capability(),
                    Arrays.asList(b.tags()),
                    b.version(),
                    b.schemaExpectedType(),
                    b.schemaMode(),
                    b.required()));
            }
        }
        return deps;
    }

    private List<DependencyInfo> extractDependencies(Selector[] selectors) {
        List<DependencyInfo> deps = new ArrayList<>();
        for (Selector sel : selectors) {
            if (!sel.capability().isEmpty()) {
                Class<?> expectedType = sel.expectedType();
                if (expectedType == Void.class || expectedType == void.class) {
                    expectedType = null;
                }
                deps.add(new DependencyInfo(
                    sel.capability(),
                    Arrays.asList(sel.tags()),
                    sel.version(),
                    expectedType,
                    sel.schemaMode(),
                    sel.required()
                ));
            }
        }
        return deps;
    }

    /**
     * Apply issue #547 schema-aware matching fields to the outgoing AgentSpec
     * dependency. Mirrors {@code MeshRouteRegistry.applySchemaMatching}:
     *
     * <ul>
     *   <li>{@code expectedType} set, {@code schemaMode} unset → default mode SUBSET</li>
     *   <li>{@code schemaMode} set, {@code expectedType} unset → log warning, no schema check</li>
     *   <li>{@code expectedType} set + {@code schemaMode} != NONE → normalize and ship</li>
     *   <li>both unset → backward-compatible no-op</li>
     * </ul>
     *
     * <p>Phase 4: cluster-wide strict knob promotes WARN→BLOCK on the consumer
     * side too. There's no per-tool override here — the override is producer-side.
     */
    private static void applySchemaMatching(
            AgentSpec.DependencySpec target, DependencyInfo source, boolean clusterStrict) {
        Class<?> expectedType = source.expectedType();
        SchemaMode mode = source.schemaMode();
        boolean modeRequested = mode != null && mode != SchemaMode.NONE;

        if (expectedType == null && !modeRequested) {
            return;
        }
        if (expectedType == null) {
            log.warn("Dependency '{}' sets schemaMode={} but no expectedType — ignoring schema match",
                source.capability(), mode);
            return;
        }
        SchemaMode effectiveMode = modeRequested ? mode : SchemaMode.SUBSET;

        String rawJson = MeshSchemaSupport.generateRawSchemaJson(expectedType);
        if (rawJson == null) {
            log.warn("Dependency '{}': failed to generate JSON Schema for expectedType {} — skipping schema match",
                source.capability(), expectedType.getName());
            return;
        }
        MeshCoreBridge.NormalizeResult result = MeshSchemaSupport.normalizeWithPolicy(
            rawJson, "java", "dependency '" + source.capability() + "' expected schema",
            clusterStrict, true);
        if (result == null) {
            return;
        }
        target.setExpectedSchemaCanonical(result.canonicalJson());
        target.setExpectedSchemaHash(result.hash());
        target.setMatchMode(effectiveMode == SchemaMode.STRICT ? "strict" : "subset");
    }

    /**
     * Issue #1164 MED-2: delegate to the shared victools-backed builder in
     * {@link MeshSchemaSupport} — the SAME method {@link MeshToolWrapper} uses
     * for the MCP-served schema — so the heartbeat-advertised
     * {@code input_schema} / {@code input_schema_canonical} /
     * {@code input_schema_hash} can never drift from what the MCP server
     * actually serves. (The previous hand-rolled builder emitted bare
     * {@code {"type":"object"}} for POJO params and {@code {"type":"array"}}
     * for {@code List<Foo>} — no properties, no items, no required.)
     */
    private Map<String, Object> extractInputSchema(Method method) {
        return MeshSchemaSupport.buildToolInputSchema(method);
    }

    /**
     * Metadata about a registered tool.
     *
     * <p>{@code outputType} is the optional return type from {@link MeshTool#outputType()},
     * used for output-schema generation (issue #547). Null when the user did not opt in.
     *
     * <p>{@code outputSchemaStrict} mirrors {@link MeshTool#outputSchemaStrict()} —
     * when false, BLOCK verdicts for this tool are demoted to WARN instead of
     * refusing startup (issue #547 Phase 4).
     *
     * <p>{@code retryOn} mirrors {@link MeshTool#retryOn()} (issue #895) — the
     * per-tool exception whitelist that triggers release-and-retry instead of
     * fail() when a {@code task=true} handler raises. Always non-null (defaults
     * to a zero-length array).
     */
    public record ToolMetadata(
        String capability,
        String description,
        String version,
        List<String> tags,
        List<DependencyInfo> dependencies,
        Map<String, Object> inputSchema,
        Class<?> outputType,
        boolean outputSchemaStrict,
        boolean task,
        Class<? extends Throwable>[] retryOn,
        Object bean,
        Method method
    ) {
        // Backward-compatible 10-arg constructor for callers that haven't
        // adopted the Phase B `task` flag yet (defaults to false).
        public ToolMetadata(
                String capability,
                String description,
                String version,
                List<String> tags,
                List<DependencyInfo> dependencies,
                Map<String, Object> inputSchema,
                Class<?> outputType,
                boolean outputSchemaStrict,
                Object bean,
                Method method) {
            this(capability, description, version, tags, dependencies, inputSchema,
                outputType, outputSchemaStrict, false, EMPTY_RETRY_ON, bean, method);
        }

        // Backward-compatible 11-arg constructor for callers that adopted
        // the `task` flag but predate the issue #895 retryOn field.
        public ToolMetadata(
                String capability,
                String description,
                String version,
                List<String> tags,
                List<DependencyInfo> dependencies,
                Map<String, Object> inputSchema,
                Class<?> outputType,
                boolean outputSchemaStrict,
                boolean task,
                Object bean,
                Method method) {
            this(capability, description, version, tags, dependencies, inputSchema,
                outputType, outputSchemaStrict, task, EMPTY_RETRY_ON, bean, method);
        }

        @SuppressWarnings("unchecked")
        private static final Class<? extends Throwable>[] EMPTY_RETRY_ON =
            (Class<? extends Throwable>[]) new Class<?>[0];
    }

    /**
     * Information about a tool dependency.
     *
     * <p>{@code expectedType} and {@code schemaMode} carry the issue #547
     * schema-aware matching opt-in from {@link Selector#expectedType()} and
     * {@link Selector#schemaMode()}. {@code expectedType} is null when not set;
     * {@code schemaMode} defaults to {@link SchemaMode#NONE}.
     */
    public record DependencyInfo(
        String capability,
        List<String> tags,
        String version,
        Class<?> expectedType,
        SchemaMode schemaMode,
        boolean required
    ) {
        public DependencyInfo(String capability, List<String> tags, String version) {
            this(capability, tags, version, null, SchemaMode.NONE, false);
        }

        public DependencyInfo(String capability, List<String> tags, String version,
                              Class<?> expectedType, SchemaMode schemaMode) {
            this(capability, tags, version, expectedType, schemaMode, false);
        }
    }
}
