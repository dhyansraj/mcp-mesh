/**
 * Dual-dependency consumer for dep_index alignment test (issue #572).
 *
 * Declares two dependencies in specific order:
 *   dep_index=0: student_lookup (from alpha provider)
 *   dep_index=1: schedule_lookup (from beta provider)
 *
 * If dep_index alignment is broken, when only beta is running:
 *   - dep 0 would incorrectly appear available (beta wired to wrong index)
 *   - dep 1 would incorrectly appear unavailable
 */

import { FastMCP, mesh, type McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "ts-dual-consumer",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "ts-dual-consumer",
  httpPort: 9065,
});

agent.addTool({
  name: "check_enrollment",
  capability: "enrollment_check",
  description: "Check enrollment using student and schedule data",
  tags: ["consumer", "dual-dep"],
  dependencies: [
    { capability: "student_lookup" },    // dep_index=0 -> alpha provider
    { capability: "schedule_lookup" },   // dep_index=1 -> beta provider
  ],
  parameters: z.object({
    id: z.string().describe("Student ID"),
  }),
  execute: async (
    { id },
    student_service: McpMeshTool | null = null,
    schedule_service: McpMeshTool | null = null
  ) => {
    const result: Record<string, any> = {
      student_available: student_service !== null,
      schedule_available: schedule_service !== null,
      student: null,
      schedule: null,
    };

    if (student_service) {
      try {
        result.student = await student_service({ id });
      } catch (e: any) {
        result.student_error = e.message;
      }
    }

    if (schedule_service) {
      try {
        result.schedule = await schedule_service({ id });
      } catch (e: any) {
        result.schedule_error = e.message;
      }
    }

    return result;
  },
});

console.log("ts-dual-consumer defined. Waiting for auto-start...");
