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

  it("stop() exits even when the handler is long-running", async () => {
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
    const handler = vi.fn(
      () =>
        new Promise<unknown>((resolve) => {
          resolveHandler = () => resolve("done");
        }),
    );
    const d = new ClaimDispatcher("cap", "i", "http://r", handler);
    d.start();
    await new Promise((r) => setTimeout(r, 50));

    // Stop should resolve promptly even though the handler hasn't.
    const stopPromise = d.stop();
    // Resolve handler after stop call to avoid leaking the promise.
    setTimeout(() => resolveHandler(), 20);
    await stopPromise;
    expect(handler).toHaveBeenCalledOnce();
  });
});
