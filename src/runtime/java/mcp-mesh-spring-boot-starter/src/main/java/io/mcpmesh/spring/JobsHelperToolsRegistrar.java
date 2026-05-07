package io.mcpmesh.spring;

import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshObjectMappers;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Auto-registers the three MeshJob helper tools (Phase B) on every Java
 * mesh agent — independent of whether the agent owns any
 * {@code task=true} tools. Mirror of:
 * <ul>
 *   <li>Python {@code _mcp_mesh.pipeline.mcp_startup.JobsHelperToolsStep}</li>
 *   <li>TypeScript {@code @mcp-mesh/runtime registerJobsHelperTools}</li>
 * </ul>
 *
 * <p>Two registrations are performed:
 * <ul>
 *   <li><b>Wrapper registry</b> — so MCP {@code tools/call} requests for
 *       the helper names land at {@link JobsHelperToolHandler}.</li>
 *   <li><b>Tool registry</b> (synthetic) — so the heartbeat advertises
 *       the helpers as capabilities in the registry's catalog. Without
 *       this, {@code meshctl call <agent> __mesh_job_status ...} would
 *       fail with "tool not found" because the registry doesn't know
 *       they exist (matches Python bug #5 fix).</li>
 * </ul>
 *
 * <p>Skipped when no {@code MCP_MESH_REGISTRY_URL} is configured —
 * without a registry to talk to, the helpers can't function.
 */
public final class JobsHelperToolsRegistrar {

    private static final Logger log = LoggerFactory.getLogger(JobsHelperToolsRegistrar.class);

    /**
     * Shared mapper — hoisted out of {@link #buildSyntheticSpec} which
     * would otherwise allocate two new {@code JsonMapper} instances per
     * helper tool (six per agent startup) just to serialize a tiny
     * schema. Matches the {@code static final} pattern used elsewhere
     * (e.g. {@link ClaimDispatcher}).
     */
    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    private JobsHelperToolsRegistrar() {}

    /**
     * Register the three helper tools with both registries.
     *
     * @param toolRegistry      Heartbeat catalog (synthetic tool spec)
     * @param wrapperRegistry   MCP dispatch registry (real handler)
     * @param registryUrl       Mesh registry base URL — handlers POST/GET against it
     */
    public static void register(
            MeshToolRegistry toolRegistry,
            MeshToolWrapperRegistry wrapperRegistry,
            String registryUrl) {

        if (registryUrl == null || registryUrl.isEmpty()) {
            log.info("MeshJob helper tools skipped: no registry URL configured");
            return;
        }

        List<JobsHelperToolHandler> handlers = JobsHelperToolHandler.all(registryUrl);
        for (JobsHelperToolHandler handler : handlers) {
            wrapperRegistry.registerHandler(handler);
            toolRegistry.addSyntheticTool(buildSyntheticSpec(handler));
        }
        log.info("Registered {} MeshJob helper tools (status, result, cancel) on this agent",
            handlers.size());
    }

    private static AgentSpec.ToolSpec buildSyntheticSpec(JobsHelperToolHandler handler) {
        AgentSpec.ToolSpec spec = new AgentSpec.ToolSpec();
        spec.setFunctionName(handler.getMethodName());
        spec.setCapability(handler.getCapability());
        spec.setDescription(handler.getDescription());
        spec.setVersion("1.0.0");
        spec.setTags(List.of("mesh-jobs", "framework"));
        // Build a minimal input schema string for the registry catalog.
        Map<String, Object> schema = handler.getInputSchema();
        try {
            String json = MAPPER.writeValueAsString(schema);
            spec.setInputSchema(json);
        } catch (Exception e) {
            // Fall through with empty schema — heartbeat will still register
            // the capability; only schema-aware matching loses precision.
            log.debug("Failed to serialize helper tool schema: {}", e.getMessage());
        }
        // Mark as framework-internal via kwargs so future filters can
        // distinguish helper tools from user-declared tools (matches the
        // Python "framework_internal: true" metadata flag).
        try {
            Map<String, Object> kwargs = new LinkedHashMap<>();
            kwargs.put("framework_internal", true);
            String kwargsJson = MAPPER.writeValueAsString(kwargs);
            spec.setKwargs(kwargsJson);
        } catch (Exception ignored) {
            // Best-effort; absence of the marker doesn't break dispatch.
        }
        return spec;
    }
}
