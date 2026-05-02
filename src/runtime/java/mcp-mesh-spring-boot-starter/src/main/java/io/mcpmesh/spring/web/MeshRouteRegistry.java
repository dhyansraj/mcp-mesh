package io.mcpmesh.spring.web;

import io.mcpmesh.SchemaMode;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshCoreBridge;
import io.mcpmesh.spring.MeshSchemaSupport;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
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
        Set<String> seenCapabilities = new HashSet<>();
        List<AgentSpec.DependencySpec> specs = new ArrayList<>();
        // Issue #547 Phase 4: cluster-wide strict knob promotes WARN→BLOCK.
        boolean clusterStrict = MeshSchemaSupport.clusterStrictEnabled();

        for (RouteMetadata route : routesByPath.values()) {
            for (DependencySpec dep : route.getDependencies()) {
                if (seenCapabilities.add(dep.getCapability())) {
                    AgentSpec.DependencySpec agentDep = new AgentSpec.DependencySpec();
                    agentDep.setCapability(dep.getCapability());
                    if (dep.hasTags()) {
                        agentDep.setTags(String.join(",", dep.getTags()));
                    }
                    if (dep.hasVersion()) {
                        agentDep.setVersion(dep.getVersion());
                    }
                    applySchemaMatching(agentDep, dep, clusterStrict);
                    specs.add(agentDep);
                }
            }
        }

        return specs;
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
     */
    private static void applySchemaMatching(
            AgentSpec.DependencySpec target, DependencySpec source, boolean clusterStrict) {
        Class<?> expectedType = source.getExpectedType();
        SchemaMode mode = source.getSchemaMode();
        boolean modeRequested = mode != null && mode != SchemaMode.NONE;

        if (expectedType == null && !modeRequested) {
            return; // backward-compatible: nothing to do
        }
        if (expectedType == null) {
            log.warn("Dependency '{}' sets schemaMode={} but no expectedType — ignoring schema match",
                source.getCapability(), mode);
            return;
        }
        // Default mode SUBSET when caller provides expectedType only (parity with Python).
        SchemaMode effectiveMode = modeRequested ? mode : SchemaMode.SUBSET;

        String rawJson = MeshSchemaSupport.generateRawSchemaJson(expectedType);
        if (rawJson == null) {
            log.warn("Dependency '{}': failed to generate JSON Schema for expectedType {} — skipping schema match",
                source.getCapability(), expectedType.getName());
            return;
        }
        MeshCoreBridge.NormalizeResult result = MeshSchemaSupport.normalizeWithPolicy(
            rawJson, "java", "dependency '" + source.getCapability() + "' expected schema",
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
        private Type returnType;  // Set by BeanPostProcessor after construction

        public DependencySpec(String capability, String[] tags, String version, String parameterName) {
            this(capability, tags, version, parameterName, null, SchemaMode.NONE);
        }

        public DependencySpec(String capability, String[] tags, String version, String parameterName,
                              Class<?> expectedType, SchemaMode schemaMode) {
            this.capability = capability;
            this.tags = tags != null ? tags : new String[0];
            this.version = version;
            this.parameterName = parameterName;
            this.expectedType = expectedType;
            this.schemaMode = schemaMode != null ? schemaMode : SchemaMode.NONE;
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
                annotation.schemaMode()
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
