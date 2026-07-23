package io.mcpmesh.types;

/**
 * Shared vocabulary for the LLM exhaustion signal (issue #1355).
 *
 * <p>When a provider-managed agentic loop hits {@code max_iterations} it must
 * make the exhaustion <em>structurally</em> distinguishable so the delegating
 * consumer can raise a typed error instead of returning a fabricated answer.
 * Per the #1247 envelope contract, {@code content} is always the answer string
 * — the discriminant never lives inside it.
 *
 * <p>Interop with Python's {@code _mcp_mesh/engine/llm_stop_reason.py} and
 * TypeScript's {@code llm-stop-reason.ts} is by CONSTANT VALUE: a Java consumer
 * interoperates with a Python/TypeScript provider and vice versa because the
 * string tokens match exactly.
 *
 * <p><b>Buffered</b> reply envelope: a namespaced sibling field
 * {@code _mesh_stop_reason: "max_iterations"} (sibling of {@code content} /
 * {@code _mesh_usage}). Absent on normal completion.
 *
 * <p>The Java runtime has no provider-side streaming producer (deferred, see
 * #1223), so only the buffered vocabulary is defined here.
 */
public final class MeshLlmStopReason {

    private MeshLlmStopReason() {}

    /** Shared vocabulary token (kept identical to Python/TypeScript). */
    public static final String STOP_REASON_MAX_ITERATIONS = "max_iterations";

    /** Reserved sibling key on the buffered reply envelope. */
    public static final String STOP_REASON_KEY = "_mesh_stop_reason";
}
