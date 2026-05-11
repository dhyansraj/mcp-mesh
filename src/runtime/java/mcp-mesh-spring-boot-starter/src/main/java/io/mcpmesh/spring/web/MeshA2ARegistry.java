package io.mcpmesh.spring.web;

import io.mcpmesh.core.AgentSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry for {@code @MeshA2A} annotated methods discovered during bean
 * post-processing.
 *
 * <p>The registry maps each producer path to the surface metadata captured
 * from the annotation, plus a reference to the bean+method that handles
 * {@code tasks/send}. Consulted by:
 *
 * <ul>
 *   <li>{@link MeshA2ADispatcher} — to locate the handler for an incoming
 *       JSON-RPC request at {@code POST {path}}.</li>
 *   <li>{@link MeshA2ACardBuilder} — to render the {@code .well-known/agent.json}
 *       card for {@code GET {path}/.well-known/agent.json}.</li>
 *   <li>{@link MeshA2AAuthFilter} — to look up the {@code auth} setting for
 *       a candidate path.</li>
 *   <li>{@code MeshAutoConfiguration} — to enumerate all surfaces when
 *       building the heartbeat {@code a2a_surfaces[]} array (spec §2 / §8).</li>
 * </ul>
 *
 * <p>Mirrors the role of {@link MeshRouteRegistry} on the {@code @MeshRoute}
 * side: built at bean-post-processing time, immutable from the user's
 * perspective afterwards, queried during request dispatch.
 */
public class MeshA2ARegistry {

    private static final Logger log = LoggerFactory.getLogger(MeshA2ARegistry.class);

    /**
     * Surfaces indexed by the producer's {@code path} (e.g.,
     * {@code "/agents/date"}). Insertion order is preserved to keep
     * heartbeat envelope ordering stable across restarts.
     */
    private final Map<String, SurfaceMetadata> surfaces = new ConcurrentHashMap<>();

    /**
     * Insertion-ordered list mirror — {@link ConcurrentHashMap} doesn't
     * preserve order, so we keep a parallel list for deterministic iteration
     * when building the heartbeat envelope.
     */
    private final List<String> orderedPaths = Collections.synchronizedList(new ArrayList<>());

    /**
     * Register a {@code @MeshA2A} surface.
     *
     * @param metadata the captured surface metadata
     */
    public void register(SurfaceMetadata metadata) {
        SurfaceMetadata previous = surfaces.putIfAbsent(metadata.path(), metadata);
        if (previous != null) {
            throw new IllegalStateException(
                "@MeshA2A path collision: '" + metadata.path() + "' is already registered "
                    + "by " + previous.handlerMethodId() + ". Each producer path must be unique.");
        }
        orderedPaths.add(metadata.path());
        log.info("Registered @MeshA2A surface: path={} skillId={} dependencies={}",
            metadata.path(), metadata.skillId(), metadata.dependencies().size());
    }

    /**
     * Look up a surface by its path.
     *
     * @param path the {@code @MeshA2A.path()} value
     * @return the metadata, or {@code null} when no surface owns that path
     */
    public SurfaceMetadata getByPath(String path) {
        return surfaces.get(path);
    }

    /**
     * @return read-only view of every registered surface in insertion order.
     */
    public List<SurfaceMetadata> getAllSurfaces() {
        List<SurfaceMetadata> ordered = new ArrayList<>(orderedPaths.size());
        synchronized (orderedPaths) {
            for (String path : orderedPaths) {
                SurfaceMetadata md = surfaces.get(path);
                if (md != null) {
                    ordered.add(md);
                }
            }
        }
        return Collections.unmodifiableList(ordered);
    }

    /**
     * Read-only view of the path → metadata map. Provided for diagnostics.
     */
    public Collection<SurfaceMetadata> getMetadataCollection() {
        return Collections.unmodifiableCollection(surfaces.values());
    }

    /**
     * @return {@code true} when at least one {@code @MeshA2A} surface is
     *     registered. Used by the heartbeat envelope builder to decide
     *     whether to flip {@code agent_type} to {@code "a2a"}.
     */
    public boolean hasSurfaces() {
        return !surfaces.isEmpty();
    }

    public int size() {
        return surfaces.size();
    }

    /**
     * Collect the unique dependency capabilities across every registered
     * {@code @MeshA2A} surface and project them onto
     * {@link AgentSpec.DependencySpec} entries for the registry's
     * resolution mechanism. Deduplication is on capability name — first
     * occurrence wins (tag/version refinements on later occurrences are
     * dropped, matching the route-registry behaviour).
     *
     * <p>The returned specs are folded into a synthetic
     * {@code __mesh_a2a_deps} tool on the heartbeat envelope (built by
     * {@code MeshAutoConfiguration}) so the Rust core can drive
     * {@code dependency_available} events for them — the same mechanism
     * that powers {@code @MeshRoute} dependency wiring.
     */
    public List<AgentSpec.DependencySpec> getUniqueDependencySpecs() {
        Set<String> seenCapabilities = new HashSet<>();
        List<AgentSpec.DependencySpec> specs = new ArrayList<>();
        for (SurfaceMetadata surface : getAllSurfaces()) {
            for (MeshRouteRegistry.DependencySpec dep : surface.dependencies()) {
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

    /**
     * Captured metadata for a single {@code @MeshA2A} method.
     *
     * <p>Constructed once at bean-post-processing time and immutable
     * thereafter — the {@link MeshA2ADispatcher} reads
     * {@link #bean()}/{@link #method()} via reflection on every request.
     *
     * @param path               the URL path prefix for this surface
     * @param skillId            the A2A skill id (kebab-case)
     * @param skillName          the human-readable skill name
     * @param description        free-form skill description ({@code ""} when unset)
     * @param tags               skill tags (empty list when unset)
     * @param dependencies       declared mesh dependencies, in source order
     * @param auth               {@code "bearer"} or {@code ""}
     * @param handlerMethodId    {@code "ClassName.methodName"} identifier for
     *                           logs and registry lookup
     * @param bean               the Spring bean carrying the handler method
     * @param method             the handler method itself
     */
    public record SurfaceMetadata(
        String path,
        String skillId,
        String skillName,
        String description,
        List<String> tags,
        List<MeshRouteRegistry.DependencySpec> dependencies,
        String auth,
        String handlerMethodId,
        Object bean,
        Method method
    ) {
        public SurfaceMetadata {
            if (path == null || path.isEmpty()) {
                throw new IllegalArgumentException("@MeshA2A.path() must be non-empty");
            }
            if (!path.startsWith("/")) {
                throw new IllegalArgumentException(
                    "@MeshA2A.path() must start with '/': got '" + path + "'");
            }
            if (skillId == null || skillId.isEmpty()) {
                throw new IllegalArgumentException("@MeshA2A.skillId() must be non-empty");
            }
            if (skillName == null || skillName.isEmpty()) {
                throw new IllegalArgumentException("@MeshA2A.skillName() must be non-empty");
            }
            // Normalize trailing slash so path collisions are unambiguous
            // ("/agents/x/" and "/agents/x" must not co-exist).
            if (path.length() > 1 && path.endsWith("/")) {
                throw new IllegalArgumentException(
                    "@MeshA2A.path() must not end with '/': got '" + path + "'");
            }
            tags = tags == null ? List.of() : List.copyOf(tags);
            dependencies = dependencies == null ? List.of() : List.copyOf(dependencies);
            description = description == null ? "" : description;
            auth = auth == null ? "" : auth;
        }

        /** @return {@code true} when this surface declared {@code auth="bearer"}. */
        public boolean bearerAuth() {
            return "bearer".equals(auth);
        }
    }

    /**
     * Build the heartbeat {@code a2a_surfaces[]} array (spec §2.1).
     *
     * <p>Each registered surface produces one entry. Required fields
     * ({@code path}, {@code skill_id}) are always emitted. Optional fields
     * ({@code name}, {@code description}, {@code tags}) are emitted ONLY
     * when set on the annotation, never as empty strings or empty arrays —
     * spec §2.1 is explicit about this so the registry's OpenAPI defaults
     * (e.g., {@code input_modes: ["application/json"]}) aren't overridden
     * with empty values.
     *
     * @return list of plain-Map surfaces ready for JSON serialization
     */
    public List<Map<String, Object>> buildHeartbeatSurfaces() {
        List<SurfaceMetadata> all = getAllSurfaces();
        if (all.isEmpty()) {
            return List.of();
        }
        List<Map<String, Object>> out = new ArrayList<>(all.size());
        for (SurfaceMetadata md : all) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("path", md.path());
            entry.put("skill_id", md.skillId());
            // skill_name is always present on @MeshA2A (required annotation
            // field), so we always emit `name`. Python's
            // collect_a2a_surfaces emits it only when set; on the Java
            // annotation it's mandatory so absence is impossible.
            entry.put("name", md.skillName());
            if (md.description() != null && !md.description().isEmpty()) {
                entry.put("description", md.description());
            }
            if (!md.tags().isEmpty()) {
                entry.put("tags", new ArrayList<>(md.tags()));
            }
            // input_modes / output_modes default at card-render time, not at
            // heartbeat-emit time. Java's @MeshA2A doesn't expose them yet
            // (mirrors Python's decorator), so we omit them here.
            out.add(entry);
        }
        return out;
    }
}
