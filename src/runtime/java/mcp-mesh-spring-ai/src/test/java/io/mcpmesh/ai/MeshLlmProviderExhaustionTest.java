package io.mcpmesh.ai;

import io.mcpmesh.types.MeshLlmStopReason;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1355: the LLM {@code max_iterations} exhaustion signal (provider side).
 *
 * <p>On exhaustion the provider-managed parallel loop must mark the failure
 * <em>structurally</em> via the {@code _mesh_stop_reason: "max_iterations"}
 * sibling field — never by writing an English marker into {@code content}.
 * {@code content} carries the last genuine assistant text (or {@code ""}); the
 * discriminant is omitted on a normal completion so absence means a normal turn.
 *
 * <p>The parallel loop is the only mesh-owned agentic loop in the Java provider
 * (the sequential shape delegates the tool loop to Spring AI's {@code ChatClient},
 * which manages iterations internally and exposes no exhaustion signal). This test
 * exercises the extracted {@link MeshLlmProviderProcessor#applyExhaustionSignal}
 * envelope builder — the exact wire shape that path emits — following the module
 * convention of unit-testing the extracted static helpers.
 */
@DisplayName("MeshLlmProviderProcessor — max_iterations exhaustion signal (#1355)")
class MeshLlmProviderExhaustionTest {

    @Test
    @DisplayName("wire vocabulary byte-matches Python/TypeScript")
    void wireVocabularyMatches() {
        assertEquals("_mesh_stop_reason", MeshLlmStopReason.STOP_REASON_KEY);
        assertEquals("max_iterations", MeshLlmStopReason.STOP_REASON_MAX_ITERATIONS);
    }

    @Test
    @DisplayName("exhaustion sets the discriminant and drops the English marker")
    void exhaustionSetsDiscriminant() {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("model", "anthropic/claude");

        MeshLlmProviderProcessor.applyExhaustionSignal(response, "partial reasoning");

        assertEquals("max_iterations", response.get(MeshLlmStopReason.STOP_REASON_KEY));
        // content is the last genuine assistant text — never the fabricated marker.
        assertEquals("partial reasoning", response.get("content"));
        assertNotEquals("Maximum tool call iterations reached", response.get("content"));
        assertEquals(List.of(), response.get("tool_calls"));
        // Sibling fields already on the envelope are preserved.
        assertEquals("anthropic/claude", response.get("model"));
    }

    @Test
    @DisplayName("null last-assistant-text collapses to \"\" (never fabricated)")
    void nullLastTextBecomesEmpty() {
        Map<String, Object> response = new LinkedHashMap<>();

        MeshLlmProviderProcessor.applyExhaustionSignal(response, null);

        assertEquals("", response.get("content"));
        assertEquals("max_iterations", response.get(MeshLlmStopReason.STOP_REASON_KEY));
    }

    @Test
    @DisplayName("a normal-completion envelope omits the discriminant (absence == normal turn)")
    void normalCompletionOmitsDiscriminant() {
        // A normal completion builds the envelope WITHOUT applyExhaustionSignal.
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("content", "final answer");
        response.put("tool_calls", List.of());

        assertFalse(response.containsKey(MeshLlmStopReason.STOP_REASON_KEY),
            "normal completion must omit _mesh_stop_reason");
    }
}
