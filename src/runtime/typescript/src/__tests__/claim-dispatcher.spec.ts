/**
 * Tests for ClaimDispatcher (Phase 1 — MeshJob substrate).
 *
 * The dispatcher polls `POST /jobs/claim` periodically and dispatches
 * claimed work via the local handler. Heavy on side effects, so tests
 * use a stubbed `fetch` and a minimal handler — we exercise:
 *
 *   - Empty-claim behaviour (HTTP 204 → backoff, no handler call).
 *   - Successful claim → handler invoked with payload, controller
 *     constructed via napi.
 *   - The claim-then-acquire ordering: even with an immediate claim,
 *     the dispatcher must hold a permit before issuing the POST so
 *     it never owns more jobs than it can run.
 *   - Stop semantics: a long-running handler doesn't block stop().
 *
 * The napi `JobController` constructor is real — it doesn't reach out
 * to the registry until `complete()`/`updateProgress()` is called, so
 * the test stays in-process.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ClaimDispatcher } from "../claim-dispatcher.js";
import { getCurrentPropagatedHeaders } from "../proxy.js";
import * as inboundDispatch from "../inbound-job-dispatch.js";

// Mock @mcpmesh/core so the real JobController/withJobAsync don't
// actually try to reach the registry. The dispatcher uses `fetch`
// directly for /jobs/claim (mocked separately below).
vi.mock("@mcpmesh/core", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@mcpmesh/core");
  return {
    ...actual,
    // The dispatcher constructs JobController via makeJobController
    // (which calls `new JobController(...)`). Replace with a stub so
    // the constructor doesn't spawn the per-controller batching tick
    // (which would keep the test process alive past the test).
    JobController: class {
      jobId: string;
      constructor(jobId: string, _instanceId: string, _registryUrl: string) {
        this.jobId = jobId;
      }
      isTerminal = vi.fn().mockResolvedValue(true);
      complete = vi.fn().mockResolvedValue(undefined);
      fail = vi.fn().mockResolvedValue(undefined);
      updateProgress = vi.fn().mockResolvedValue(undefined);
    },
    // withJobAsync just runs the body without binding the Rust
    // task-local — fine for a test.
    withJobAsync: vi.fn(async (
      _jobId: string,
      _deadline: number | null,
      body: Promise<unknown>,
    ) => body),
  };
});

const originalFetch = globalThis.fetch;

describe("ClaimDispatcher", () => {
  beforeEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = vi.fn();
  });
  afterEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = originalFetch;
  });

  it("polls /jobs/claim and skips when registry returns 204 (no work)", async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue({
      status: 204,
      json: async () => ({}),
    } as unknown as Response);

    const handler = vi.fn().mockResolvedValue("ok");
    const d = new ClaimDispatcher(
      "cap",
      "agent-instance",
      "http://reg",
      handler,
    );
    d.start();
    await new Promise((r) => setTimeout(r, 50));
    await d.stop();

    expect(fetchMock).toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();

    // Check the URL + body the dispatcher used to claim.
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://reg/jobs/claim");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body.capability).toBe("cap");
    expect(body.instance_id).toBe("agent-instance");
  });

  it("dispatches a claimed job to the handler with the submitted payload", async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    let calls = 0;
    fetchMock.mockImplementation(async () => {
      calls += 1;
      // First poll returns one claim; subsequent polls return empty
      // so the dispatcher backs off and the test can stop cleanly.
      if (calls === 1) {
        return {
          status: 200,
          json: async () => ({
            claimed: [
              {
                id: "job-uuid-1",
                submitted_payload: { user_id: "u", n: 5 },
                max_duration: 30,
              },
            ],
          }),
        } as unknown as Response;
      }
      return { status: 204, json: async () => ({}) } as unknown as Response;
    });

    const handler = vi.fn().mockResolvedValue({ done: true });
    const d = new ClaimDispatcher("cap", "agent-instance", "http://reg", handler);
    d.start();
    await new Promise((r) => setTimeout(r, 100));
    await d.stop();

    expect(handler).toHaveBeenCalledOnce();
    const [payload, ctrl] = handler.mock.calls[0];
    expect(payload).toEqual({ user_id: "u", n: 5 });
    expect(ctrl).toBeDefined();
    // Stub controller exposes jobId.
    expect((ctrl as { jobId: string }).jobId).toBe("job-uuid-1");
  });

  it("treats malformed claim responses as no work (no crash, no handler call)", async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue({
      status: 200,
      json: async () => ({ claimed: "not-a-list" }),
    } as unknown as Response);

    const handler = vi.fn();
    const d = new ClaimDispatcher("cap", "i", "http://r", handler);
    d.start();
    await new Promise((r) => setTimeout(r, 50));
    await d.stop();
    expect(handler).not.toHaveBeenCalled();
  });

  it("filters out claimed entries without an id", async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    let calls = 0;
    fetchMock.mockImplementation(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          status: 200,
          json: async () => ({
            claimed: [
              { not_an_id: true },
              { id: "" },
              { id: "real-job", submitted_payload: {} },
            ],
          }),
        } as unknown as Response;
      }
      return { status: 204, json: async () => ({}) } as unknown as Response;
    });

    const handler = vi.fn().mockResolvedValue("done");
    const d = new ClaimDispatcher("cap", "i", "http://r", handler);
    d.start();
    await new Promise((r) => setTimeout(r, 100));
    await d.stop();
    expect(handler).toHaveBeenCalledOnce();
    expect(handler.mock.calls[0][1].jobId).toBe("real-job");
  });

  it("seeds the propagated-headers ALS with x-mesh-job-id (and x-mesh-timeout when present)", async () => {
    // Verifies follow-up #2: claim-path dispatches must seed the
    // propagated-headers AsyncLocalStorage so outbound calls made by
    // the handler continue the submitter's trace tree (Python parity
    // — see `_mcp_mesh.engine.claim_dispatcher.PythonClaimDispatcher
    // ._dispatch`'s `TraceContext.set_propagated_headers` block).
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    let calls = 0;
    fetchMock.mockImplementation(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          status: 200,
          json: async () => ({
            claimed: [
              {
                id: "job-trace-1",
                submitted_payload: { foo: "bar" },
                max_duration: 45,
              },
            ],
          }),
        } as unknown as Response;
      }
      return { status: 204, json: async () => ({}) } as unknown as Response;
    });

    let observed: Record<string, string> | null = null;
    const handler = vi.fn(async () => {
      // Snapshot the ALS view from inside the user handler — exactly
      // where outbound proxy calls would read it.
      observed = { ...getCurrentPropagatedHeaders() };
      return { ok: true };
    });
    const d = new ClaimDispatcher("cap-trace", "agent-1", "http://reg", handler);
    d.start();
    await new Promise((r) => setTimeout(r, 100));
    await d.stop();

    expect(handler).toHaveBeenCalledOnce();
    expect(observed).not.toBeNull();
    expect(observed!["x-mesh-job-id"]).toBe("job-trace-1");
    expect(observed!["x-mesh-timeout"]).toBe("45");
  });

  it("omits x-mesh-timeout when claim has no max_duration", async () => {
    // Defensive: a claim without max_duration must not seed an empty
    // / zero-valued timeout header (downstream parsers would reject it).
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    let calls = 0;
    fetchMock.mockImplementation(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          status: 200,
          json: async () => ({
            claimed: [{ id: "job-no-timeout", submitted_payload: {} }],
          }),
        } as unknown as Response;
      }
      return { status: 204, json: async () => ({}) } as unknown as Response;
    });

    let observed: Record<string, string> | null = null;
    const handler = vi.fn(async () => {
      observed = { ...getCurrentPropagatedHeaders() };
      return null;
    });
    const d = new ClaimDispatcher("cap-no-timeout", "i", "http://r", handler);
    d.start();
    await new Promise((r) => setTimeout(r, 100));
    await d.stop();

    expect(handler).toHaveBeenCalledOnce();
    expect(observed).not.toBeNull();
    expect(observed!["x-mesh-job-id"]).toBe("job-no-timeout");
    expect(observed!["x-mesh-timeout"]).toBeUndefined();
  });

  it("stop() closes the keep-alive http agent (no leaked sockets)", async () => {
    // Verifies follow-up #3: each ClaimDispatcher owns an undici Agent
    // for connection reuse on /jobs/claim polls; stop() must close
    // it so long-lived test harnesses don't leak sockets across
    // agent restarts.
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue({
      status: 204,
      json: async () => ({}),
    } as unknown as Response);

    const d = new ClaimDispatcher("cap-stop", "i", "http://r", vi.fn());
    // The Agent is private; reach in to verify close-state transitions.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const agent = (d as any)._httpAgent as {
      close: () => Promise<void>;
      destroyed: boolean;
      closed: boolean;
    };
    const closeSpy = vi.spyOn(agent, "close");

    d.start();
    await new Promise((r) => setTimeout(r, 30));
    await d.stop();

    // We invoke close() once from stop(); undici's DispatcherBase
    // re-enters close(callback) internally, which the spy records as
    // a second call. We only care that it was invoked (and that the
    // agent is now in the closed state).
    expect(closeSpy).toHaveBeenCalled();
    expect(agent.closed || agent.destroyed).toBe(true);
  });

  it("stop() drains in-flight handlers before closing the keep-alive pool", async () => {
    // Verifies the F7 follow-up: stop() must await any handler
    // dispatches that are still mid-fetch before it tears down the
    // shared `_httpAgent`. Without the drain, controller.complete /
    // controller.fail HTTP calls would race with Agent.close() and
    // surface as cryptic socket-closed errors — worse, the terminal
    // delta might never reach the registry, leaving the row stuck.
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    let calls = 0;
    fetchMock.mockImplementation(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          status: 200,
          json: async () => ({
            claimed: [{ id: "long", submitted_payload: {} }],
          }),
        } as unknown as Response;
      }
      return { status: 204, json: async () => ({}) } as unknown as Response;
    });

    let resolveHandler!: () => void;
    let handlerObservedFinish = false;
    const handler = vi.fn(
      () =>
        new Promise<unknown>((resolve) => {
          resolveHandler = () => {
            handlerObservedFinish = true;
            resolve("done");
          };
        }),
    );
    const d = new ClaimDispatcher("cap", "i", "http://r", handler);
    // The Agent is private; verify close ordering relative to handler
    // resolution. eslint-disable-next-line @typescript-eslint/no-explicit-any
    const httpAgent = (d as any)._httpAgent as { close: () => Promise<void> };
    let closedAt = 0;
    const closeSpy = vi.spyOn(httpAgent, "close").mockImplementation(async () => {
      closedAt = Date.now();
    });

    d.start();
    await new Promise((r) => setTimeout(r, 50));

    // Kick off stop(); resolve the handler ~20ms later.
    const stopStart = Date.now();
    const stopPromise = d.stop();
    let resolvedAt = 0;
    setTimeout(() => {
      resolvedAt = Date.now();
      resolveHandler();
    }, 20);
    await stopPromise;

    expect(handler).toHaveBeenCalledOnce();
    expect(handlerObservedFinish).toBe(true);
    // The keep-alive pool must close STRICTLY AFTER the handler
    // resolved — that's the whole point of the drain.
    expect(closeSpy).toHaveBeenCalled();
    expect(resolvedAt).toBeGreaterThan(0);
    expect(closedAt).toBeGreaterThanOrEqual(resolvedAt);
    // Sanity: stop() should still be quick — the bounded timeout is
    // 30s default, but we resolved at 20ms, so total wall < 1s.
    expect(Date.now() - stopStart).toBeLessThan(1000);

    closeSpy.mockRestore();
  });

  it("stop(timeoutMs=0) skips the drain when the caller asks for an immediate close", async () => {
    // Defensive: the bounded-drain default is 30s, but the caller can
    // pass `0` to force-close (e.g. tests that stub a long-running
    // handler and don't want to wait for it). Verify the path doesn't
    // hang on the in-flight handler.
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    let calls = 0;
    fetchMock.mockImplementation(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          status: 200,
          json: async () => ({
            claimed: [{ id: "never-finishes", submitted_payload: {} }],
          }),
        } as unknown as Response;
      }
      return { status: 204, json: async () => ({}) } as unknown as Response;
    });

    let resolveHandler!: () => void;
    const handler = vi.fn(
      () =>
        new Promise<unknown>((resolve) => {
          resolveHandler = () => resolve("done");
        }),
    );
    const d = new ClaimDispatcher("cap", "i", "http://r", handler);
    d.start();
    await new Promise((r) => setTimeout(r, 50));

    const t0 = Date.now();
    await d.stop(0);
    expect(Date.now() - t0).toBeLessThan(500);

    // Cleanup: resolve the dangling handler so it doesn't keep the
    // event loop alive past the test.
    resolveHandler();
  });

  it("posts a `failed` /jobs/batch delta when JobController construction throws (W2)", async () => {
    // Review finding W2: previously a `console.warn` + early return left
    // the registry believing this replica owned the job until lease
    // expiry, leaving the row stuck in `working`. The fix is to fire a
    // POST /jobs/batch failed delta directly (bypassing the controller
    // we couldn't construct) so the row flips terminal immediately and
    // unblocks retry.
    const ctorSpy = vi
      .spyOn(inboundDispatch, "makeJobController")
      .mockImplementation(() => {
        throw new Error("boom: napi binding refused");
      });

    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    let calls = 0;
    const claimUrl = "http://reg/jobs/claim";
    const batchUrl = "http://reg/jobs/batch";
    fetchMock.mockImplementation(async (url: string) => {
      calls += 1;
      if (url === claimUrl && calls === 1) {
        return {
          status: 200,
          json: async () => ({
            claimed: [
              {
                id: "job-broken-ctor",
                submitted_payload: { x: 1 },
              },
            ],
          }),
        } as unknown as Response;
      }
      if (url === batchUrl) {
        return { status: 200, json: async () => ({}) } as unknown as Response;
      }
      return { status: 204, json: async () => ({}) } as unknown as Response;
    });

    const handler = vi.fn();
    const d = new ClaimDispatcher("cap-broken", "agent-x", "http://reg", handler);
    d.start();
    await new Promise((r) => setTimeout(r, 100));
    await d.stop();

    // Handler must NOT have been invoked — the dispatcher bailed before
    // calling it because we couldn't build a controller.
    expect(handler).not.toHaveBeenCalled();

    // The fail-fast path must have POSTed a `failed` delta to /jobs/batch.
    const batchCall = fetchMock.mock.calls.find(
      (call) => call[0] === batchUrl,
    );
    expect(batchCall, "expected a POST /jobs/batch fail-fast call").toBeDefined();
    const init = batchCall![1] as RequestInit;
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.instance_id).toBe("agent-x");
    expect(body.deltas).toHaveLength(1);
    const delta = body.deltas[0];
    expect(delta.id).toBe("job-broken-ctor");
    expect(delta.status).toBe("failed");
    expect(typeof delta.error).toBe("string");
    expect(delta.error).toContain("controller construction failed");
    expect(delta.error).toContain("boom: napi binding refused");

    ctorSpy.mockRestore();
  });
});
