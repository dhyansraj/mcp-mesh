/**
 * MeshJob Phase 2 — TypeScript Producer Example: event-aware long task (v2.2).
 *
 * Demonstrates the producer-side event-channel surface added in v2.2:
 *
 *     agent.addTool({
 *       name: "event_aware_long_task",
 *       task: true,
 *       meshJobParamIndex: 1,
 *       execute: async (_args, controller: MeshJob | null = null) => {
 *         while (true) {
 *           const event = await controller!.recvEvent!(["work", "stop"], 30);
 *           // ...
 *         }
 *       },
 *     });
 *
 * Pattern: the handler drains a per-job event log inline. `recvEvent`
 * long-polls the registry; each invocation returns the next event
 * matching the type filter, or `null` if no event arrives within the
 * timeout budget. The `stop` event lets a remote caller cleanly shut
 * the loop down without having to `cancel()` the job.
 *
 * Pair this provider with `../event-aware-consumer-ts/src/index.ts`
 * for a full 3-terminal demo.
 *
 * Run:
 *     MCP_MESH_REGISTRY_URL=http://localhost:8000 npx tsx src/index.ts
 */
import { FastMCP } from "fastmcp";
import { mesh, type MeshJob } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Event-Aware Provider (TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "event-aware-provider-ts",
  httpPort: 9112,
  description:
    "MeshJob v2.2 producer (TS) — drains injected events via recvEvent",
});

agent.addTool({
  name: "event_aware_long_task",
  capability: "event_aware_long_task",
  task: true,
  // Sig pos 0 is the args object; the MeshJob controller lands at 1.
  meshJobParamIndex: 1,
  description:
    "Long-running task that drains injected events. Loops on " +
    "recvEvent(['work', 'stop']) and exits cleanly on 'stop'.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, controller: MeshJob | null = null) => {
    if (!controller?.recvEvent) {
      return { error: "no job controller injected" };
    }

    let processed = 0;
    while (true) {
      const event = await controller.recvEvent(["work", "stop"], 30);
      if (event === null) {
        // Long-poll budget elapsed with no matching event. In a real
        // producer this is a good moment to tick housekeeping
        // (refresh leases, write checkpoints) before re-parking.
        if (controller.updateProgress) {
          await controller.updateProgress(
            processed / (processed + 1),
            `idle, waiting for events (processed=${processed})`,
          );
        }
        continue;
      }

      if (event.type === "stop") {
        const payload = { processed, status: "stopped" };
        if (controller.complete) {
          await controller.complete(payload);
        }
        return payload;
      }

      // 'work' event — advance counter, log progress.
      processed += 1;
      if (controller.updateProgress) {
        await controller.updateProgress(
          Math.min(processed / 10.0, 0.99),
          `processed work item ${processed} (seq=${event.seq})`,
        );
      }
    }
  },
});

agent.addTool({
  name: "resumable_event_task",
  capability: "resumable_event_task",
  task: true,
  // Issue #1277: opt into durable cursor resume. On re-claim the handler
  // resumes recvEvent from the persisted per-filter cursor instead of
  // replaying its event log from seq 0, so the non-idempotent `total +=`
  // accumulation below is not re-applied for events already consumed.
  //   * At-least-once still holds: a bounded tail may replay on resume, so
  //     keep per-event effects tolerant of a rare repeat (or fence on seq).
  //   * Consumption MUST stay strictly sequential-per-filter: process each
  //     event fully before the next recvEvent. Do NOT prefetch or fan out to
  //     concurrent workers — the persisted cursor only advances correctly for
  //     in-order, one-at-a-time draining.
  resumeCursor: true,
  // Sig pos 0 is the args object; the MeshJob controller lands at 1.
  meshJobParamIndex: 1,
  description:
    "Durable variant of event_aware_long_task. Opts into resumeCursor so " +
    "a re-claimed run resumes after the last processed event instead of " +
    "replaying its event log from seq 0.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, controller: MeshJob | null = null) => {
    if (!controller?.recvEvent) {
      return { error: "no job controller injected" };
    }

    let total = 0;
    let processed = 0;
    while (true) {
      const event = await controller.recvEvent(["work", "stop"], 30);
      if (event === null) {
        continue;
      }

      if (event.type === "stop") {
        const payload = { processed, total, status: "stopped" };
        if (controller.complete) {
          await controller.complete(payload);
        }
        return payload;
      }

      // Sequential-per-filter: this non-idempotent accumulation runs once
      // per event, in order, before we request the next one.
      const amount =
        (event.payload as { amount?: number } | null)?.amount ?? 1;
      total += amount;
      processed += 1;
      if (controller.updateProgress) {
        await controller.updateProgress(
          Math.min(processed / 10.0, 0.99),
          `applied work item ${processed} (seq=${event.seq}, total=${total})`,
        );
      }
    }
  },
});

console.log("event-aware-provider-ts agent defined. Waiting for auto-start...");
