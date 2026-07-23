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
 * <p>Two channels carry the signal:
 *
 * <p><b>Buffered</b> reply envelope: a namespaced sibling field
 * {@code _mesh_stop_reason: "max_iterations"} (sibling of {@code content} /
 * {@code _mesh_usage}). Absent on normal completion.
 *
 * <p><b>Streaming</b>: the MCP stream channel is strictly stringly-typed
 * (FastMCP progress notifications carry {@code str} chunks), so a structured
 * object cannot ride it directly. We adopt the Anthropic Messages API streaming
 * discipline: the discriminator is the frame <em>type</em>, never the text
 * content. EVERY chunk is a typed frame — a JSON <em>string</em> keyed by a
 * RESERVED {@code _mesh_}-namespaced discriminator — so text can never be
 * misread as a control signal:
 *
 * <ul>
 *   <li>text delta            → {@code {"_mesh_frame":"chunk","content":"<delta>"}}</li>
 *   <li>terminal, normal      → {@code {"_mesh_frame":"end"}}</li>
 *   <li>terminal, exhaustion  → {@code {"_mesh_frame":"end","stop_reason":"max_iterations"}}</li>
 * </ul>
 *
 * <p>The Java runtime has no provider-side streaming <b>producer</b> (deferred,
 * see #1223), so no frame encoder is defined here. But the streaming
 * <b>consumer</b> ({@code MeshLlmAgentProxy.streamGenerate()}) DOES decode these
 * frames when talking to a Python/TypeScript streaming provider (#1369): it
 * unwraps {@code chunk} content to the caller, completes on a plain {@code end}
 * frame, and raises {@link MeshMaxIterationsException} on an {@code end} frame
 * carrying {@code stop_reason == "max_iterations"}. The frame parser lives with
 * the consumer (mirroring the buffered {@code extractStopReason} JSON unwrap);
 * only the shared frame vocabulary is defined here.
 */
public final class MeshLlmStopReason {

    private MeshLlmStopReason() {}

    /** Shared vocabulary token (kept identical to Python/TypeScript). */
    public static final String STOP_REASON_MAX_ITERATIONS = "max_iterations";

    /** Reserved sibling key on the buffered reply envelope. */
    public static final String STOP_REASON_KEY = "_mesh_stop_reason";

    /**
     * Reserved discriminator key on every streaming frame. Byte-identical to
     * Python's {@code FRAME_KEY} and TypeScript's {@code FRAME_KEY}. Namespaced
     * under {@code _mesh_} so raw model text can never satisfy the frame check.
     */
    public static final String FRAME_KEY = "_mesh_frame";

    /** Frame type for a text delta ({@code {"_mesh_frame":"chunk","content":...}}). */
    public static final String FRAME_CHUNK = "chunk";

    /** Frame type for a terminal frame ({@code {"_mesh_frame":"end", ...}}). */
    public static final String FRAME_END = "end";
}
