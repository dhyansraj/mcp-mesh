/**
 * MeshJob Phase 2 — TypeScript Consumer Example: drive an event-aware job (v2.2).
 *
 * Demonstrates the three v2.2 event-channel surfaces from outside the
 * running handler:
 *
 *     const proxy = await eventAwareLongTask.submit({}, { maxDuration: 60 });
 *     // observer: mirror the stream via subscribeEvents
 *     // poster:  fire 3 'work' events + 1 'stop' via postEvent
 *     await proxy.wait!(30);
 *
 * The subscriber and the poster run concurrently. Each has its own
 * cursor: the in-handler `recvEvent` cursor on the producer side is
 * independent from the observer's `subscribeEvents` cursor — both
 * observe every `work` event the consumer posts.
 *
 * Pair this consumer with `../event-aware-provider-ts/src/index.ts`.
 * Run after the provider is up:
 *
 *     MCP_MESH_REGISTRY_URL=http://localhost:8000 npx tsx src/index.ts
 */
import { FastMCP } from "fastmcp";
import { mesh, type MeshJob } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Event-Aware Consumer (TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "event-aware-consumer-ts",
  httpPort: 9113,
  description:
    "MeshJob v2.2 consumer (TS) — drives an event-aware job via postEvent + subscribeEvents",
});

function sleepMs(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

agent.addTool({
  name: "drive_event_aware_task",
  capability: "drive_event_aware_task",
  // Dep[0] is task=true → the slot is wired as a MeshJobSubmitter.
  dependencies: [{ capability: "event_aware_long_task" }],
  meshJobDepIndex: 0,
  description:
    "Submit an event-aware job, post 3 'work' events + 1 'stop', " +
    "mirror the stream via subscribeEvents, and return both halves.",
  parameters: z.object({}).passthrough(),
  execute: async (
    _args,
    eventAwareLongTask: MeshJob | null = null,
  ) => {
    if (!eventAwareLongTask?.submit) {
      return { error: "event_aware_long_task submitter not injected" };
    }

    const proxy = await eventAwareLongTask.submit({}, { maxDuration: 60 });
    const jobId = (proxy as { jobId?: string }).jobId ?? "";

    // Brief wait so the producer claims the job + parks on recvEvent
    // before the first event lands. Without this the event would still
    // be observable (the log is append-only), but we wouldn't be
    // exercising the long-poll wake path.
    await sleepMs(2000);

    const observed: Array<{ seq: number; payload: unknown }> = [];

    async function runSubscriber(): Promise<void> {
      for await (const event of mesh.jobs.subscribeEvents(jobId, {
        types: ["work"],
        longPollSecs: 5,
      })) {
        observed.push({ seq: event.seq, payload: event.payload });
        if (observed.length >= 3) return;
      }
    }

    const subPromise = runSubscriber();

    const postedSeqs: number[] = [];
    for (let i = 1; i <= 3; i++) {
      await sleepMs(500);
      const receipt = await mesh.jobs.postEvent(jobId, "work", { item: i });
      postedSeqs.push(receipt.seq);
    }
    await mesh.jobs.postEvent(jobId, "stop", {});

    // Bound the subscriber wait so a stuck observer doesn't hang the
    // tool call. We can't cancel the underlying long-poll from JS, but
    // we can stop awaiting it.
    // On timeout, suppress the subscriber promise's eventual rejection (or
    // resolution) to avoid an unhandled-rejection warning when we abandon
    // the wait. We CANNOT actually cancel the underlying long-poll from
    // here — `proxy.listEvents` is a fire-and-forget native await and JS
    // has no cancellation primitive for it. The subscriber will continue
    // to long-poll for up to `longPollSecs` after we report
    // subscriber_status="timeout" before resolving naturally. Plumbing an
    // AbortController through the napi layer would close this leak window
    // but is out of scope for this example.
    try {
      await Promise.race([
        subPromise,
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("subscriber_timeout")), 15000),
        ),
      ]);
    } catch {
      subPromise.catch(() => {});
    }

    let result: unknown = null;
    if (proxy.wait) {
      result = await proxy.wait(30);
    }
    return {
      job_id: jobId,
      posted_seqs: postedSeqs,
      observed_count: observed.length,
      observed_events: observed,
      result,
    };
  },
});

console.log("event-aware-consumer-ts agent defined. Waiting for auto-start...");
