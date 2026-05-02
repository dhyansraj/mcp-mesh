package io.mcpmesh.spring;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Issue #547 Phase 4: unit tests for the schema verdict policy helpers in
 * {@link MeshSchemaSupport}.
 *
 * <p>These tests are pure-Java (no native lib dependency).
 */
@DisplayName("MeshSchemaSupport — verdict policy")
class MeshSchemaVerdictPolicyTest {

    @Test
    @DisplayName("OK never refuses regardless of flags")
    void okNeverRefuses() {
        assertFalse(MeshSchemaSupport.shouldRefuseStartup("OK", false, true));
        assertFalse(MeshSchemaSupport.shouldRefuseStartup("OK", true, true));
        assertFalse(MeshSchemaSupport.shouldRefuseStartup("OK", true, false));
    }

    @Test
    @DisplayName("BLOCK with default toolStrict refuses")
    void blockWithDefaultsRefuses() {
        assertTrue(MeshSchemaSupport.shouldRefuseStartup("BLOCK", false, true));
    }

    @Test
    @DisplayName("BLOCK with per-tool override does not refuse")
    void blockWithOverrideDoesNotRefuse() {
        assertFalse(MeshSchemaSupport.shouldRefuseStartup("BLOCK", false, false));
    }

    @Test
    @DisplayName("WARN with defaults does not refuse")
    void warnWithDefaultsDoesNotRefuse() {
        assertFalse(MeshSchemaSupport.shouldRefuseStartup("WARN", false, true));
    }

    @Test
    @DisplayName("WARN with cluster strict refuses")
    void warnWithClusterStrictRefuses() {
        assertTrue(MeshSchemaSupport.shouldRefuseStartup("WARN", true, true));
    }

    @Test
    @DisplayName("Per-tool override wins over cluster strict (BLOCK case)")
    void overrideWinsBlock() {
        assertFalse(MeshSchemaSupport.shouldRefuseStartup("BLOCK", true, false));
    }

    @Test
    @DisplayName("Per-tool override wins over cluster strict (WARN case)")
    void overrideWinsWarn() {
        assertFalse(MeshSchemaSupport.shouldRefuseStartup("WARN", true, false));
    }

    @Test
    @DisplayName("Unknown verdict does not refuse")
    void unknownVerdictDoesNotRefuse() {
        // Defensive: anything that's not BLOCK or WARN is treated as a pass.
        assertFalse(MeshSchemaSupport.shouldRefuseStartup("UNKNOWN", true, true));
        assertFalse(MeshSchemaSupport.shouldRefuseStartup("", true, true));
    }
}
