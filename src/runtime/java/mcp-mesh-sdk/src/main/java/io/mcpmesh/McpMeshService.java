package io.mcpmesh;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks an interface as a consumer-owned <b>service view</b>: a typed
 * aggregation of ordinary capability dependencies (RFC #1280).
 *
 * <p>Each abstract method of the interface binds exactly one capability via a
 * method-level {@link Selector}, and calling that method delegates to the
 * capability's own resolved proxy. Different methods may therefore resolve to
 * DIFFERENT provider agents and rebind independently as the mesh topology
 * changes — the group is a typed view, the capability remains the atom. There
 * are no wire or registry changes: every method is an ordinary dependency edge,
 * expanded into the agent's registration exactly like a {@code @MeshDependsOn}
 * dependency.
 *
 * <h2>Example</h2>
 * <pre>{@code
 * @McpMeshService
 * public interface LlmService {
 *     @Selector(capability = "llm.chat",   tags = {"+gpt"})                     ChatResult   chat(ChatRequest req);
 *     @Selector(capability = "llm.vision", tags = {"+claude"}, required = true) VisionResult vision(VisionRequest req);
 *     @Selector(capability = "llm.video",  tags = {"+gemini"})                  VideoResult  video(VideoRequest req);
 * }
 * }</pre>
 *
 * <p>The consumer {@code @Autowired}s {@code LlmService} and calls its methods
 * directly. A Spring bean (named by the decapitalized simple interface name) is
 * registered automatically.
 *
 * <h2>Method rules</h2>
 * <ul>
 *   <li>Every abstract method must carry {@link Selector} with a non-empty
 *       {@code capability}.</li>
 *   <li>Parameters follow the {@code @MeshTool} convention: 0 params → no-arg
 *       call; exactly 1 param without {@link Param} → single-POJO conversion;
 *       otherwise every param must carry {@code @Param("name")}.</li>
 *   <li>Return {@code T} → synchronous call, {@code CompletableFuture<T>} →
 *       async call, {@code java.util.concurrent.Flow.Publisher<String>} →
 *       streaming call.</li>
 *   <li>{@code default} / {@code static} interface methods are allowed and are
 *       NOT expanded as dependency edges.</li>
 * </ul>
 *
 * <p><b>Not a shared contract:</b> a service view is purely consumer-local.
 * There is no group versioning and no interface-level availability summary —
 * any scalar "is the view up?" would lie about partial availability, since each
 * method resolves independently.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface McpMeshService {

    /**
     * Opt-in availability floor. When fewer than {@code minAvailable} of the
     * view's methods currently resolve to a provider, EVERY facade call throws
     * {@link io.mcpmesh.types.MeshServiceUnavailableException} — a
     * consumer-local circuit breaker with no wire effect.
     *
     * <p>Default {@code 0} means "no floor": each method independently soft-
     * or hard-fails per its own {@link Selector#required()} flag, exactly like
     * a directly-injected {@code McpMeshTool}.
     */
    int minAvailable() default 0;
}
