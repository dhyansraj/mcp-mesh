package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1277 (WAVE 2c): {@code @MeshTool(resumeCursor = true)} requires
 * {@code task = true} — a non-task tool has no {@link io.mcpmesh.JobController},
 * so a resume cursor has no meaning. The
 * {@link MeshToolBeanPostProcessor} fails fast at startup otherwise (mirrors
 * the issue #895 {@code retryOn requires task=true} guard).
 */
@DisplayName("@MeshTool(resumeCursor) — startup validation (issue #1277)")
class MeshToolResumeCursorValidationTest {

    // ── Fixtures ────────────────────────────────────────────────────────────

    /** Illegal: resumeCursor without task. */
    public static class ResumeWithoutTaskBean {
        @MeshTool(capability = "bad_resume", resumeCursor = true)
        public String bad(@Param("x") String x) {
            return x;
        }
    }

    /** Legal: resumeCursor with task=true. */
    public static class ResumeWithTaskBean {
        @MeshTool(capability = "good_resume", task = true, resumeCursor = true)
        public String good(@Param("x") String x, MeshJob job) {
            return x;
        }
    }

    /** Baseline: no resumeCursor opt-in. */
    public static class PlainBean {
        @MeshTool(capability = "plain")
        public String plain(@Param("x") String x) {
            return x;
        }
    }

    // ── Helper ──────────────────────────────────────────────────────────────

    private static MeshToolBeanPostProcessor processor(MeshToolRegistry registry) {
        return new MeshToolBeanPostProcessor(
            registry,
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory()),
            JsonMapper.builder().build());
    }

    // ── Tests ───────────────────────────────────────────────────────────────

    @Test
    @DisplayName("resumeCursor=true without task=true → boot error naming the constraint")
    void resumeCursorWithoutTaskFailsFast() {
        MeshToolRegistry registry = new MeshToolRegistry();
        IllegalStateException ex = assertThrows(IllegalStateException.class, () ->
            processor(registry).postProcessAfterInitialization(
                new ResumeWithoutTaskBean(), "bad"));
        assertTrue(ex.getMessage().contains("resumeCursor"),
            "error must name resumeCursor. Got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("task = true"),
            "error must state the task=true requirement. Got: " + ex.getMessage());
    }

    @Test
    @DisplayName("resumeCursor=true with task=true → accepted, flag captured on metadata")
    void resumeCursorWithTaskAccepted() {
        MeshToolRegistry registry = new MeshToolRegistry();
        assertDoesNotThrow(() ->
            processor(registry).postProcessAfterInitialization(
                new ResumeWithTaskBean(), "good"));
        MeshToolRegistry.ToolMetadata meta = registry.getTool("good_resume");
        assertNotNull(meta);
        assertTrue(meta.task());
        assertTrue(meta.resumeCursor(),
            "resumeCursor opt-in must be threaded onto the tool metadata");
    }

    @Test
    @DisplayName("no resumeCursor opt-in → defaults to false")
    void plainToolDefaultsResumeCursorFalse() {
        MeshToolRegistry registry = new MeshToolRegistry();
        assertDoesNotThrow(() ->
            processor(registry).postProcessAfterInitialization(
                new PlainBean(), "plain"));
        MeshToolRegistry.ToolMetadata meta = registry.getTool("plain");
        assertNotNull(meta);
        assertFalse(meta.resumeCursor(), "resumeCursor must default to false");
    }
}
