package io.mcpmesh.a2a;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a {@link MeshTool}-annotated method as an A2A consumer bridge
 * AND carries the upstream A2A configuration.
 *
 * <p>The Spring starter reads these fields at boot, constructs an
 * {@link A2AClient} per unique {@code (url, skillId, auth, timeout)}
 * tuple, and injects the cached client at the method's
 * {@link A2AClient} parameter slot at invoke time. Mirrors Python's
 * {@code @mesh.a2a_consumer(url=..., a2a_skill_id=..., auth=...)}
 * decorator (issue #913) so Java, Python, and the upcoming TypeScript
 * implementation (#917) share the same framework-injection shape.
 *
 * <p>The marker also opts the surrounding tool into the consumer-name
 * auto-tag injection path: at agent registration time the starter
 * appends the surrounding {@link MeshAgent#name()} to the tool's tag
 * list, making the bridged capability distinguishable from sibling
 * consumers (and pinnable from downstream dependencies via the
 * consumer name).
 *
 * <h2>Pattern</h2>
 * <pre>{@code
 * @MeshTool(capability = "current-date", tags = {"a2a-bridge"})
 * @A2AConsumer(
 *     url = "http://upstream.example.com/agents/date",
 *     skillId = "get-date",
 *     authBearerEnv = "UPSTREAM_TOKEN",
 *     timeoutSeconds = 30
 * )
 * public Map<String, Object> currentDate(A2AClient a2a) throws Exception {
 *     A2AResponse r = a2a.send(Map.of(
 *         "role", "user",
 *         "parts", List.of(Map.of("type", "text", "text", "now"))));
 *     return new ObjectMapper().readValue(r.artifactText(), Map.class);
 * }
 * }</pre>
 *
 * <p>Usage rules:
 * <ul>
 *   <li>Must be combined with {@link MeshTool} on the same method —
 *       a bare {@code @A2AConsumer} on a non-mesh method is a no-op.</li>
 *   <li>The method MUST declare exactly one {@link A2AClient}
 *       parameter — the framework injects the cached client at that
 *       slot. Boot fails with a clear error otherwise.</li>
 *   <li>{@link #url()} is required. The marker-only form (predating
 *       issue #923) is rejected at boot with a migration message.</li>
 *   <li>{@link #url()} supports Spring property placeholders, e.g.
 *       {@code @A2AConsumer(url = "${weather.a2a.url}")}.</li>
 *   <li>{@link #authBearerEnv()} and {@link #authBearerToken()} are
 *       mutually exclusive — set zero or one, never both.</li>
 *   <li>The surrounding agent must declare {@link MeshAgent#name()}
 *       (or its env-var override) so the auto-tag has a value to
 *       substitute. A consumer-only / nameless agent skips the
 *       injection cleanly with a warning.</li>
 * </ul>
 *
 * <p><b>Lifecycle:</b> The framework owns the {@link A2AClient}'s
 * lifecycle. Do not retain references to the injected client across
 * Spring context shutdown — the framework's {@code @PreDestroy} hook
 * closes all cached clients and may run before any user
 * {@code @PreDestroy} that retained a reference. The injection is
 * scoped to the method invocation; let the framework manage construction
 * + close.
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface A2AConsumer {

    /**
     * Required: URL of the A2A endpoint to bridge.
     *
     * <p>Supports Spring property placeholders, e.g.
     * {@code "${weather.a2a.url}"}, resolved against the Spring
     * {@code Environment} at boot.
     *
     * <p>Defaults to {@code ""} so that class files compiled against the
     * pre-#923 marker-only annotation continue to load — the runtime
     * surfaces a clear migration error in
     * {@link io.mcpmesh.spring.A2AConsumerBeanPostProcessor} when the
     * resolved value is blank, instead of throwing an opaque
     * {@code IncompleteAnnotationException} at reflection time.
     */
    String url() default "";

    /**
     * Optional: A2A skill ID. Defaults to the surrounding
     * {@link MeshTool#capability()} when left empty.
     */
    String skillId() default "";

    /**
     * Optional: env-var name holding the bearer token for outbound
     * auth. Resolved per call (so a rotated credential is honoured
     * without restarting the agent). Mutually exclusive with
     * {@link #authBearerToken()}.
     */
    String authBearerEnv() default "";

    /**
     * Optional: explicit bearer token for outbound auth. Rarely used;
     * prefer {@link #authBearerEnv()} to avoid hardcoding credentials
     * in source. Mutually exclusive with {@link #authBearerEnv()}.
     */
    String authBearerToken() default "";

    /**
     * Optional: per-call deadline (seconds) on the constructed
     * {@link A2AClient}. Default 30. Must be {@code > 0}.
     */
    int timeoutSeconds() default 30;
}
