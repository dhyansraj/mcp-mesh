package io.mcpmesh.a2a;

import tools.jackson.databind.JsonNode;

/**
 * One parsed event from a {@code tasks/sendSubscribe} SSE stream
 * (returned by {@link A2AClient#subscribe}).
 *
 * <p>{@link Kind#STATUS} events are {@code TaskStatusUpdateEvent} frames
 * carrying {@code state}/{@code progress}/{@code message} (and
 * {@code isFinal=true} on the terminal frame). {@link Kind#ARTIFACT}
 * events are {@code TaskArtifactUpdateEvent} frames carrying
 * {@code artifactText}.
 *
 * <p>Mirrors {@code mesh._a2a_consumer.A2AEvent} from the Python
 * runtime (issue #910 Phase 3).
 *
 * @param kind         event kind ({@code STATUS} or {@code ARTIFACT}).
 * @param state        for {@link Kind#STATUS} events: lifecycle state
 *                     (typically {@code working} / {@code completed} /
 *                     {@code failed} / {@code canceled}); {@code null}
 *                     for {@link Kind#ARTIFACT} events.
 * @param progress     normalized progress fraction (0.0..1.0) when
 *                     present in the envelope's {@code result.metadata};
 *                     {@code null} otherwise.
 * @param message      optional human-readable status message
 *                     (from {@code status.message.parts[0].text}).
 * @param artifactText for {@link Kind#ARTIFACT} events: the artifact's
 *                     {@code parts[0].text} payload (typically
 *                     JSON-stringified handler return); {@code null} for
 *                     {@link Kind#STATUS} events.
 * @param isFinal      {@code true} for the terminal status frame —
 *                     callers SHOULD stop iterating once they have
 *                     consumed this event (the producer will close the
 *                     stream right after).
 * @param raw          the unparsed JSON-RPC envelope for callers that
 *                     need fields the convenience accessors don't expose.
 *                     <p><b>Sharing semantics:</b> Despite the enclosing
 *                     record being immutable, this {@link JsonNode} is
 *                     the live parse tree owned by the surrounding
 *                     {@link A2AStream}. Treat it as read-only — any
 *                     mutation (e.g.
 *                     {@code ((ObjectNode) raw).put(...)}) leaks into
 *                     other consumers of the same envelope. Deep-copy
 *                     via {@code raw.deepCopy()} if mutation is
 *                     required.
 */
public record A2AEvent(
    Kind kind,
    String state,
    Double progress,
    String message,
    String artifactText,
    boolean isFinal,
    JsonNode raw
) {

    /**
     * Discriminator for the two A2A v1.0 SSE event shapes the consumer
     * cares about. Other event types
     * ({@code TaskInputRequiredEvent}, etc.) are skipped at parse time
     * rather than surfaced as a third Kind — this matches the Python
     * runtime's parse-and-skip approach.
     */
    public enum Kind {
        /** {@code TaskStatusUpdateEvent} — lifecycle / progress frames. */
        STATUS,
        /** {@code TaskArtifactUpdateEvent} — artifact-payload frames. */
        ARTIFACT
    }
}
