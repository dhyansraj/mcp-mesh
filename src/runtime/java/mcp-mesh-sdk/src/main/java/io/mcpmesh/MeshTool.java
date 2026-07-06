package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as an MCP Mesh tool/capability.
 *
 * <p>Methods annotated with {@code @MeshTool} are registered as capabilities
 * with the mesh registry and can be called by other agents in the mesh.
 *
 * <h2>Basic Example</h2>
 * <pre>{@code
 * @MeshTool(
 *     capability = "greeting",
 *     description = "Greet a user by name"
 * )
 * public String greet(@Param("name") String name) {
 *     return "Hello, " + name + "!";
 * }
 * }</pre>
 *
 * <h2>With Dependencies</h2>
 * <pre>{@code
 * @MeshTool(
 *     capability = "smart_greeting",
 *     description = "Enhanced greeting with current date",
 *     dependencies = @Selector(capability = "date_service")
 * )
 * public String smartGreet(
 *     @Param("name") String name,
 *     McpMeshTool dateService  // Injected by mesh
 * ) {
 *     if (dateService != null) {
 *         String today = dateService.call("format", "long");
 *         return String.format("Hello, %s! Today is %s", name, today);
 *     }
 *     return String.format("Hello, %s!", name);
 * }
 * }</pre>
 *
 * <h2>With OR Tag Alternatives (Polyglot)</h2>
 * <pre>{@code
 * @MeshTool(
 *     capability = "calculator",
 *     tags = {"math", "calculator"},
 *     dependencies = @Selector(
 *         capability = "math_ops",
 *         tags = {"addition", "(python|+typescript)"}  // Try Python, prefer TypeScript
 *     )
 * )
 * public int calculate(int a, int b, McpMeshTool mathOps) {
 *     return mathOps.call("a", a, "b", b);
 * }
 * }</pre>
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface MeshTool {

    /**
     * Capability name for discovery.
     *
     * <p>This is the name other agents use to find and depend on this tool.
     */
    String capability();

    /**
     * Human-readable description of the tool.
     */
    String description() default "";

    /**
     * Capability version (semver format).
     */
    String version() default "1.0.0";

    /**
     * Tags for filtering.
     *
     * <p>Supports tag operators:
     * <ul>
     *   <li>{@code "tag"} - Required tag</li>
     *   <li>{@code "+tag"} - Preferred tag (bonus score)</li>
     *   <li>{@code "-tag"} - Excluded tag (hard fail)</li>
     *   <li>{@code "(a|b)"} - OR alternatives (try in order)</li>
     *   <li>{@code "(a|+b)"} - OR with preference</li>
     * </ul>
     */
    String[] tags() default {};

    /**
     * Dependencies required by this tool.
     *
     * <p>Each dependency is resolved at runtime and injected as a
     * {@code McpMeshTool} parameter. If a dependency is unavailable,
     * the parameter will be {@code null} (graceful degradation).
     */
    Selector[] dependencies() default {};

    /**
     * Optional output schema type for capability matching (issue #547).
     *
     * <p>Java cannot reliably infer return-type schemas from method signatures
     * (generics erasure, polymorphism), so users opt in by pointing to the
     * concrete class. The class is run through victools/jsonschema-generator,
     * normalized via the Rust normalizer, and shipped to the registry alongside
     * the input schema. Consumers using {@code @MeshDependency(expectedType=...)}
     * can then be matched against this output schema.
     *
     * <p>Default {@code Void.class} means "not set" — backward-compatible with
     * existing tools that don't ship an output schema.
     *
     * <p>Example:
     * <pre>{@code
     * @MeshTool(capability = "lookup_employee", outputType = Employee.class)
     * public Employee lookupEmployee(@Param("id") String id) { ... }
     * }</pre>
     */
    Class<?> outputType() default Void.class;

    /**
     * Per-tool override for the schema verdict policy (issue #547 Phase 4).
     *
     * <p>When {@code true} (default), a BLOCK verdict from the schema normalizer
     * refuses agent startup. Set to {@code false} as a producer-side escape
     * hatch to demote BLOCK to WARN for this specific tool. Wins even when
     * the cluster-wide {@code MCP_MESH_SCHEMA_STRICT=true} env var is set
     * (which otherwise promotes WARN to BLOCK across all tools).
     *
     * <p>Example:
     * <pre>{@code
     * @MeshTool(capability = "experimental_tool", outputSchemaStrict = false)
     * public Object experimental(...) { ... }
     * }</pre>
     */
    boolean outputSchemaStrict() default true;

    /**
     * Marks this tool as a long-running <b>task</b> (MeshJob).
     *
     * <p>When {@code true}, the runtime treats this method as a producer for
     * the MeshJob substrate (Phase 1 — see {@code MESHJOB_DESIGN.org}):
     * <ul>
     *   <li>Inbound HTTP calls bearing an {@code X-Mesh-Job-Id} header dispatch
     *       through the job pipeline, with a {@link MeshJob}-typed parameter
     *       receiving an injected {@code JobController} for progress / result /
     *       failure reporting.</li>
     *   <li>Pull-mode workers can claim queued jobs for this capability via
     *       {@code POST /jobs/claim} when the registry's
     *       {@code X-Mesh-Pending-Jobs} header signals work.</li>
     *   <li>The capability is advertised to the registry with the
     *       {@code task} attribute so consumers depending on it receive a
     *       {@code MeshJobSubmitter} (rather than the synchronous
     *       {@code McpMeshTool} proxy) via DDDI.</li>
     * </ul>
     *
     * <p>The method MUST also declare exactly one {@link MeshJob} parameter (per
     * {@code MESHJOB_DDDI_CONTRACT.md}); the resolver rejects multiple. The
     * parameter may legitimately receive {@code null} when the tool is called
     * synchronously via the regular {@code tools/call} fast path — user code
     * must tolerate that.
     *
     * <p>Default {@code false} preserves existing tool semantics.
     *
     * <p>Example:
     * <pre>{@code
     * @MeshTool(capability = "plan_trip", task = true)
     * public CompletableFuture<TripPlan> planTrip(
     *     @Param("user_id") String userId,
     *     MeshJob job
     * ) {
     *     if (job instanceof JobController c) c.updateProgress(0.25, "...");
     *     return CompletableFuture.completedFuture(...);
     * }
     * }</pre>
     */
    boolean task() default false;

    /**
     * Issue #1277: opt in to <b>cursor resume</b> for a reclaimed job.
     *
     * <p>By default a job that is reclaimed by a peer replica (owner change,
     * lease expiry, drain) gets a fresh {@link JobController} whose
     * {@link JobController#recvEvent(java.util.List, java.time.Duration)}
     * cursor starts at seq 0 — the handler <em>replays</em> the whole event
     * log from the beginning. When {@code resumeCursor = true}, the dispatcher
     * seeds the reclaimed controller from the {@code recv_cursor} the registry
     * persisted for the claim, so {@code recvEvent} resumes from the last
     * consumed sequence instead of replaying.
     *
     * <p>Constraints (validated at registration via
     * {@link io.mcpmesh.spring.MeshToolBeanPostProcessor}):
     * <ul>
     *   <li>requires {@code task = true} — non-task tools have no controller,
     *       so a resume cursor has no meaning;
     *   <li>the handler MUST consume events strictly sequentially per filter.
     *       A handler that prefetches (reads ahead of the work it has actually
     *       committed) MUST NOT enable this — on resume it would skip the
     *       prefetched-but-unprocessed events. Replay-from-0 (the default) is
     *       the safe choice for such handlers.
     * </ul>
     *
     * <p>Default {@code false} preserves the replay-from-0 semantics.
     *
     * @return {@code true} to resume {@code recvEvent} from the persisted
     *         cursor on reclaim; {@code false} (default) to replay from seq 0.
     */
    boolean resumeCursor() default false;

    /**
     * Issue #895: per-tool retry-eligible exception whitelist.
     *
     * <p>When a {@code task = true} handler raises a {@link Throwable} whose
     * class is a subtype of one of the entries (checked via
     * {@code cls.isInstance(thrown)}), the dispatch wrapper calls
     * {@code JobController.releaseLease(reason)} instead of
     * {@code JobController.fail(reason)}. The registry then resets
     * {@code owner_instance_id} so a peer replica can re-claim within ~5s
     * — useful for transient failures (network blips, upstream
     * unavailable) where the next attempt on a different replica is
     * likely to succeed.
     *
     * <p>Constraints (validated at registration via the bean
     * post-processor, see {@link io.mcpmesh.spring.MeshToolBeanPostProcessor}):
     * <ul>
     *   <li>requires {@code task = true} — synchronous tools have no
     *       controller, so retry has no meaning;
     *   <li>entries must be {@link Throwable} subclasses (the annotation
     *       processor enforces this via {@code Class<? extends Throwable>}).
     * </ul>
     *
     * <p>Default: empty array (no retry-eligible exceptions; all raises
     * mark the row failed via the existing {@code controller.fail()}
     * behaviour).
     *
     * @return the set of {@link Throwable} subclasses that trigger
     *         release-and-retry on raise.
     */
    Class<? extends Throwable>[] retryOn() default {};
}
