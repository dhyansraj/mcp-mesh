package io.mcpmesh.spring;

import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshObjectMappers;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the helper tool startup registrar (Phase B). Verifies
 * the auto-registration on every agent + skip-on-no-registry behavior.
 */
class JobsHelperToolsRegistrarTest {

    @Test
    void register_addsThreeWrappersAndThreeSyntheticSpecs() {
        MeshToolRegistry toolRegistry = new MeshToolRegistry();
        MeshToolWrapperRegistry wrapperRegistry =
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory());

        JobsHelperToolsRegistrar.register(toolRegistry, wrapperRegistry, "http://localhost:8000");

        // Three handlers in the wrapper registry
        assertNotNull(wrapperRegistry.getHandlerByCapability(JobsHelperToolHandler.TOOL_NAME_STATUS));
        assertNotNull(wrapperRegistry.getHandlerByCapability(JobsHelperToolHandler.TOOL_NAME_RESULT));
        assertNotNull(wrapperRegistry.getHandlerByCapability(JobsHelperToolHandler.TOOL_NAME_CANCEL));

        // Three synthetic ToolSpecs in the heartbeat catalog
        List<AgentSpec.ToolSpec> specs = toolRegistry.getToolSpecs();
        assertEquals(3, specs.size(), "expected 3 synthetic tool specs in heartbeat");

        // All three have the framework_internal kwargs marker
        for (AgentSpec.ToolSpec s : specs) {
            assertNotNull(s.getKwargs(), "synthetic helper specs must carry kwargs");
            assertTrue(s.getKwargs().contains("framework_internal"),
                "kwargs must mark the spec framework-internal");
        }
    }

    @Test
    void register_isSkippedOnEmptyRegistryUrl() {
        MeshToolRegistry toolRegistry = new MeshToolRegistry();
        MeshToolWrapperRegistry wrapperRegistry =
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory());

        JobsHelperToolsRegistrar.register(toolRegistry, wrapperRegistry, "");

        // No registry URL → no helpers registered (without a registry to
        // talk to, the helpers can't function — same skip semantics as
        // the Python and TS registrars).
        assertNull(wrapperRegistry.getHandlerByCapability(JobsHelperToolHandler.TOOL_NAME_STATUS));
        assertEquals(0, toolRegistry.getToolSpecs().size());
    }

    @Test
    void register_isSkippedOnNullRegistryUrl() {
        MeshToolRegistry toolRegistry = new MeshToolRegistry();
        MeshToolWrapperRegistry wrapperRegistry =
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory());

        JobsHelperToolsRegistrar.register(toolRegistry, wrapperRegistry, null);

        assertNull(wrapperRegistry.getHandlerByCapability(JobsHelperToolHandler.TOOL_NAME_STATUS));
        assertEquals(0, toolRegistry.getToolSpecs().size());
    }
}
