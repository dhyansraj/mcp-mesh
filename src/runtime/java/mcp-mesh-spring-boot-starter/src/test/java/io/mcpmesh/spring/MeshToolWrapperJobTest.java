package io.mcpmesh.spring;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.Param;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the Phase B MeshJob fields on {@link MeshToolWrapper}.
 *
 * <p>Covers the parts of the inbound dispatch wrapper that don't require
 * a live Rust core (job param recognition, slot injection on non-job
 * paths, getter contracts). The job-dispatch path itself (constructing
 * a {@link JobController} via FFI + binding both contexts) is exercised
 * end-to-end in the integration suite.
 */
class MeshToolWrapperJobTest {

    @SuppressWarnings("unused")
    static class Producer {
        // task=true producer with a MeshJob slot — same shape as the
        // long-task-provider example.
        public Map<String, Object> generateReport(
                @Param("user_id") String userId,
                @Param(value = "sections", required = false) List<String> sections,
                MeshJob job) {
            return Map.of("user_id", userId, "report", List.of());
        }

        // No MeshJob slot — task=true is allowed but the slot is optional.
        public String simpleTask(@Param("input") String input) {
            return "ok:" + input;
        }
    }

    @SuppressWarnings("unused")
    static class Consumer {
        // Consumer-side: MeshJob slot + a declared dependency name.
        public Map<String, Object> commissionReport(
                @Param("user_id") String userId,
                MeshJob generateReport) {
            return Map.of();
        }
    }

    private static Method find(Class<?> cls, String name) {
        for (Method m : cls.getDeclaredMethods()) {
            if (m.getName().equals(name)) return m;
        }
        throw new AssertionError("not found: " + name);
    }

    @Test
    void taskWrapper_recordsTaskFlagAndMeshJobIndex() {
        MeshToolWrapper w = new MeshToolWrapper(
            "Producer.generateReport",
            "generate_report",
            "test",
            new Producer(),
            find(Producer.class, "generateReport"),
            List.of(),
            JsonMapper.builder().build(),
            true
        );
        assertTrue(w.isTask(), "task flag must round-trip");
        assertEquals(2, w.getMeshJobParamIndex(),
            "MeshJob param sits at signature position 2 (after user_id + sections)");
    }

    @Test
    void taskWrapper_meshJobParamIsNotInInputSchema() {
        MeshToolWrapper w = new MeshToolWrapper(
            "Producer.generateReport",
            "generate_report",
            "test",
            new Producer(),
            find(Producer.class, "generateReport"),
            List.of(),
            JsonMapper.builder().build(),
            true
        );
        Map<String, Object> schema = w.getInputSchema();
        @SuppressWarnings("unchecked")
        Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
        // user_id + sections → 2 props; MeshJob is exempt.
        assertEquals(2, properties.size(),
            "MeshJob param must be excluded from MCP input schema");
        assertTrue(properties.containsKey("user_id"));
        assertTrue(properties.containsKey("sections"));
        assertFalse(properties.containsKey("job"));
    }

    @Test
    void taskWrapper_withoutMeshJobSlot_isLegal() {
        MeshToolWrapper w = new MeshToolWrapper(
            "Producer.simpleTask",
            "simple_task",
            "test",
            new Producer(),
            find(Producer.class, "simpleTask"),
            List.of(),
            JsonMapper.builder().build(),
            true
        );
        assertTrue(w.isTask());
        assertNull(w.getMeshJobParamIndex(),
            "task=true without a MeshJob slot must not synthesize one");
    }

    @Test
    void nonTaskWrapper_isTaskReturnsFalse() {
        MeshToolWrapper w = new MeshToolWrapper(
            "Consumer.commissionReport",
            "commission_report",
            "test",
            new Consumer(),
            find(Consumer.class, "commissionReport"),
            List.of("generate_report"),
            JsonMapper.builder().build(),
            false
        );
        assertFalse(w.isTask());
        assertEquals(1, w.getMeshJobParamIndex(),
            "consumer's MeshJob slot at signature position 1");
    }

    @Test
    void invoke_withoutJobIdHeader_passesNullForMeshJobSlot() throws Exception {
        // No X-Mesh-Job-Id and no submitter wired → MeshJob slot is null.
        // The user method must tolerate null per MESHJOB_DDDI_CONTRACT.md.
        MeshToolWrapper w = new MeshToolWrapper(
            "Consumer.commissionReport",
            "commission_report",
            "test",
            new Consumer(),
            find(Consumer.class, "commissionReport"),
            List.of("generate_report"),
            JsonMapper.builder().build(),
            false
        );
        // Direct invoke — no TraceContext set, so no propagated headers.
        Object result = w.invoke(Map.of("user_id", "demo"));
        assertNotNull(result);
        // The Consumer method just returns Map.of(); no NPE means the
        // null MeshJob slot was handled correctly.
    }

    @Test
    void setJobBindingContext_isSafeWithNulls() {
        MeshToolWrapper w = new MeshToolWrapper(
            "Producer.simpleTask",
            "simple_task",
            "test",
            new Producer(),
            find(Producer.class, "simpleTask"),
            List.of(),
            JsonMapper.builder().build(),
            true
        );
        // Both null is a no-op (defensive — in case the runtime hasn't
        // resolved instance id / registry url yet).
        assertDoesNotThrow(() -> w.setJobBindingContext(null, null));
        assertDoesNotThrow(() -> w.setJobBindingContext("id", "http://x"));
    }

    @Test
    void setJobSubmitter_acceptsSubmitterAndNull() {
        MeshToolWrapper w = new MeshToolWrapper(
            "Consumer.commissionReport",
            "commission_report",
            "test",
            new Consumer(),
            find(Consumer.class, "commissionReport"),
            List.of("generate_report"),
            JsonMapper.builder().build(),
            false
        );
        MeshJobSubmitter submitter = new MeshJobSubmitter("generate_report", "consumer-1", "http://localhost:8000");
        assertDoesNotThrow(() -> w.setJobSubmitter(submitter));
        assertDoesNotThrow(() -> w.setJobSubmitter(null));
    }
}
