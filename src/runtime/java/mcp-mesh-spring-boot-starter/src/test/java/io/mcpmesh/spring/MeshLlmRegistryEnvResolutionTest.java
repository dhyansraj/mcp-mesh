package io.mcpmesh.spring;

import io.mcpmesh.FilterMode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the {@code MESH_LLM_*} env-override resolution helpers
 * (issue #1112, finding 2). The helpers are pure functions taking the env
 * string as a parameter, so they are exercised directly without mutating the
 * process environment. Precedence is ENV &gt; annotation &gt; default.
 */
@DisplayName("MeshLlmRegistry — MESH_LLM_* env resolution")
class MeshLlmRegistryEnvResolutionTest {

    @Test
    @DisplayName("resolveMaxIterations: valid positive env wins over annotation")
    void maxIterationsEnvWins() {
        assertEquals(3, MeshLlmRegistry.resolveMaxIterations("3", 10));
    }

    @Test
    @DisplayName("resolveMaxIterations: null env falls back to annotation")
    void maxIterationsNullFallsBack() {
        assertEquals(5, MeshLlmRegistry.resolveMaxIterations(null, 5));
    }

    @Test
    @DisplayName("resolveMaxIterations: blank env falls back to annotation")
    void maxIterationsBlankFallsBack() {
        assertEquals(5, MeshLlmRegistry.resolveMaxIterations("  ", 5));
    }

    @Test
    @DisplayName("resolveMaxIterations: non-numeric env falls back to annotation (warns)")
    void maxIterationsInvalidFallsBack() {
        assertEquals(5, MeshLlmRegistry.resolveMaxIterations("abc", 5));
    }

    @Test
    @DisplayName("resolveMaxIterations: non-positive env falls back to annotation")
    void maxIterationsNonPositiveFallsBack() {
        assertEquals(5, MeshLlmRegistry.resolveMaxIterations("0", 5));
        assertEquals(5, MeshLlmRegistry.resolveMaxIterations("-2", 5));
    }

    @Test
    @DisplayName("resolveFilterModeOrdinal: known env value maps to matching ordinal (case-insensitive)")
    void filterModeEnvWins() {
        assertEquals(FilterMode.BEST_MATCH.ordinal(),
            MeshLlmRegistry.resolveFilterModeOrdinal("best_match", FilterMode.ALL));
        assertEquals(FilterMode.WILDCARD.ordinal(),
            MeshLlmRegistry.resolveFilterModeOrdinal("WILDCARD", FilterMode.ALL));
        assertEquals(FilterMode.ALL.ordinal(),
            MeshLlmRegistry.resolveFilterModeOrdinal("all", FilterMode.WILDCARD));
    }

    @Test
    @DisplayName("resolveFilterModeOrdinal: unknown env value falls back to annotation ordinal (warns)")
    void filterModeUnknownFallsBack() {
        assertEquals(FilterMode.ALL.ordinal(),
            MeshLlmRegistry.resolveFilterModeOrdinal("bogus", FilterMode.ALL));
    }

    @Test
    @DisplayName("resolveFilterModeOrdinal: null/blank env falls back to annotation ordinal")
    void filterModeNullFallsBack() {
        assertEquals(FilterMode.BEST_MATCH.ordinal(),
            MeshLlmRegistry.resolveFilterModeOrdinal(null, FilterMode.BEST_MATCH));
        assertEquals(FilterMode.BEST_MATCH.ordinal(),
            MeshLlmRegistry.resolveFilterModeOrdinal("  ", FilterMode.BEST_MATCH));
    }
}
