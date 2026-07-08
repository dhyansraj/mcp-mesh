package io.mcpmesh;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Two related roles depending on the annotated type (RFC #1280):
 *
 * <h2>On an INTERFACE — consumer-owned service view</h2>
 * A typed aggregation of ordinary capability dependencies.
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
 * @MeshService
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
 * <p><b>Scanning rule:</b> a scanned bean view requires {@code @MeshService}
 * <i>directly</i> on the interface. An interface that only INHERITS the
 * annotation from a super-interface is NOT auto-discovered as a bean view
 * (co-discovering it would always pull in the annotated parent too — duplicate
 * facades and parent-type injection ambiguity). Inherited-annotation interfaces
 * ARE usable as tool-parameter views (there the user names the type explicitly,
 * so there is no discovery ambiguity). When a view inherits from multiple
 * annotated parents, {@code minAvailable} is read from an arbitrary one of them;
 * declare it on the leaf interface if it matters.
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
 *
 * <p><b>Removed in 3.1:</b> the producer-on-class form
 * ({@code @MeshService("prefix")} on a {@code @Component} class, which
 * published {@code prefix.<methodName>} tools) was withdrawn — it derived the
 * wire capability from the method name, coupling the cross-runtime contract to a
 * language identifier, and could not express tags/version/dependencies. Using
 * {@link #value()} on a class now fast-fails at boot; declare each tool
 * explicitly with {@code @MeshTool(capability = "prefix.method")} instead.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface MeshService {

    /**
     * The capability-name prefix.
     *
     * <p><b>On a producer CLASS:</b> REMOVED in 3.1 — a non-blank value on a
     * class fast-fails at boot. Declare each tool explicitly with
     * {@code @MeshTool(capability = "prefix.method")}.
     *
     * <p><b>On a consumer INTERFACE (service view):</b> optional and currently
     * inert — reserved for future display grouping. Method capabilities on a
     * view come from each method's own {@link Selector}, not this prefix.
     */
    String value() default "";

    /**
     * Opt-in availability floor. When fewer than {@code minAvailable} of the
     * view's methods currently resolve to a provider, EVERY facade call throws
     * {@link io.mcpmesh.types.MeshServiceUnavailableException} — a
     * consumer-local circuit breaker with no wire effect.
     *
     * <p>Default {@code 0} means "no floor": each method independently soft-
     * or hard-fails per its own {@link Selector#required()} flag, exactly like
     * a directly-injected {@code McpMeshTool}.
     *
     * <p><b>Meaningful only on an interface (view).</b>
     */
    int minAvailable() default 0;
}
