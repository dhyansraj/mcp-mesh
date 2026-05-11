/**
 * uc29_a2a_producer_ts fixture (long-running) — TS A2A producer
 * exposing the generate-report skill via mesh.a2a.mount on top of the
 * existing generate_report task=true capability served by the
 * long-task-provider Python agent on port 9100. Returns a JobProxy to
 * trigger the framework's long-running mode (parks the task in the A2A
 * task store, services tasks/get, tasks/cancel, tasks/sendSubscribe,
 * tasks/resubscribe from it).
 *
 * Issue #936: the MeshJobSubmitter is auto-injected as the third
 * positional handler arg — capability derives from skillId
 * ("generate-report" → "generate_report"). No more hand-construction
 * from getApiRuntime().getServiceId() + MCP_MESH_REGISTRY_URL.
 */
const HTTP_PORT = parseInt(
  (process.env.MCP_MESH_HTTP_PORT = process.env.MCP_MESH_HTTP_PORT ?? "9091"),
  10,
);
process.env.MCP_MESH_AGENT_NAME =
  process.env.MCP_MESH_AGENT_NAME ?? "report-a2a-agent";

import express from "express";
import { mesh } from "@mcpmesh/sdk";

const app = express();
app.use(express.json());

mesh.a2a.mount(
  app,
  {
    path: "/agents/report",
    skillId: "generate-report",
    skillName: "Generate Report",
    description: "Generate a long-form report via A2A (task=True streaming)",
    tags: ["reports", "long-running"],
  },
  async (_deps, payload, jobSubmitter) => {
    let userId = "anon";
    let sections: string[] = ["overview"];
    const parts =
      (payload?.parts as Array<{ type?: string; text?: string }> | undefined) ?? [];
    if (parts.length > 0 && parts[0]?.type === "text" && parts[0].text) {
      try {
        const args = JSON.parse(parts[0].text) as {
          user_id?: string;
          sections?: string[];
        };
        if (typeof args.user_id === "string" && args.user_id.length > 0) {
          userId = args.user_id;
        }
        if (Array.isArray(args.sections) && args.sections.length > 0) {
          sections = args.sections.map(String);
        }
      } catch {
        // Tolerant: keep defaults on parse failure.
      }
    }

    if (!jobSubmitter) {
      throw new Error(
        "MeshJobSubmitter not yet available — mesh runtime is still " +
          "initialising. Retry tasks/send shortly.",
      );
    }

    const proxy = await jobSubmitter.submit({
      user_id: userId,
      sections,
    });
    console.log(`[uc29] submitted job_id=${proxy.jobId} — parking in A2A store`);
    return proxy;
  },
);

app.listen(HTTP_PORT, () => {
  console.log(`Report A2A Producer (TS, uc29, long-running) on port ${HTTP_PORT}`);
});
