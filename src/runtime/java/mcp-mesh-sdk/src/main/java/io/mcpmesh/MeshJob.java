package io.mcpmesh;

/**
 * Type marker for DDDI injection of a long-running job handle.
 *
 * <p>Mirrors the Python {@code MeshJob} Protocol and the TypeScript
 * {@code MeshJob} type marker. Application code declares a parameter of this
 * type to opt into job semantics; the runtime injects the appropriate
 * concrete implementation based on the call site:
 *
 * <ul>
 *   <li><b>Producer side</b> — a method annotated with
 *       {@code @MeshTool(task = true)} receives a {@code JobController} via
 *       this slot when invoked through the job-dispatch path
 *       ({@code X-Mesh-Job-Id} header present, or claimed from the pull
 *       queue). The user calls {@code updateProgress() / requestInput() /
 *       complete() / fail()} on it. {@code requestInput(prompt)} transitions
 *       the job to {@code input_required} (status-only; flushes immediately)
 *       so the handler can park on {@code recvEvent(List.of("answer"), ...)}
 *       for an external party to answer via
 *       {@code MeshJobs.postEvent(jobId, "answer", ...)}.</li>
 *   <li><b>Consumer side</b> — a method depending on a {@code task = true}
 *       capability receives a {@code MeshJobSubmitter} via this slot. The
 *       user calls {@code .submit(...)} on it to start a job and
 *       {@code .wait(...)} on the returned {@code JobProxy}.</li>
 *   <li><b>Fast-path call</b> — when a {@code task = true} tool is invoked
 *       as a regular synchronous {@code tools/call} (no job dispatch), the
 *       runtime injects {@code null} into this slot. User code MUST tolerate
 *       a {@code null} {@code MeshJob} parameter (typically by treating the
 *       call as a non-job execution that doesn't update progress).</li>
 * </ul>
 *
 * <p>See {@code MESHJOB_DDDI_CONTRACT.md} for the full DDDI resolver
 * contract that all three SDKs (Python, TypeScript, Java) share.
 *
 * <h2>Example — producer side</h2>
 * <pre>{@code
 * @MeshTool(capability = "plan_trip", task = true)
 * public CompletableFuture<TripPlan> planTrip(
 *     @Param("user_id") String userId,
 *     MeshJob job  // injected as JobController; null on non-job calls
 * ) {
 *     if (job instanceof JobController controller) {
 *         controller.updateProgress(0.25, "fetching weather");
 *         // ... long-running work ...
 *         controller.updateProgress(0.75, "scoring options");
 *     }
 *     return CompletableFuture.completedFuture(new TripPlan(...));
 * }
 * }</pre>
 *
 * <h2>Example — consumer side</h2>
 * <pre>{@code
 * @MeshTool(
 *     capability = "trip_planner_ui",
 *     dependencies = @Selector(capability = "plan_trip")
 * )
 * public TripPlan kickOffTrip(
 *     @Param("user_id") String userId,
 *     MeshJob planTripJob  // injected as MeshJobSubmitter
 * ) {
 *     if (planTripJob instanceof MeshJobSubmitter submitter) {
 *         JobProxy proxy = submitter.submit(Map.of("user_id", userId)).join();
 *         return (TripPlan) proxy.wait(60).join();
 *     }
 *     throw new IllegalStateException("plan_trip dependency unavailable");
 * }
 * }</pre>
 *
 * <p><b>One MeshJob per method</b> — the resolver rejects methods declaring
 * more than one {@code MeshJob} parameter. See
 * {@code MESHJOB_DDDI_CONTRACT.md} → "Multiple MeshJob parameters".
 */
public interface MeshJob {
    // Marker interface — runtime injects either JobController, JobProxy, or
    // MeshJobSubmitter depending on call-site context. May also be null for
    // a fast-path tools/call invocation on a task=true tool.
}
