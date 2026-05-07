package io.mcpmesh.spring;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the three MeshJob helper tool handlers (Phase B). These
 * tests cover the static surface (tool names, schema, validation) — the
 * actual JobProxy round-trip is exercised in integration tests because
 * it needs a live registry.
 */
class JobsHelperToolHandlerTest {

    private static final String DUMMY_REGISTRY = "http://localhost:0/no-such";

    @Test
    void all_returnsThreeHandlersWithExpectedNames() {
        List<JobsHelperToolHandler> handlers = JobsHelperToolHandler.all(DUMMY_REGISTRY);
        assertEquals(3, handlers.size());

        // Verify each handler reports the canonical __mesh_job_ name
        assertEquals(JobsHelperToolHandler.TOOL_NAME_STATUS, handlers.get(0).getCapability());
        assertEquals(JobsHelperToolHandler.TOOL_NAME_RESULT, handlers.get(1).getCapability());
        assertEquals(JobsHelperToolHandler.TOOL_NAME_CANCEL, handlers.get(2).getCapability());
    }

    @Test
    void status_inputSchemaRequiresJobIdString() {
        JobsHelperToolHandler h = new JobsHelperToolHandler(JobsHelperToolHandler.Op.STATUS, DUMMY_REGISTRY);
        Map<String, Object> schema = h.getInputSchema();
        assertEquals("object", schema.get("type"));
        @SuppressWarnings("unchecked")
        Map<String, Object> props = (Map<String, Object>) schema.get("properties");
        assertNotNull(props.get("job_id"));
        assertNull(props.get("reason"), "status helper has no `reason` field");
        @SuppressWarnings("unchecked")
        List<String> required = (List<String>) schema.get("required");
        assertTrue(required.contains("job_id"));
    }

    @Test
    void cancel_inputSchemaIncludesOptionalReason() {
        JobsHelperToolHandler h = new JobsHelperToolHandler(JobsHelperToolHandler.Op.CANCEL, DUMMY_REGISTRY);
        Map<String, Object> schema = h.getInputSchema();
        @SuppressWarnings("unchecked")
        Map<String, Object> props = (Map<String, Object>) schema.get("properties");
        assertNotNull(props.get("reason"), "cancel helper has a `reason` field");
        @SuppressWarnings("unchecked")
        List<String> required = (List<String>) schema.get("required");
        assertTrue(required.contains("job_id"));
        assertFalse(required.contains("reason"), "reason must be optional");
    }

    @Test
    void invoke_rejectsMissingJobId() {
        JobsHelperToolHandler h = new JobsHelperToolHandler(JobsHelperToolHandler.Op.STATUS, DUMMY_REGISTRY);
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> h.invoke(Map.of()));
        assertTrue(e.getMessage().contains("job_id"));
    }

    @Test
    void invoke_rejectsEmptyJobId() {
        JobsHelperToolHandler h = new JobsHelperToolHandler(JobsHelperToolHandler.Op.STATUS, DUMMY_REGISTRY);
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> h.invoke(Map.of("job_id", "")));
        assertTrue(e.getMessage().contains("job_id"));
    }

    @Test
    void invoke_rejectsNonStringJobId() {
        JobsHelperToolHandler h = new JobsHelperToolHandler(JobsHelperToolHandler.Op.STATUS, DUMMY_REGISTRY);
        assertThrows(IllegalArgumentException.class,
            () -> h.invoke(Map.of("job_id", 123)));
    }

    @Test
    void all_dependencyAndLlmCountsAreZero() {
        for (JobsHelperToolHandler h : JobsHelperToolHandler.all(DUMMY_REGISTRY)) {
            assertEquals(0, h.getDependencyCount(), "helper tools have no deps");
            assertEquals(0, h.getLlmAgentCount(), "helper tools have no LLM agents");
        }
    }

    @Test
    void funcId_usesSyntheticPrefix() {
        JobsHelperToolHandler h = new JobsHelperToolHandler(JobsHelperToolHandler.Op.STATUS, DUMMY_REGISTRY);
        // Synthetic prefix avoids collisions with user-declared funcIds
        assertTrue(h.getFuncId().startsWith("__mesh_jobs_helper."),
            "funcId must use the synthetic helper prefix; got: " + h.getFuncId());
    }
}
