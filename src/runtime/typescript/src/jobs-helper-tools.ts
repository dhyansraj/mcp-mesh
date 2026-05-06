/**
 * Auto-register the three MeshJob helper tools on every TS mesh agent
 * (Phase 1 — MeshJob substrate).
 *
 * Mirrors Python's
 * `_mcp_mesh.pipeline.mcp_startup.jobs_helper_tools.JobsHelperToolsStep`.
 *
 * Per `MESHJOB_DESIGN.org` "Helper tool placement: auto-registered on
 * every mesh agent": `__mesh_job_status` / `__mesh_job_result` /
 * `__mesh_job_cancel` are framework primitives, exposed on every agent
 * that initialises the mesh runtime — independent of whether that
 * agent owns any `task: true` tools. External MCP clients can call any
 * agent to poll job status; the call lands at the registry, not at any
 * specific owner replica.
 *
 * The helpers are thin wrappers around `JobProxy` from `@mcpmesh/core`
 * (which terminates at the registry's `GET /jobs/{id}` /
 * `POST /jobs/{id}/cancel`). No replica-side caching, no owner-bound
 * routing for reads (per "Status read path" decision in design doc).
 */
import type { FastMCP } from "fastmcp";
import { z } from "zod";
import { JobProxy } from "@mcpmesh/core";

const TOOL_NAME_STATUS = "__mesh_job_status";
const TOOL_NAME_RESULT = "__mesh_job_result";
const TOOL_NAME_CANCEL = "__mesh_job_cancel";

const DESCRIPTIONS: Record<string, string> = {
  [TOOL_NAME_STATUS]:
    "[Framework] Return the latest mesh-registry state for a job_id. " +
    "Reads terminate at the registry; safe to call from any agent.",
  [TOOL_NAME_RESULT]:
    "[Framework] Return the terminal result/status/error for a job_id " +
    "via a single registry read.",
  [TOOL_NAME_CANCEL]:
    "[Framework] Request cancellation for a job_id. The registry " +
    "forwards the signal to the owner replica when alive.",
};

/**
 * Metadata stamp for the three helper tools — same shape `MeshAgent`
 * builds for user tools, so the Rust core ships them to the registry
 * as regular capabilities under the framework_internal=true tag.
 */
export interface HelperToolMeta {
  capability: string;
  version: string;
  tags: string[];
  description: string;
  inputSchema: string;
  task: boolean;
}

/**
 * Register `__mesh_job_status` / `__mesh_job_result` /
 * `__mesh_job_cancel` on the FastMCP server and return their mesh
 * metadata so the agent can ship them in the heartbeat tool catalog.
 *
 * Skipped if `registryUrl` is empty — without a registry there's
 * nothing for the helpers to read from. Returns an empty metadata map
 * in that case so the caller can still proceed with startup.
 *
 * Idempotent w.r.t. an already-registered tool name (FastMCP throws on
 * duplicate names; we catch + log so a hot-reload doesn't crash).
 */
export function registerJobHelperTools(
  server: FastMCP,
  registryUrl: string,
): Map<string, HelperToolMeta> {
  const meta = new Map<string, HelperToolMeta>();
  if (!registryUrl) {
    return meta;
  }

  const inputParams = z.object({
    jobId: z.string().describe("Job UUID returned by submit_job"),
  });
  const cancelParams = z.object({
    jobId: z.string().describe("Job UUID returned by submit_job"),
    reason: z.string().optional().describe("Optional reason string"),
  });

  // We pass JSON-stringified inputSchema downstream just like the user
  // tools do (see agent.ts addTool path).
  const inputSchemaJson = JSON.stringify({
    type: "object",
    properties: {
      jobId: { type: "string", description: "Job UUID returned by submit_job" },
    },
    required: ["jobId"],
  });
  const cancelSchemaJson = JSON.stringify({
    type: "object",
    properties: {
      jobId: { type: "string", description: "Job UUID returned by submit_job" },
      reason: { type: "string", description: "Optional reason string" },
    },
    required: ["jobId"],
  });

  // Status: GET /jobs/{id} via JobProxy.status()
  try {
    server.addTool({
      name: TOOL_NAME_STATUS,
      description: DESCRIPTIONS[TOOL_NAME_STATUS],
      parameters: inputParams,
      execute: async (args: { jobId: string }) => {
        const proxy = new JobProxy(args.jobId, registryUrl);
        const snapshot = await proxy.status();
        return JSON.stringify(snapshot);
      },
    });
    meta.set(TOOL_NAME_STATUS, {
      capability: TOOL_NAME_STATUS,
      version: "1.0.0",
      tags: ["mesh-jobs", "framework"],
      description: DESCRIPTIONS[TOOL_NAME_STATUS],
      inputSchema: inputSchemaJson,
      task: false,
    });
  } catch (err) {
    console.warn(`[mesh-jobs] could not register ${TOOL_NAME_STATUS}:`, err);
  }

  // Result: same wire as status; helper unwraps just the terminal bits.
  try {
    server.addTool({
      name: TOOL_NAME_RESULT,
      description: DESCRIPTIONS[TOOL_NAME_RESULT],
      parameters: inputParams,
      execute: async (args: { jobId: string }) => {
        const proxy = new JobProxy(args.jobId, registryUrl);
        const snapshot = (await proxy.status()) as Record<string, unknown>;
        return JSON.stringify({
          status: snapshot.status,
          result: snapshot.result,
          error: snapshot.error,
        });
      },
    });
    meta.set(TOOL_NAME_RESULT, {
      capability: TOOL_NAME_RESULT,
      version: "1.0.0",
      tags: ["mesh-jobs", "framework"],
      description: DESCRIPTIONS[TOOL_NAME_RESULT],
      inputSchema: inputSchemaJson,
      task: false,
    });
  } catch (err) {
    console.warn(`[mesh-jobs] could not register ${TOOL_NAME_RESULT}:`, err);
  }

  // Cancel: POST /jobs/{id}/cancel via JobProxy.cancel()
  try {
    server.addTool({
      name: TOOL_NAME_CANCEL,
      description: DESCRIPTIONS[TOOL_NAME_CANCEL],
      parameters: cancelParams,
      execute: async (args: { jobId: string; reason?: string }) => {
        const proxy = new JobProxy(args.jobId, registryUrl);
        await proxy.cancel(args.reason ?? null);
        return JSON.stringify({ ok: true, jobId: args.jobId });
      },
    });
    meta.set(TOOL_NAME_CANCEL, {
      capability: TOOL_NAME_CANCEL,
      version: "1.0.0",
      tags: ["mesh-jobs", "framework"],
      description: DESCRIPTIONS[TOOL_NAME_CANCEL],
      inputSchema: cancelSchemaJson,
      task: false,
    });
  } catch (err) {
    console.warn(`[mesh-jobs] could not register ${TOOL_NAME_CANCEL}:`, err);
  }

  return meta;
}
