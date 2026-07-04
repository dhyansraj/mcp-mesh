package io.mcpmesh.spring.web;

import io.mcpmesh.SchemaMode;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshCoreBridge;
import io.mcpmesh.spring.MeshSchemaSupport;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry for @MeshRoute annotated endpoints.
 *
 * <p>Stores route metadata discovered during bean post-processing for
 * lookup during request handling.
 */
public class MeshRouteRegistry {

    private static final Logger log = LoggerFactory.getLogger(MeshRouteRegistry.class);

    /**
     * Routes indexed by "METHOD:path" (e.g., "POST:/api/upload").
     */
    private final Map<String, RouteMetadata> routesByPath = new ConcurrentHashMap<>();

    /**
     * Routes indexed by handler method ID (ClassName.methodName).
     */
    private final Map<String, RouteMetadata> routesByHandler = new ConcurrentHashMap<>();

    /**
     * Register a @MeshRoute endpoint.
     *
     * @param httpMethod HTTP method (GET, POST, etc.)
     * @param path       URL path pattern
     * @param metadata   Route metadata
     */
    public void register(String httpMethod, String path, RouteMetadata metadata) {
        String routeId = buildRouteId(httpMethod, path);
        routesByPath.put(routeId, metadata);
        routesByHandler.put(metadata.getHandlerMethodId(), metadata);

        // Settling-window grace (#1193): declare this route's dependency
        // capabilities with the process-wide settle state so the
        // agent-level "all declared deps resolved" latch can flip eagerly.
        // Capability keying is correct for routes (unlike tool wrappers'
        // per-slot composite keys): every route resolves through the
        // injector's shared per-capability proxy, updated before its
        // countdown — see MeshRouteHandlerInterceptor.
        io.mcpmesh.spring.MeshSettleState settleState =
            io.mcpmesh.spring.MeshSettleState.getInstance();
        for (DependencySpec dep : metadata.getDependencies()) {
            settleState.registerDeclared(dep.getCapability());
        }

        log.info("Registered @MeshRoute: {} {} with {} dependencies",
            httpMethod, path, metadata.getDependencies().size());
    }

    /**
     * Get route metadata by HTTP method and path.
     *
     * @param httpMethod HTTP method
     * @param path       URL path
     * @return route metadata or null if not found
     */
    public RouteMetadata getByRoute(String httpMethod, String path) {
        return routesByPath.get(buildRouteId(httpMethod, path));
    }

    /**
     * Get route metadata by handler method ID.
     *
     * @param handlerMethodId "ClassName.methodName" identifier
     * @return route metadata or null if not found
     */
    public RouteMetadata getByHandlerMethodId(String handlerMethodId) {
        return routesByHandler.get(handlerMethodId);
    }

    /**
     * Get all registered routes.
     *
     * @return unmodifiable collection of all route metadata
     */
    public Collection<RouteMetadata> getAllRoutes() {
        return Collections.unmodifiableCollection(routesByPath.values());
    }

    /**
     * Check if any routes are registered.
     *
     * @return true if at least one route is registered
     */
    public boolean hasRoutes() {
        return !routesByPath.isEmpty();
    }

    /**
     * Get the number of registered routes.
     *
     * @return route count
     */
    public int getRouteCount() {
        return routesByPath.size();
    }

    /**
     * Get unique dependency capabilities from all routes for agent registration.
     *
     * <p>These dependencies will be included in the agent heartbeat so the
     * Rust core can resolve them via the registry.
     *
     * @return list of unique AgentSpec.DependencySpec for route dependencies
     */
    public List<AgentSpec.DependencySpec> getUniqueDependencySpecs() {
        // Keyed by capability, insertion-ordered. Issue #1249: required WINS on
        // merge — see the conflict branch below.
        Map<String, AgentSpec.DependencySpec> byCapability = new LinkedHashMap<>();
        var jsonMapper = JsonMapper.builder().build();
        // Issue #547 Phase 4: cluster-wide strict knob promotes WARN→BLOCK.
        boolean clusterStrict = MeshSchemaSupport.clusterStrictEnabled();

        for (RouteMetadata route : routesByPath.values()) {
            for (DependencySpec dep : route.getDependencies()) {
                AgentSpec.DependencySpec existing = byCapability.get(dep.getCapability());
                if (existing != null) {
                    // Issue #1249: dedupe on capability is otherwise first-wins,
                    // but iteration order over the route map is nondeterministic
                    // (ConcurrentHashMap). A required=true declaration must never
                    // be silently dropped just because a non-required declaration
                    // of the same capability happened to be visited first —
                    // required WINS on merge.
                    if (dep.isRequired() && !existing.isRequired()) {
                        log.warn("Capability '{}' is declared by multiple @MeshRoute dependencies "
                                + "with conflicting required flags — upgrading the deduped dependency "
                                + "to required=true (required wins on merge)",
                            dep.getCapability());
                        existing.setRequired(true);
                    }
                    continue;
                }
                AgentSpec.DependencySpec agentDep = new AgentSpec.DependencySpec();
                agentDep.setCapability(dep.getCapability());
                if (dep.hasTags()) {
                    // Issue #1158: tags is contractually a JSON-array string
                    // (the Rust core JSON-parses it; a comma-joined string
                    // silently degrades to "no tag constraint").
                    try {
                        agentDep.setTags(jsonMapper.writeValueAsString(dep.getTags()));
                    } catch (Exception e) {
                        log.warn("Failed to serialize tags for dependency '{}' — registering with no tag constraint: {}",
                            dep.getCapability(), e.getMessage());
                        agentDep.setTags("[]");
                    }
                }
                if (dep.hasVersion()) {
                    agentDep.setVersion(dep.getVersion());
                }
                // Issue #1249: carry required through to the spec JSON
                // (omitted when false via NON_DEFAULT on the AgentSpec dep).
                agentDep.setRequired(dep.isRequired());
                applySchemaMatching(agentDep, dep, clusterStrict);
                byCapability.put(dep.getCapability(), agentDep);
            }
        }

        return new ArrayList<>(byCapability.values());
    }

    /**
     * Cross-source required-wins (2.8.1): promote every route dependency
     * matching {@code capability} to required=true. Called when another
     * declaration source (e.g. a {@code @MeshDependsOn} bean) marks the same
     * capability required — without this, the merged agent spec would
     * advertise the edge as required while the request-time 503 perimeter
     * ({@link MeshRouteHandlerInterceptor}, which reads the route's own
     * {@link DependencySpec#isRequired()}) still soft-served a null dependency
     * (split-brain).
     *
     * @return {@code true} when at least one route dependency was promoted.
     */
    public boolean promoteCapabilityToRequired(String capability) {
        boolean promoted = false;
        for (RouteMetadata route : routesByPath.values()) {
            for (DependencySpec dep : route.getDependencies()) {
                if (capability.equals(dep.getCapability()) && !dep.isRequired()) {
                    dep.setRequired(true);
                    promoted = true;
                }
            }
        }
        return promoted;
    }

    /**
     * Surface the {@code expectedType} declared on each {@code @MeshDependency}
     * across all registered routes. Returns the Class<?> reference for every
     * capability whose source annotation set {@code expectedType} to a
     * non-default value (i.e. not {@code Void.class}).
     *
     * <p>Used by the auto-configuration late-phase bean registrar to wire
     * typed deserialisation into the {@link io.mcpmesh.types.McpMeshTool}
     * singleton beans — without this, a
     * {@code @Qualifier("cap") McpMeshTool<Foo>} consumer receives an
     * untyped proxy that returns {@code Map<String, Object>} instead of
     * {@code Foo}.
     *
     * @return map of capability name to expected return Class; capabilities
     *         without expectedType are absent from the map
     */
    public Map<String, Class<?>> getExpectedTypesByCapability() {
        Map<String, Class<?>> result = new LinkedHashMap<>();
        for (RouteMetadata route : routesByPath.values()) {
            for (DependencySpec dep : route.getDependencies()) {
                Class<?> et = dep.getExpectedType();
                if (et != null && et != Void.class && et != void.class) {
                    result.putIfAbsent(dep.getCapability(), et);
                }
            }
        }
        return result;
    }

    /**
     * Apply issue #547 schema-aware matching fields to the outgoing AgentSpec
     * dependency. Mirrors the Python ({@code mesh.tool} decorator) and TypeScript
     * (Zod expectedSchema) behaviors:
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
     *
     * <p>Package-private convenience overload shared by the {@code @MeshRoute},
     * {@code @MeshDependsOn}, AND {@code @MeshA2A} wiring paths — they all hold a
     * {@link DependencySpec} and need the same schema-matching fields stamped.
     */
    static void applySchemaMatching(
            AgentSpec.DependencySpec target, DependencySpec source, boolean clusterStrict) {
        applySchemaMatching(target, source.getCapability(), source.getExpectedType(),
            source.getSchemaMode(), clusterStrict);
    }

    /**
     * Canonical schema-aware matching helper, shared between the
     * {@code @MeshRoute}, {@code @MeshDependsOn}, and {@code @MeshA2A} wiring
     * paths (issue #547, issue #1086, issue #1089). All surfaces must stamp
     * {@code expectedSchemaCanonical}, {@code expectedSchemaHash}, and
     * {@code matchMode} the same way so the registry's schema stage sees
     * identical shapes regardless of the source.
     *
     * <p>Caller passes raw inputs (capability name, expected type class,
     * schema mode, cluster-strict flag) so {@code @MeshDependsOn}'s code path
     * — which reads these off {@link MeshDependency} directly — doesn't need
     * to materialise a {@link DependencySpec} intermediate.
     *
     * @param target        the outgoing {@link AgentSpec.DependencySpec} to mutate
     * @param capability    capability name (for log context)
     * @param expectedType  expected return type, or {@code null} when unset
     * @param mode          requested {@link SchemaMode} (treated as {@link SchemaMode#NONE} when null)
     * @param clusterStrict cluster-wide strict knob (typically from env var)
     */
    public static void applySchemaMatching(
            AgentSpec.DependencySpec target,
            String capability,
            Class<?> expectedType,
            SchemaMode mode,
            boolean clusterStrict) {
        boolean modeRequested = mode != null && mode != SchemaMode.NONE;

        if (expectedType == null && !modeRequested) {
            return; // backward-compatible: nothing to do
        }
        if (expectedType == null) {
            log.warn("Dependency '{}' sets schemaMode={} but no expectedType — ignoring schema match",
                capability, mode);
            return;
        }
        // Default mode SUBSET when caller provides expectedType only (parity with Python).
        SchemaMode effectiveMode = modeRequested ? mode : SchemaMode.SUBSET;

        String rawJson = MeshSchemaSupport.generateRawSchemaJson(expectedType);
        if (rawJson == null) {
            log.warn("Dependency '{}': failed to generate JSON Schema for expectedType {} — skipping schema match",
                capability, expectedType.getName());
            return;
        }
        MeshCoreBridge.NormalizeResult result = MeshSchemaSupport.normalizeWithPolicy(
            rawJson, "java", "dependency '" + capability + "' expected schema",
            clusterStrict, true);
        if (result == null) {
            return;
        }
        target.setExpectedSchemaCanonical(result.canonicalJson());
        target.setExpectedSchemaHash(result.hash());
        target.setMatchMode(effectiveMode == SchemaMode.STRICT ? "strict" : "subset");
    }

    private String buildRouteId(String httpMethod, String path) {
        return httpMethod.toUpperCase() + ":" + path;
    }

    /**
     * Metadata for a @MeshRoute annotated endpoint.
     */
    public static class RouteMetadata {
        private final String handlerMethodId;
        private final List<DependencySpec> dependencies;
        private final String description;
        private final boolean failOnMissingDependency;

        public RouteMetadata(String handlerMethodId, List<DependencySpec> dependencies,
                            String description, boolean failOnMissingDependency) {
            this.handlerMethodId = handlerMethodId;
            this.dependencies = dependencies != null ? dependencies : Collections.emptyList();
            this.description = description;
            this.failOnMissingDependency = failOnMissingDependency;
        }

        public String getHandlerMethodId() {
            return handlerMethodId;
        }

        public List<DependencySpec> getDependencies() {
            return dependencies;
        }

        public String getDescription() {
            return description;
        }

        public boolean isFailOnMissingDependency() {
            return failOnMissingDependency;
        }

        /**
         * Find dependency spec by capability name.
         *
         * @param capability capability name
         * @return dependency spec or null if not found
         */
        public DependencySpec findDependency(String capability) {
            return dependencies.stream()
                .filter(d -> d.getCapability().equals(capability))
                .findFirst()
                .orElse(null);
        }

        /**
         * Get the parameter name for a capability.
         *
         * @param capability capability name
         * @return parameter name (from spec or derived from capability)
         */
        public String getParameterName(String capability) {
            DependencySpec spec = findDependency(capability);
            if (spec != null && spec.getParameterName() != null && !spec.getParameterName().isEmpty()) {
                return spec.getParameterName();
            }
            // Convert kebab-case to camelCase
            return toCamelCase(capability);
        }

        private String toCamelCase(String kebab) {
            if (!kebab.contains("-")) {
                return kebab;
            }
            StringBuilder result = new StringBuilder();
            boolean capitalizeNext = false;
            for (char c : kebab.toCharArray()) {
                if (c == '-') {
                    capitalizeNext = true;
                } else if (capitalizeNext) {
                    result.append(Character.toUpperCase(c));
                    capitalizeNext = false;
                } else {
                    result.append(c);
                }
            }
            return result.toString();
        }
    }

    /**
     * Specification for a single dependency.
     */
    public static class DependencySpec {
        private final String capability;
        private final String[] tags;
        private final String version;
        private final String parameterName;
        private final Class<?> expectedType;
        private final SchemaMode schemaMode;
        // Not final: cross-source required-wins (2.8.1) may promote a route
        // dependency to required=true after construction when a @MeshDependsOn
        // on the same capability declares required — see
        // MeshRouteRegistry.promoteCapabilityToRequired.
        private boolean required;
        private Type returnType;  // Set by BeanPostProcessor after construction

        public DependencySpec(String capability, String[] tags, String version, String parameterName) {
            this(capability, tags, version, parameterName, null, SchemaMode.NONE, false);
        }

        public DependencySpec(String capability, String[] tags, String version, String parameterName,
                              Class<?> expectedType, SchemaMode schemaMode) {
            this(capability, tags, version, parameterName, expectedType, schemaMode, false);
        }

        public DependencySpec(String capability, String[] tags, String version, String parameterName,
                              Class<?> expectedType, SchemaMode schemaMode, boolean required) {
            this.capability = capability;
            this.tags = tags != null ? tags : new String[0];
            this.version = version;
            this.parameterName = parameterName;
            this.expectedType = expectedType;
            this.schemaMode = schemaMode != null ? schemaMode : SchemaMode.NONE;
            this.required = required;
        }

        /**
         * Create from @MeshDependency annotation.
         */
        public static DependencySpec fromAnnotation(MeshDependency annotation) {
            String paramName = annotation.name();
            if (paramName == null || paramName.isEmpty()) {
                // Convert capability to camelCase for parameter name
                paramName = toCamelCase(annotation.capability());
            }
            Class<?> expectedType = annotation.expectedType();
            if (expectedType == Void.class || expectedType == void.class) {
                expectedType = null;
            }
            return new DependencySpec(
                annotation.capability(),
                annotation.tags(),
                annotation.version(),
                paramName,
                expectedType,
                annotation.schemaMode(),
                annotation.required()
            );
        }

        /**
         * Create list from @MeshRoute annotation.
         */
        public static List<DependencySpec> fromAnnotation(MeshRoute annotation) {
            List<DependencySpec> specs = new ArrayList<>();
            for (MeshDependency dep : annotation.dependencies()) {
                specs.add(fromAnnotation(dep));
            }
            return specs;
        }

        public String getCapability() {
            return capability;
        }

        public String[] getTags() {
            return tags;
        }

        public String getVersion() {
            return version;
        }

        public String getParameterName() {
            return parameterName;
        }

        /**
         * Optional expected response type for schema-aware capability matching (issue #547).
         *
         * @return the type from {@link MeshDependency#expectedType()}, or null if not set
         */
        public Class<?> getExpectedType() {
            return expectedType;
        }

        /**
         * Schema match mode for this dependency (issue #547).
         *
         * @return the mode (defaults to {@link SchemaMode#NONE})
         */
        public SchemaMode getSchemaMode() {
            return schemaMode;
        }

        /**
         * Whether this route dependency is required (issue #1249). When true,
         * the route perimeter returns 503 before user code if the dependency's
         * proxy is unavailable at call time.
         *
         * @return true if the source {@link MeshDependency#required()} was set
         */
        public boolean isRequired() {
            return required;
        }

        /**
         * Promote this route dependency to required=true (cross-source
         * required-wins, 2.8.1). Only ever flips false→true — a source that
         * declares required wins over one that does not, and no source can
         * downgrade an already-required edge. The request-time 503 perimeter
         * ({@link MeshRouteHandlerInterceptor}) reads {@link #isRequired()}
         * live, so this keeps the perimeter aligned with the merged agent-spec
         * wire advertisement.
         */
        public void setRequired(boolean required) {
            this.required = required;
        }

        public Type getReturnType() { return returnType; }

        public void setReturnType(Type returnType) { this.returnType = returnType; }

        public boolean hasTags() {
            return tags != null && tags.length > 0;
        }

        public boolean hasVersion() {
            return version != null && !version.isEmpty();
        }

        @Override
        public String toString() {
            StringBuilder sb = new StringBuilder(capability);
            if (hasTags()) {
                sb.append(Arrays.toString(tags));
            }
            if (hasVersion()) {
                sb.append("@").append(version);
            }
            return sb.toString();
        }

        private static String toCamelCase(String kebab) {
            if (!kebab.contains("-")) {
                return kebab;
            }
            StringBuilder result = new StringBuilder();
            boolean capitalizeNext = false;
            for (char c : kebab.toCharArray()) {
                if (c == '-') {
                    capitalizeNext = true;
                } else if (capitalizeNext) {
                    result.append(Character.toUpperCase(c));
                    capitalizeNext = false;
                } else {
                    result.append(c);
                }
            }
            return result.toString();
        }
    }
}
