package io.mcpmesh.spring;

import io.mcpmesh.JobProxy;
import io.mcpmesh.core.MeshException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Handlers for the three framework-internal MeshJob helper tools (Phase B
 * — MeshJob substrate). Auto-registered on every Java mesh agent
 * regardless of whether the agent owns any {@code task=true} tools, so
 * any MCP client can poll job status / result / cancel by calling any
 * agent.
 *
 * <p>The handlers are thin shims around {@link JobProxy} — all reads /
 * cancels terminate at the registry's {@code GET /jobs/{id}} /
 * {@code POST /jobs/{id}/cancel}. No replica-side caching, no owner-
 * bound routing for reads (matches the "Status read path" decision in
 * {@code MESHJOB_DESIGN.org}).
 *
 * <p>Mirror of:
 * <ul>
 *   <li>Python {@code _mcp_mesh.pipeline.mcp_startup.jobs_helper_tools}</li>
 *   <li>TypeScript {@code @mcp-mesh/runtime jobs-helper-tools.ts}</li>
 * </ul>
 *
 * <p>Tool names use a {@code __mesh_job_} prefix so MCP clients can
 * filter them out of user-facing tool lists if desired. Reading is
 * unauthenticated by design — knowledge of the job_id is the capability
 * (presigned-URL semantics, ~122-bit UUID).
 */
public final class JobsHelperToolHandler implements McpToolHandler {

    private static final Logger log = LoggerFactory.getLogger(JobsHelperToolHandler.class);

    public static final String TOOL_NAME_STATUS = "__mesh_job_status";
    public static final String TOOL_NAME_RESULT = "__mesh_job_result";
    public static final String TOOL_NAME_CANCEL = "__mesh_job_cancel";

    enum Op {
        STATUS, RESULT, CANCEL;

        String toolName() {
            return switch (this) {
                case STATUS -> TOOL_NAME_STATUS;
                case RESULT -> TOOL_NAME_RESULT;
                case CANCEL -> TOOL_NAME_CANCEL;
            };
        }

        String description() {
            return switch (this) {
                case STATUS -> "[Framework] Return the latest mesh-registry state for a "
                    + "job_id. Reads terminate at the registry; safe to call from any agent.";
                case RESULT -> "[Framework] Return the terminal result/status/error for a "
                    + "job_id via a single registry read.";
                case CANCEL -> "[Framework] Request cancellation for a job_id. The registry "
                    + "forwards the signal to the owner replica when alive.";
            };
        }
    }

    private final Op op;
    private final String registryUrl;

    JobsHelperToolHandler(Op op, String registryUrl) {
        this.op = op;
        this.registryUrl = registryUrl;
    }

    /** Build all three helper handlers bound to {@code registryUrl}. */
    public static List<JobsHelperToolHandler> all(String registryUrl) {
        return List.of(
            new JobsHelperToolHandler(Op.STATUS, registryUrl),
            new JobsHelperToolHandler(Op.RESULT, registryUrl),
            new JobsHelperToolHandler(Op.CANCEL, registryUrl)
        );
    }

    @Override
    public String getFuncId() {
        // Use a synthetic prefix so this never collides with a user-declared funcId
        return "__mesh_jobs_helper." + op.toolName();
    }

    @Override
    public String getCapability() {
        return op.toolName();
    }

    @Override
    public String getMethodName() {
        return op.toolName();
    }

    @Override
    public String getDescription() {
        return op.description();
    }

    @Override
    public Map<String, Object> getInputSchema() {
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        Map<String, Object> props = new LinkedHashMap<>();
        Map<String, Object> jobIdProp = new LinkedHashMap<>();
        jobIdProp.put("type", "string");
        jobIdProp.put("description", "Job UUID");
        props.put("job_id", jobIdProp);
        if (op == Op.CANCEL) {
            Map<String, Object> reasonProp = new LinkedHashMap<>();
            reasonProp.put("type", "string");
            reasonProp.put("description", "Optional cancel reason");
            props.put("reason", reasonProp);
        }
        schema.put("properties", props);
        schema.put("required", List.of("job_id"));
        return schema;
    }

    @Override
    public Object invoke(Map<String, Object> mcpArgs) throws Exception {
        if (mcpArgs == null) {
            throw new IllegalArgumentException("Missing required parameter: job_id");
        }
        Object jobIdObj = mcpArgs.get("job_id");
        if (!(jobIdObj instanceof String jobId) || jobId.isEmpty()) {
            throw new IllegalArgumentException("job_id must be a non-empty string");
        }
        if (registryUrl == null || registryUrl.isEmpty()) {
            throw new MeshException(op.toolName() + ": no registry URL configured");
        }

        try (JobProxy proxy = JobProxy.open(jobId, registryUrl)) {
            return switch (op) {
                case STATUS -> proxy.status();
                case RESULT -> {
                    Map<String, Object> snapshot = proxy.status();
                    Map<String, Object> out = new LinkedHashMap<>();
                    out.put("status", snapshot.get("status"));
                    out.put("result", snapshot.get("result"));
                    out.put("error", snapshot.get("error"));
                    yield out;
                }
                case CANCEL -> {
                    String reason = mcpArgs.get("reason") instanceof String s ? s : null;
                    proxy.cancel(reason);
                    Map<String, Object> ok = new LinkedHashMap<>();
                    ok.put("ok", true);
                    ok.put("job_id", jobId);
                    yield ok;
                }
            };
        } catch (Exception e) {
            log.warn("{} failed for job_id={}: {}", op.toolName(), jobId, e.getMessage());
            throw e;
        }
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
