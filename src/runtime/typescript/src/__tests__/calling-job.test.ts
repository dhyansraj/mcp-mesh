/**
 * Issue #1263: propagate the CALLING job's identity on outbound tool calls via
 * a dedicated header pair, and expose a provider-side accessor.
 *
 * Carrier: `x-mesh-calling-job-id` / `x-mesh-calling-claim-epoch` — distinct
 * from the push-mode dispatch protocol's `x-mesh-job-id` / `x-mesh-claim-epoch`
 * (x-mesh-job-id doubles as the dispatch discriminator and cannot carry calling
 * identity).
 */
import { describe, it, expect, vi, afterEach } from "vitest";

// Keep the REAL core (real matchesPropagateHeader / injectTraceContext); only
// silence the span publisher and the never-resolving cancel await.
vi.mock("@mcpmesh/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mcpmesh/core")>();
  return {
    ...actual,
    publishSpan: vi.fn(async () => false),
    awaitJobCancel: vi.fn(() => new Promise<void>(() => {})),
  };
});
vi.mock("../http-pool.js", () => ({ getDispatcher: () => undefined }));

import {
  callingJob,
  callMcpTool,
  DEFAULT_CALL_OPTIONS,
  runWithPropagatedHeaders,
} from "../proxy.js";
import { matchesPropagateHeader } from "../tracing.js";
import { CURRENT_JOB, type JobContextSnapshot } from "../job-context.js";

describe("allowlist (issue #1263)", () => {
  it("always propagates the calling-* pair", () => {
    expect(matchesPropagateHeader("x-mesh-calling-job-id")).toBe(true);
    expect(matchesPropagateHeader("x-mesh-calling-claim-epoch")).toBe(true);
  });
  it("does NOT allowlist the dispatch pair (reverted)", () => {
    expect(matchesPropagateHeader("x-mesh-job-id")).toBe(false);
    expect(matchesPropagateHeader("x-mesh-claim-epoch")).toBe(false);
  });
  it("is case-insensitive", () => {
    expect(matchesPropagateHeader("X-Mesh-Calling-Job-Id")).toBe(true);
  });
});

describe("callingJob() accessor (issue #1263)", () => {
  it("returns null outside a job", () => {
    expect(callingJob()).toBeNull();
  });
  it("returns null when no calling job id", () => {
    runWithPropagatedHeaders({ "x-mesh-calling-claim-epoch": "7" }, () => {
      expect(callingJob()).toBeNull();
    });
  });
  it("does NOT read the dispatch pair", () => {
    runWithPropagatedHeaders(
      { "x-mesh-job-id": "job-self", "x-mesh-claim-epoch": "3" },
      () => {
        expect(callingJob()).toBeNull();
      },
    );
  });
  it("returns jobId + claimEpoch from the calling-* pair", () => {
    runWithPropagatedHeaders(
      {
        "x-mesh-calling-job-id": "job-abc",
        "x-mesh-calling-claim-epoch": "5",
      },
      () => {
        expect(callingJob()).toEqual({ jobId: "job-abc", claimEpoch: 5 });
      },
    );
  });
  it("claimEpoch is null when only calling job id present", () => {
    runWithPropagatedHeaders({ "x-mesh-calling-job-id": "job-xyz" }, () => {
      expect(callingJob()).toEqual({ jobId: "job-xyz", claimEpoch: null });
    });
  });
  it("malformed epoch degrades to null", () => {
    runWithPropagatedHeaders(
      { "x-mesh-calling-job-id": "job-1", "x-mesh-calling-claim-epoch": "5.5" },
      () => {
        expect(callingJob()?.claimEpoch).toBeNull();
      },
    );
  });
});

describe("outbound overlay (issue #1263)", () => {
  let captured: RequestInit | undefined;

  function mockFetch(): void {
    captured = undefined;
    globalThis.fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
      captured = init;
      const body = JSON.stringify({
        jsonrpc: "2.0",
        id: "x",
        result: { content: [{ type: "text", text: "{}" }] },
      });
      return {
        ok: true,
        status: 200,
        statusText: "OK",
        text: async () => body,
        headers: {
          get: (n: string) =>
            n.toLowerCase() === "content-type" ? "application/json" : null,
        },
      } as unknown as Response;
    }) as unknown as typeof fetch;
  }

  function capturedHeaders(): Record<string, string> {
    return (captured?.headers ?? {}) as Record<string, string>;
  }
  function capturedMeshHeaders(): Record<string, string> {
    const body = JSON.parse((captured?.body as string) ?? "{}");
    return (body?.params?.arguments?._mesh_headers ?? {}) as Record<
      string,
      string
    >;
  }

  function snap(jobId: string, claimEpoch: number | null): JobContextSnapshot {
    return { jobId, deadlineSecsRemaining: null, claimEpoch };
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("no active job → no calling-* seeded", async () => {
    mockFetch();
    await callMcpTool("http://d:9000", "t", { a: 1 }, DEFAULT_CALL_OPTIONS, "cap");
    expect(capturedHeaders()["x-mesh-calling-job-id"]).toBeUndefined();
  });

  it("seeds both from the active job snapshot", async () => {
    mockFetch();
    await CURRENT_JOB.run(snap("job-A", 4), async () => {
      await callMcpTool("http://d:9000", "t", {}, DEFAULT_CALL_OPTIONS, "cap");
    });
    expect(capturedHeaders()["x-mesh-calling-job-id"]).toBe("job-A");
    expect(capturedHeaders()["x-mesh-calling-claim-epoch"]).toBe("4");
    // Also carried in the _mesh_headers args (FastMCP-visible path).
    expect(capturedMeshHeaders()["x-mesh-calling-job-id"]).toBe("job-A");
  });

  it("seeds id only when the snapshot has no epoch", async () => {
    mockFetch();
    await CURRENT_JOB.run(snap("job-A", null), async () => {
      await callMcpTool("http://d:9000", "t", {}, DEFAULT_CALL_OPTIONS, "cap");
    });
    expect(capturedHeaders()["x-mesh-calling-job-id"]).toBe("job-A");
    expect(capturedHeaders()["x-mesh-calling-claim-epoch"]).toBeUndefined();
  });

  it("replaces an inherited pair entirely — no stale epoch rides along", async () => {
    mockFetch();
    await runWithPropagatedHeaders(
      {
        "x-mesh-calling-job-id": "job-OLD",
        "x-mesh-calling-claim-epoch": "99",
      },
      async () => {
        await CURRENT_JOB.run(snap("job-NEW", null), async () => {
          await callMcpTool("http://d:9000", "t", {}, DEFAULT_CALL_OPTIONS, "cap");
        });
      },
    );
    expect(capturedHeaders()["x-mesh-calling-job-id"]).toBe("job-NEW");
    expect(capturedHeaders()["x-mesh-calling-claim-epoch"]).toBeUndefined();
  });

  it("passes an inherited pair through when there is no active job", async () => {
    mockFetch();
    await runWithPropagatedHeaders(
      {
        "x-mesh-calling-job-id": "job-UP",
        "x-mesh-calling-claim-epoch": "2",
      },
      async () => {
        await callMcpTool("http://d:9000", "t", {}, DEFAULT_CALL_OPTIONS, "cap");
      },
    );
    expect(capturedHeaders()["x-mesh-calling-job-id"]).toBe("job-UP");
    expect(capturedHeaders()["x-mesh-calling-claim-epoch"]).toBe("2");
  });
});
