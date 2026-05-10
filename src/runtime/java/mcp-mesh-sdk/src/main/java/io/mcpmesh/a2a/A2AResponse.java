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
 */
public record A2AResponse(
    String artifactText,
    String state,
    String taskId,
    JsonNode rawTask
) {
}
