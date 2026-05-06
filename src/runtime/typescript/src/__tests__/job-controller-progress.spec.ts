/**
 * Regression test for the napi `JobController` constructor's batching tick.
 *
 * The `#[napi(constructor)]` is invoked synchronously from JS context with
 * NO ambient Tokio runtime — `Handle::try_current()` returns Err there,
 * so an earlier implementation silently skipped `spawn_batching_tick` and
 * mid-flight `updateProgress` calls accumulated in the coalescing queue
 * forever (only `complete()`/`fail()` flushed because those are async napi
 * methods that run inside napi-rs's Tokio runtime).
 *
 * The fix uses `napi::bindgen_prelude::within_runtime_if_available` so
 * the tick spawns inside napi-rs's shared runtime regardless of whether
 * the caller is sync or async — mirroring Python's pattern of entering
 * `pyo3_async_runtimes::tokio::get_runtime()`.
 *
 * This test spins up a tiny HTTP server playing the role of the registry,
 * constructs a real `JobController` against it, calls `updateProgress`,
 * and asserts that the batching tick eventually POSTs to `/jobs/batch`
 * with the queued delta — proving the tick actually runs.
 */
import { describe, it, expect } from "vitest";
import { JobController } from "@mcpmesh/core";
import http from "node:http";
import type { AddressInfo } from "node:net";

interface RecordedBatch {
  instance_id: string;
  deltas: Array<{
    id: string;
    progress?: number | null;
    progress_message?: string | null;
    status?: string | null;
  }>;
}

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

describe("JobController batching tick", () => {
  it("flushes updateProgress via the batching tick on a fake registry", async () => {
    const recorded: RecordedBatch[] = [];

    // Tiny registry mock: accept POST /jobs/batch, record body, return 200.
    const server = http.createServer((req, res) => {
      if (req.method === "POST" && req.url === "/jobs/batch") {
        readBody(req)
          .then((body) => {
            recorded.push(JSON.parse(body) as RecordedBatch);
            res.statusCode = 200;
            res.setHeader("content-type", "application/json");
            res.end(JSON.stringify({ accepted: 1, rejected: [] }));
          })
          .catch(() => {
            res.statusCode = 500;
            res.end();
          });
        return;
      }
      res.statusCode = 404;
      res.end();
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const port = (server.address() as AddressInfo).port;
    const registryUrl = `http://127.0.0.1:${port}`;

    try {
      // Construct a real napi JobController — this is the exact code path
      // that was broken: the constructor must spawn the batching tick on
      // napi-rs's runtime, not on `Handle::try_current()` (which returns
      // Err from a synchronous JS context).
      const ctrl = new JobController("job-batch-test", "inst-1", registryUrl);

      await ctrl.updateProgress(0.5, "halfway");

      // Default batching interval is 2s. Wait long enough for at least one
      // tick to fire. If the tick wasn't spawned, recorded stays empty.
      // Use 5s of slack so this isn't flaky on slow CI runners — 500ms
      // of headroom over a 2s tick was too tight, the cost of ~2.5s
      // extra wall time is acceptable for a single test.
      await new Promise((r) => setTimeout(r, 5000));

      expect(
        recorded.length,
        "batching tick must POST at least one batch with the queued progress delta",
      ).toBeGreaterThanOrEqual(1);

      const seen = recorded[0];
      expect(seen.instance_id).toBe("inst-1");
      expect(seen.deltas.length).toBe(1);
      expect(seen.deltas[0].id).toBe("job-batch-test");
      expect(seen.deltas[0].progress).toBeCloseTo(0.5, 5);
      expect(seen.deltas[0].progress_message).toBe("halfway");
      // Mid-flight delta — no terminal status.
      expect(seen.deltas[0].status ?? null).toBeNull();
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  }, 15_000);
});
