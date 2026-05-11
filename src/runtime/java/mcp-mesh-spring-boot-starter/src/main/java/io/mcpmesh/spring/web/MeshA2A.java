package io.mcpmesh.spring.web;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as an A2A (Agent-to-Agent) producer surface. The framework
 * mounts a JSON-RPC 2.0 entry point at {@code POST {path}} and an A2A v1.0
 * AgentCard at {@code GET {path}/.well-known/agent.json}, dispatching to the
 * annotated method whenever a client sends a {@code tasks/send} (Phase 1A
 * scope) or — once Chunk 1B lands — any other {@code tasks/*} verb.
 *
 * <p>This annotation is the Spring equivalent of Python's {@code @mesh.a2a}
 * decorator + {@code mesh.a2a.mount(app, path=...)} call. It carries the
 * skill-level metadata that the framework projects onto:
 * <ol>
 *   <li>the heartbeat {@code a2a_surfaces[]} array (registry registration,
 *       per spec §2 / §8);</li>
 *   <li>the agent card returned from {@code .well-known/agent.json}
 *       (per spec §3); and</li>
 *   <li>the JSON-RPC dispatch table that handles {@code tasks/*} verbs at
 *       {@code POST {path}} (per spec §4).</li>
 * </ol>
 *
 * <p>The annotated method is invoked with the A2A {@code message} object
 * already extracted from {@code params.message}. Return values are wrapped
 * as a single text-part artifact on a {@code state=completed} Task envelope.
 * Thrown exceptions become {@code state=failed} Tasks per the A2A v1.0 spec
 * (handler exceptions are NEVER JSON-RPC errors — JSON-RPC errors are
 * reserved for protocol-level issues).
 *
 * <h2>Example Usage</h2>
 *
 * <pre>{@code
 * @Component
 * public class DateAgent {
 *
 *     @MeshA2A(
 *         path = "/agents/date",
 *         skillId = "current-date",
 *         skillName = "Current Date",
 *         description = "Returns the current UTC date in ISO-8601 form",
 *         tags = {"date", "v1"}
 *     )
 *     public Map<String, Object> currentDate(Map<String, Object> message) {
 *         return Map.of("date", java.time.Instant.now().toString());
 *     }
 * }
 * }</pre>
 *
 * <h3>With mesh dependency injection</h3>
 *
 * <p>{@link MeshDependency} entries declared on the annotation are resolved
 * by the same {@link io.mcpmesh.spring.MeshDependencyInjector} that powers
 * {@code @MeshRoute}. Inject the resolved {@link io.mcpmesh.types.McpMeshTool}
 * via {@link MeshInject} on a method parameter:
 *
 * <pre>{@code
 * @MeshA2A(
 *     path = "/agents/report-generator",
 *     skillId = "generate-report",
 *     skillName = "Report Generator",
 *     description = "Generates a long-form report from structured input",
 *     dependencies = {
 *         @MeshDependency(capability = "outline-tool"),
 *         @MeshDependency(capability = "writer-tool", tags = "+premium")
 *     }
 * )
 * public Map<String, Object> generateReport(
 *         Map<String, Object> message,
 *         @MeshInject("outline-tool") McpMeshTool outline,
 *         @MeshInject("writer-tool") McpMeshTool writer) {
 *     Map<String, Object> outlineResult = outline.call(message);
 *     return writer.call(outlineResult);
 * }
 * }</pre>
 *
 * <h3>Bearer-token gate</h3>
 *
 * <p>Setting {@link #auth()} to {@code "bearer"} enables a header-presence
 * gate on the {@code POST {path}} entry point. The agent card endpoint is
 * always reachable without authentication so external clients can discover
 * the scheme. Phase 1 only checks header presence; token-value validation
 * (signature, issuer, audience) is Phase 2+ scope.
 *
 * <pre>{@code
 * @MeshA2A(
 *     path = "/agents/private",
 *     skillId = "internal-report",
 *     skillName = "Internal Report",
 *     auth = "bearer"
 * )
 * public Map<String, Object> privateReport(Map<String, Object> message) { ... }
 * }</pre>
 *
 * <h2>Registry registration</h2>
 *
 * <p>When this Spring Boot app heartbeats to the mesh registry, the
 * presence of at least one {@code @MeshA2A} method flips {@code agent_type}
 * to {@code "a2a"} and emits an {@code a2a_surfaces[]} array with one
 * entry per surface. The registry stamps a public FQDN onto each surface
 * (when {@code MCP_MESH_PUBLIC_URL_PREFIX} is configured) so external
 * A2A clients can discover the agent via {@code GET /a2a/agents}.
 *
 * @see MeshDependency
 * @see MeshInject
 * @see MeshRoute
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface MeshA2A {

    /**
     * URL path prefix for this A2A surface. Required.
     *
     * <p>The framework mounts the JSON-RPC entry point at {@code POST {path}}
     * and the agent card at {@code GET {path}/.well-known/agent.json}. Must
     * start with {@code /}. Example: {@code "/agents/report-generator"}.
     *
     * @return the path prefix
     */
    String path();

    /**
     * A2A skill identifier (kebab-case canonical). Required.
     *
     * <p>This is the {@code skill_id} surfaced on the registry's
     * {@code a2a_surfaces[]} array and the {@code skills[0].id} field on
     * the agent card. Example: {@code "generate-report"}.
     *
     * @return the skill id
     */
    String skillId();

    /**
     * Human-readable skill name surfaced on the agent card. Required.
     *
     * <p>Becomes the {@code skills[0].name} field on the agent card and the
     * {@code name} field on the {@code a2a_surfaces[]} entry.
     *
     * @return the skill display name
     */
    String skillName();

    /**
     * Optional free-form skill description.
     *
     * <p>Surfaces on the agent card as {@code skills[0].description} and on
     * the {@code a2a_surfaces[]} entry as {@code description}. Defaults to
     * {@link #skillName()} on the card when blank.
     *
     * @return the skill description
     */
    String description() default "";

    /**
     * Optional tags for this skill. Surfaced verbatim on the agent card
     * as {@code skills[0].tags} and on the {@code a2a_surfaces[]} entry
     * as {@code tags}.
     *
     * @return the skill tags
     */
    String[] tags() default {};

    /**
     * Mesh dependencies to inject when the handler is invoked.
     *
     * <p>Each entry is resolved from the mesh registry by capability; the
     * resolved {@link io.mcpmesh.types.McpMeshTool} proxy is made available
     * to the handler via {@link MeshInject} parameter injection. Mirrors
     * {@link MeshRoute#dependencies()}.
     *
     * @return the array of mesh dependencies
     */
    MeshDependency[] dependencies() default {};

    /**
     * Optional authentication scheme. Either {@code ""} (no gate, default)
     * or {@code "bearer"} (Phase 1: header-presence check only).
     *
     * <p>Per spec §6, when set to {@code "bearer"} the producer:
     * <ul>
     *   <li>advertises {@code authentication.schemes = ["bearer"]} on the
     *       agent card;</li>
     *   <li>rejects any {@code POST {path}} request with a missing,
     *       non-{@code Bearer}, or empty-token {@code Authorization} header
     *       with HTTP 401 + JSON-RPC error code {@code -32001};</li>
     *   <li>does NOT validate the token value (signature/issuer/audience
     *       validation is Phase 2+).</li>
     * </ul>
     *
     * <p>When unset (the default), the agent card advertises an empty
     * {@code authentication.schemes} list (NOT {@code "none"} — A2A v1.0
     * has no such scheme) and the entry point is reachable without
     * authentication.
     *
     * @return {@code "bearer"} to enable the gate, {@code ""} otherwise
     */
    String auth() default "";
}
