package io.mcpmesh.a2a;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a {@link MeshTool}-annotated method as an A2A consumer bridge.
 *
 * <p>Pure marker — the annotation itself carries no fields. Its sole
 * purpose is to opt the surrounding tool into the consumer-name
 * auto-tag injection path: at agent registration time the Spring
 * starter rewrites the tool's tag list to include the surrounding
 * {@link MeshAgent#name()}, making the bridged capability
 * distinguishable from sibling consumers (and pinnable from downstream
 * dependencies via the consumer name).
 *
 * <p>Mirrors the Python runtime's {@code @mesh.a2a_consumer} surface
 * (issue #908), which auto-tags via the
 * {@code __MESH_CONSUMER_SELF__} sentinel substitution. Java keeps the
 * relationship explicit: the user constructs an {@link A2AClient}
 * inside the method body and places this annotation alongside
 * {@link MeshTool} so the post-processor knows to inject the auto-tag.
 *
 * <h2>Pattern</h2>
 * <pre>{@code
 * private static final A2AClient CLIENT = new A2AClient(
 *     "http://upstream.example.com/agents/date", "get-date");
 *
 * @MeshTool(capability = "current-date", tags = {"a2a-bridge"})
 * @A2AConsumer
 * public Map<String, Object> currentDate() throws Exception {
 *     A2AResponse r = CLIENT.send(Map.of(
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
 *   <li>The surrounding agent must declare {@link MeshAgent#name()}
 *       (or its env-var override) so the auto-tag has a value to
 *       substitute. A consumer-only / nameless agent skips the
 *       injection cleanly with a warning.</li>
 * </ul>
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface A2AConsumer {
}
