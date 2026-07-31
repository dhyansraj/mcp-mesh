package io.mcpmesh.spring;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Two declarations may not advertise the same MCP tool name — issue #1442.
 *
 * <p>{@code MeshMcpServerConfiguration.registerTool} names the MCP tool
 * {@code handler.getMethodName()} — a BARE method name, no class qualifier —
 * and the registration loop iterates {@code getAllHandlers()}, which is keyed
 * by funcId ({@code FQCN.methodName}). Two {@code @MeshTool} methods named
 * {@code analyze} in different classes therefore both reach
 * {@code server.addTool}, and the MCP SDK 2.0.0 keeps one silently. Since the
 * advertised name IS the wire name — {@code tools/call} carries
 * {@code params.name = <registry function_name>} — the loser is unreachable
 * while the registry keeps advertising it.
 *
 * <p>The guard is the MCP-layer analogue of
 * {@link MeshToolRegistryDuplicateCapabilityTest}'s duplicate-capability boot
 * error, and it borrows the same tolerance: the discriminator is the funcId,
 * NOT handler identity, so re-registering the same declaration with a fresh
 * handler instance (prototype bean, context refresh, repeated post-processing)
 * is not a collision.
 */
@DisplayName("MCP registration — duplicate advertised tool name fails the boot (issue #1442)")
class MeshMcpServerDuplicateToolNameTest {

    /**
     * Minimal {@link McpToolHandler}: the guard reads only the funcId and the
     * advertised method name.
     */
    private record StubHandler(String funcId, String capability, String methodName)
            implements McpToolHandler {

        @Override
        public String getFuncId() {
            return funcId;
        }

        @Override
        public String getCapability() {
            return capability;
        }

        @Override
        public String getMethodName() {
            return methodName;
        }

        @Override
        public String getDescription() {
            return "stub";
        }

        @Override
        public Map<String, Object> getInputSchema() {
            return Map.of("type", "object");
        }

        @Override
        public Object invoke(Map<String, Object> mcpArgs) {
            return null;
        }

        @Override
        public int getDependencyCount() {
            return 0;
        }

        @Override
        public int getLlmAgentCount() {
            return 0;
        }
    }

    private static StubHandler tool(Class<?> owner, String methodName) {
        return new StubHandler(owner.getName() + "." + methodName, methodName, methodName);
    }

    // ─────────────────────────────────────────────────────────────────
    // The collision
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("two @MeshTool methods named the same in different classes → boot error naming both")
    void sameMethodNameInTwoClassesFailsBoot() {
        List<McpToolHandler> handlers = List.of(
            tool(AlphaTools.class, "analyze"),
            tool(BetaTools.class, "analyze"));

        IllegalStateException boom = assertThrows(IllegalStateException.class,
            () -> MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(handlers));

        assertTrue(boom.getMessage().contains("'analyze'"),
            "the error must name the contested MCP tool name. Got: " + boom.getMessage());
        assertTrue(boom.getMessage().contains(AlphaTools.class.getName() + ".analyze"),
            "the error must name the first declaration by funcId. Got: " + boom.getMessage());
        assertTrue(boom.getMessage().contains(BetaTools.class.getName() + ".analyze"),
            "the error must name the second declaration by funcId. Got: " + boom.getMessage());
    }

    @Test
    @DisplayName("the collision is caught through the real wrapper registry's handler collection")
    void collisionIsCaughtThroughTheWrapperRegistry() {
        MeshToolWrapperRegistry registry = new MeshToolWrapperRegistry(null);
        registry.registerHandler(tool(AlphaTools.class, "search"));
        registry.registerHandler(tool(BetaTools.class, "search"));

        // Both survive getAllHandlers() — it is keyed by funcId, and the two
        // funcIds differ. That is exactly why both reach server.addTool.
        assertThrows(IllegalStateException.class,
            () -> MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(
                registry.getAllHandlers()));
    }

    @Test
    @DisplayName("two @MeshLlmProvider classes get a remedy that fits — no method to rename")
    void twoLlmProvidersGetAProviderSpecificRemedy() {
        // Every provider wrapper returns the framework constant 'llm_generate'
        // from getMethodName(), so "rename one of the methods" is advice the
        // user cannot act on: the name is not theirs.
        List<McpToolHandler> handlers = List.of(
            new StubHandler("llm_provider:llm-claude", "llm-claude", "llm_generate"),
            new StubHandler("llm_provider:llm-gpt", "llm-gpt", "llm_generate"));

        IllegalStateException boom = assertThrows(IllegalStateException.class,
            () -> MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(handlers));

        assertTrue(boom.getMessage().contains("@MeshLlmProvider"),
            "the remedy must name the annotation actually involved. Got: " + boom.getMessage());
        assertTrue(boom.getMessage().contains("its own agent"),
            "the only real fix is one provider per agent. Got: " + boom.getMessage());
        assertTrue(!boom.getMessage().contains("Rename one of the methods"),
            "there is no method to rename. Got: " + boom.getMessage());
    }

    @Test
    @DisplayName("a @MeshTool colliding with the LLM provider names the provider explicitly")
    void toolVersusProviderRemedyNamesTheProvider() {
        List<McpToolHandler> handlers = List.of(
            new StubHandler("llm_provider:llm", "llm", "llm_generate"),
            new StubHandler(AlphaTools.class.getName() + ".llm_generate", "gen",
                "llm_generate"));

        IllegalStateException boom = assertThrows(IllegalStateException.class,
            () -> MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(handlers));

        assertTrue(boom.getMessage().contains("@MeshLlmProvider"), boom.getMessage());
        assertTrue(boom.getMessage().contains("Rename the @MeshTool method"), boom.getMessage());
    }

    @Test
    @DisplayName("an ordinary @MeshTool collision keeps the rename remedy")
    void ordinaryCollisionKeepsTheRenameRemedy() {
        List<McpToolHandler> handlers = List.of(
            tool(AlphaTools.class, "analyze"),
            tool(BetaTools.class, "analyze"));

        IllegalStateException boom = assertThrows(IllegalStateException.class,
            () -> MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(handlers));

        assertTrue(boom.getMessage().contains("Rename one of the methods"), boom.getMessage());
        assertTrue(!boom.getMessage().contains("@MeshLlmProvider"), boom.getMessage());
    }

    @Test
    @DisplayName("a null funcId claims the name — it must not read as unclaimed for the next handler")
    void aNullFuncIdStillClaimsTheName() {
        // McpToolHandler is a public interface and getFuncId() has no default,
        // so nothing enforces non-null. The map permits null values, and
        // putIfAbsent REPLACES a null-valued mapping and returns null — so on
        // putIfAbsent the second handler read "unclaimed" and the collision
        // walked through the one guard whose entire job is to not let it.
        List<McpToolHandler> handlers = List.of(
            new StubHandler(null, "first", "analyze"),
            tool(BetaTools.class, "analyze"));

        IllegalStateException boom = assertThrows(IllegalStateException.class,
            () -> MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(handlers));
        assertTrue(boom.getMessage().contains("'analyze'"), boom.getMessage());
        assertTrue(boom.getMessage().contains(BetaTools.class.getName() + ".analyze"),
            boom.getMessage());
    }

    @Test
    @DisplayName("a null funcId on the SECOND handler is still a collision")
    void aNullFuncIdOnTheIncomingHandlerIsACollision() {
        List<McpToolHandler> handlers = List.of(
            tool(AlphaTools.class, "analyze"),
            new StubHandler(null, "second", "analyze"));

        assertThrows(IllegalStateException.class,
            () -> MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(handlers));
    }

    @Test
    @DisplayName("two handlers that BOTH report a null funcId are treated as one declaration")
    void twoNullFuncIdsAreNotDistinguishable() {
        // Nothing distinguishes them, so this stays tolerant rather than
        // failing a boot on a pair the guard cannot actually tell apart.
        List<McpToolHandler> handlers = List.of(
            new StubHandler(null, "a", "analyze"),
            new StubHandler(null, "b", "analyze"));

        assertDoesNotThrow(() ->
            MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(handlers));
    }

    // ─────────────────────────────────────────────────────────────────
    // Idempotent re-registration is NOT a collision (the #1445 lesson)
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("the SAME declaration re-registered is tolerated — a fresh instance is not a collision")
    void sameDeclarationReRegisteredIsTolerated() {
        // A prototype-scoped bean instantiated twice, or a Spring context
        // refresh, hands the registry a NEW handler object for an UNCHANGED
        // funcId. Discriminating on instance identity would boot-fail that.
        StubHandler first = tool(AlphaTools.class, "analyze");
        StubHandler second = tool(AlphaTools.class, "analyze");
        assertTrue(first != second, "the two handlers must be distinct instances");

        assertDoesNotThrow(() -> MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(
            List.of(first, second)));
    }

    // ─────────────────────────────────────────────────────────────────
    // A normal agent must not trip the guard
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("LLM provider + the three jobs helpers + regular @MeshTools boot clean")
    void aNormalAgentDoesNotTripTheGuard() {
        List<McpToolHandler> handlers = new ArrayList<>();
        // One @MeshLlmProvider class → one handler, fixed name llm_generate.
        handlers.add(new StubHandler("llm_provider:llm", "llm", "llm_generate"));
        // JobsHelperToolsRegistrar, one handler per op under a synthetic funcId.
        for (String op : List.of("__mesh_job_status", "__mesh_job_result", "__mesh_job_cancel")) {
            handlers.add(new StubHandler("__mesh_jobs_helper." + op, op, op));
        }
        handlers.add(tool(AlphaTools.class, "greet"));
        handlers.add(tool(AlphaTools.class, "analyze"));
        handlers.add(tool(BetaTools.class, "summarize"));

        assertDoesNotThrow(() -> MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(handlers));
    }

    @Test
    @DisplayName("a repeated jobs-helper registration pass is idempotent, not a collision")
    void repeatedJobsHelperRegistrationIsTolerated() {
        // JobsHelperToolsRegistrar.register writes into a funcId-keyed map, so a
        // second pass replaces rather than accumulates — but assert the guard
        // itself tolerates the duplicate even if a collection ever carried both.
        List<McpToolHandler> handlers = List.of(
            new StubHandler("__mesh_jobs_helper.__mesh_job_status", "__mesh_job_status",
                "__mesh_job_status"),
            new StubHandler("__mesh_jobs_helper.__mesh_job_status", "__mesh_job_status",
                "__mesh_job_status"));

        assertDoesNotThrow(() ->
            MeshMcpServerConfiguration.assertUniqueAdvertisedToolNames(handlers));
    }

    private static final class AlphaTools {}

    private static final class BetaTools {}
}
