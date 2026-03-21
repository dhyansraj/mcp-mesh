/**
 * media-consumer - MCP Mesh Media Consumer Agent
 *
 * Demonstrates consuming resource_links produced by another mesh agent.
 * Depends on the media-producer agent's capabilities (report_generator,
 * chart_generator) to show how media flows through the mesh.
 *
 * Run with:
 *   npm run start:consumer
 */

import { FastMCP, mesh, type McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Media Consumer", version: "1.0.0" });

const agent = mesh(server, {
  name: "media-consumer",
  httpPort: 9211,
  description: "Agent that consumes resource_links from the media-producer",
});

/**
 * Extract a resource_link from a tool result, handling both direct
 * resource_link objects and multi_content wrappers.
 */
function extractResourceLink(
  result: unknown
): Record<string, unknown> | null {
  if (!result || typeof result !== "object") return null;
  const obj = result as Record<string, unknown>;

  if (obj.type === "resource_link") return obj;

  if (
    obj.type === "multi_content" &&
    Array.isArray(obj.content) &&
    obj.content.length > 0
  ) {
    const inner = obj.content[0] as Record<string, unknown>;
    if (inner && inner.type === "resource_link") return inner;
  }

  return null;
}

function describeResourceLink(
  res: Record<string, unknown>,
  prefix: string
): string {
  const uri = res.uri ?? "unknown";
  const name = res.name ?? "unknown";
  const mime = res.mimeType ?? "unknown";
  const desc = res.description ?? "";
  const meta = res._meta as Record<string, unknown> | undefined;
  const size = meta?.size;
  const sizeInfo = size !== undefined ? `, size=${size} bytes` : "";
  return (
    `${prefix}:\n` +
    `  Name: ${name}\n` +
    `  URI:  ${uri}\n` +
    `  Type: ${mime}\n` +
    `  Description: ${desc}${sizeInfo}`
  );
}

agent.addTool({
  name: "summarize_report",
  capability: "report_summarizer",
  tags: ["media", "report"],
  description:
    "Requests a report from the producer and describes the received resource_link",
  dependencies: ["report_generator"],
  parameters: z.object({
    topic: z.string().default("AI").describe("Topic for the report"),
  }),
  execute: async (
    { topic },
    reportGenerator: McpMeshTool | null = null
  ) => {
    if (!reportGenerator) {
      return "Error: report_generator dependency not available";
    }

    const result = await reportGenerator({ topic });
    const resLink = extractResourceLink(result);

    if (resLink) {
      return describeResourceLink(
        resLink,
        "Received resource_link from media-producer"
      );
    }

    return `Received non-resource_link result: ${JSON.stringify(result)}`;
  },
});

agent.addTool({
  name: "describe_media",
  capability: "media_describer",
  tags: ["media", "chart"],
  description:
    "Requests a chart from the producer and describes the received media",
  dependencies: ["chart_generator"],
  parameters: z.object({
    data: z
      .string()
      .default("Q1:30,Q2:45,Q3:60,Q4:50")
      .describe("Data as 'Label:Value,...' pairs"),
  }),
  execute: async (
    { data },
    chartGenerator: McpMeshTool | null = null
  ) => {
    if (!chartGenerator) {
      return "Error: chart_generator dependency not available";
    }

    const result = await chartGenerator({ data });
    const resLink = extractResourceLink(result);

    if (resLink) {
      return describeResourceLink(
        resLink,
        "Received chart media from media-producer"
      );
    }

    return `Received non-resource_link result: ${JSON.stringify(result)}`;
  },
});

console.log("media-consumer agent defined. Waiting for auto-start...");
console.log("Dependencies: report_generator, chart_generator (from media-producer)");
