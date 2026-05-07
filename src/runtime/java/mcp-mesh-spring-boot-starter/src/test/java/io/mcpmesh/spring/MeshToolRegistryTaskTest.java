package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.core.AgentSpec;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the Phase B {@code task} flag wiring on
 * {@link MeshToolRegistry}.
 *
 * <p>Verifies the {@code task=true} flag flows from the {@link MeshTool}
 * annotation into the registry's metadata AND into the heartbeat
 * ToolSpec's {@code kwargs} JSON — matching Python's
 * {@code rust_heartbeat.py} kwargs spread which carries the same flag
 * through to the registry catalog.
 */
class MeshToolRegistryTaskTest {

    static class TaskBean {
        @MeshTool(capability = "task_cap", task = true)
        public String taskMethod(@Param("input") String input) {
            return input;
        }

        @MeshTool(capability = "regular_cap")
        public String regularMethod(@Param("input") String input) {
            return input;
        }
    }

    private static Method find(String name) {
        for (Method m : TaskBean.class.getDeclaredMethods()) {
            if (m.getName().equals(name)) return m;
        }
        throw new AssertionError(name);
    }

    @Test
    void registerTool_persistsTaskFlagInMetadata() throws Exception {
        MeshToolRegistry reg = new MeshToolRegistry();
        Object bean = new TaskBean();
        reg.registerTool(bean, find("taskMethod"),
            find("taskMethod").getAnnotation(MeshTool.class));

        MeshToolRegistry.ToolMetadata meta = reg.getTool("task_cap");
        assertNotNull(meta);
        assertTrue(meta.task(), "task flag must round-trip into metadata");
    }

    @Test
    void registerTool_regularMethodHasTaskFalse() throws Exception {
        MeshToolRegistry reg = new MeshToolRegistry();
        Object bean = new TaskBean();
        reg.registerTool(bean, find("regularMethod"),
            find("regularMethod").getAnnotation(MeshTool.class));

        MeshToolRegistry.ToolMetadata meta = reg.getTool("regular_cap");
        assertNotNull(meta);
        assertFalse(meta.task(), "regular tool defaults to task=false");
    }

    @Test
    void getToolSpecs_emitsTaskTrueInKwargsForTaskTools() throws Exception {
        MeshToolRegistry reg = new MeshToolRegistry();
        Object bean = new TaskBean();
        reg.registerTool(bean, find("taskMethod"),
            find("taskMethod").getAnnotation(MeshTool.class));

        List<AgentSpec.ToolSpec> specs = reg.getToolSpecs();
        AgentSpec.ToolSpec taskSpec = specs.stream()
            .filter(s -> "task_cap".equals(s.getCapability()))
            .findFirst()
            .orElseThrow();
        assertNotNull(taskSpec.getKwargs(), "task=true tool must carry kwargs");
        assertTrue(taskSpec.getKwargs().contains("\"task\""),
            "kwargs JSON must contain the `task` key");
        assertTrue(taskSpec.getKwargs().contains("true"),
            "kwargs JSON must record task=true");
    }

    @Test
    void getToolSpecs_emitsNoKwargsForRegularTools() throws Exception {
        MeshToolRegistry reg = new MeshToolRegistry();
        Object bean = new TaskBean();
        reg.registerTool(bean, find("regularMethod"),
            find("regularMethod").getAnnotation(MeshTool.class));

        AgentSpec.ToolSpec regularSpec = reg.getToolSpecs().get(0);
        assertNull(regularSpec.getKwargs(),
            "regular tools must not emit kwargs (matches Python's behavior — empty kwargs → null)");
    }

    @Test
    void addSyntheticTool_appendsToHeartbeatCatalog() {
        MeshToolRegistry reg = new MeshToolRegistry();
        AgentSpec.ToolSpec synth = new AgentSpec.ToolSpec("__mesh_job_status", "__mesh_job_status");
        reg.addSyntheticTool(synth);
        assertEquals(1, reg.getToolSpecs().size());
        assertEquals("__mesh_job_status", reg.getToolSpecs().get(0).getCapability());
    }
}
