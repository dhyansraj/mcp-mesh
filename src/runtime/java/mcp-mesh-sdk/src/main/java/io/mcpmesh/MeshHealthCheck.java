package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as this agent's health check (issue #1474).
 *
 * <p>The starter runs the annotated method on a timer and does two things with
 * the verdict:
 *
 * <ol>
 *   <li>serves it from {@code /health} (with per-check detail) and {@code /ready};</li>
 *   <li>reports it to the mesh runtime. While the verdict is
 *       {@link MeshHealthStatus#UNHEALTHY} the runtime <b>stops heartbeating</b>,
 *       the registry's staleness sweep withdraws the agent, and dependency
 *       resolution moves consumers to another provider. When the check passes
 *       again the heartbeat resumes and the registry restores the agent —
 *       with no process restart.</li>
 * </ol>
 *
 * <p>This is what lets a provider whose upstream vendor is down take itself out
 * of rotation instead of accepting calls it cannot serve.
 *
 * <h2>Shape</h2>
 *
 * <p>Annotate exactly one no-argument method on a Spring bean. The return type
 * must be either {@link MeshHealth} (full detail) or {@code boolean} (terse:
 * {@code true} = healthy, {@code false} = unhealthy). Anything else fails the
 * boot with an actionable message rather than being silently ignored.
 *
 * <p>Escaped as {@code &#64;} rather than wrapped in {@code {@code ...}}: an
 * annotation is the first token on those lines, and Javadoc reads a leading
 * {@code @} as a block tag even inside a code block — which would silently
 * truncate this description at the first sample line.
 *
 * <pre>
 * &#64;Component
 * public class VendorHealth {
 *
 *     &#64;MeshHealthCheck(ttlSeconds = 30)
 *     public MeshHealth check() {
 *         if (!vendorReachable()) {
 *             return MeshHealth.unhealthy("anthropic API unreachable")
 *                 .withCheck("anthropic_api_reachable", false);
 *         }
 *         return MeshHealth.healthy().withCheck("anthropic_api_reachable", true);
 *     }
 * }
 * </pre>
 *
 * <h2>Only an explicit unhealthy verdict withdraws the agent</h2>
 *
 * <p>A check that <b>throws</b> is recorded as {@link MeshHealthStatus#DEGRADED},
 * not unhealthy, so it keeps heartbeating. A buggy health check must not be able
 * to remove a working agent from the mesh. Return {@code false} or
 * {@link MeshHealth#unhealthy} to actually withdraw.
 *
 * <h2>Route and A2A agents</h2>
 *
 * <p>The hook works the same way on an {@code api} (route-only) or {@code a2a}
 * agent: an <b>unhealthy verdict</b> pauses the heartbeat there too (RFC #1502),
 * while a check that throws publishes {@link MeshHealthStatus#DEGRADED} and
 * keeps beating. It declares "I am not available" on every agent type, and mesh
 * does the same thing with it everywhere — it stops wiring that agent. What
 * differs is topology, not meaning: a provider is something others route
 * <i>to</i>, a gateway is where requests <i>enter</i>.
 *
 * <p>So a withdrawn gateway is not a gateway that went down. Suppressing the
 * heartbeat stops registry traffic only — the servlet container keeps serving,
 * resolved dependencies are retained, and {@code /ready} answers 200 whatever
 * the verdict, so the pod stays in its Service endpoints and keeps taking
 * ingress. It stops being <i>discovered</i>.
 *
 * @see MeshHealth
 * @see MeshHealthStatus
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface MeshHealthCheck {

    /**
     * How often the check is re-run, in seconds.
     *
     * <p>Mirrors Python's {@code health_check_ttl}, and the same default (15).
     * This is the <b>cadence</b>, not the end-to-end latency: withdrawal costs
     * up to one TTL plus the registry's staleness window once heartbeats stop,
     * and recovery costs up to one TTL plus the heartbeat resume and
     * re-register round trip.
     *
     * <p>Override with the {@code MCP_MESH_HEALTH_CHECK_TTL} environment
     * variable.
     */
    int ttlSeconds() default 15;
}
