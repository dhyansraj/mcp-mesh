package io.mcpmesh.spring.web;

import io.mcpmesh.core.AgentSpec;
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
                    specs.add(agentDep);
                }
            }
        }

        return specs;
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
        private Type returnType;  // Set by BeanPostProcessor after construction

        public DependencySpec(String capability, String[] tags, String version, String parameterName) {
            this.capability = capability;
            this.tags = tags != null ? tags : new String[0];
            this.version = version;
            this.parameterName = parameterName;
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
            return new DependencySpec(
                annotation.capability(),
                annotation.tags(),
                annotation.version(),
                paramName
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
