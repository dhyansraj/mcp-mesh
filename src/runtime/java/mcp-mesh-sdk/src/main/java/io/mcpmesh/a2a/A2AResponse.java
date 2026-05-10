package io.mcpmesh.a2a;

import tools.jackson.databind.JsonNode;

/**
 * Result of a synchronous {@link A2AClient#send} call.
 *
 * <p>{@code artifactText} is the canonical sync return — the
 * producer-side surface places the handler's return value as
 * {@code result.artifacts[0].parts[0].text} (JSON-stringified for
 * non-string returns). Consumers that need the raw envelope
 * (multi-artifact responses, status messages, history) can read
 * {@link #rawTask()}.
 *
 * <p>{@code state} is the lifecycle state from the terminal {@code Task}
 * envelope (typically one of {@code completed} / {@code failed} /
 * {@code canceled}); {@code taskId} is the consumer-generated ID that
 * the producer echoed back.
 *
 * <p>Mirrors {@code mesh._a2a_consumer.A2AResponse}.
 *
 * @param artifactText canonical sync return value (text part of the
 *                     first artifact); empty string when the producer
 *                     emitted no artifacts.
 * @param state        terminal lifecycle state from the {@code Task}
 *                     envelope (typically {@code completed} /
 *                     {@code failed} / {@code canceled}).
 * @param taskId       consumer-generated task ID echoed back by the
 *                     producer.
 * @param rawTask      the full A2A v1.0 Task envelope's {@code result}
 *                     field — useful for advanced consumers that need
 *                     fields beyond the parsed convenience properties
 *                     ({@code artifactText}, {@code state}, {@code taskId}).
 *                     <p><b>Sharing semantics:</b> Despite the enclosing
 *                     record being immutable, this {@link JsonNode} is the
 *                     live parse tree owned by {@link A2AClient}. Treat it
 *                     as read-only — any mutation (e.g.
 *                     {@code ((ObjectNode) rawTask).put(...)}) leaks into
 *                     other consumers of the same response. Deep-copy via
 *                     {@code rawTask.deepCopy()} if mutation is required.
 */
public record A2AResponse(
    String artifactText,
    String state,
    String taskId,
    JsonNode rawTask
) {
}
