/**
 * Issue #1570: the cross-runtime `x-mesh-job-id` contract.
 *
 * `x-mesh-job-id` is the push-mode dispatch DISCRIMINATOR. It is read from the
 * RAW inbound `_mesh_headers` map and is never emitted on an outbound call.
 *
 * Two defects are pinned here:
 *
 * 1. The dispatch site read the allowlist-FILTERED map while the required-dep
 *    guard read the raw one, so a genuine inbound job dispatch never built a
 *    JobController (push-mode dispatch over HTTP was unreachable).
 * 2. The claim dispatcher seeded `x-mesh-job-id` into the propagated store that
 *    every outbound call forwards, so a nested call into a `task:true` tool
 *    whose required dependency was down released the CALLER's lease and
 *    returned `""` instead of the `dependency_unavailable` refusal.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { UserError } from "fastmcp";

const h = vi.hoisted(() => {
  const completeMock = vi.fn(async () => {});
  const releaseLeaseMock = vi.fn(async () => {});
  const makeJobControllerMock = vi.fn(() => ({
    complete: completeMock,
    releaseLease: releaseLeaseMock,
    close: vi.fn(async () => {}),
  }));
  return { completeMock, releaseLeaseMock, makeJobControllerMock };
});

vi.mock("../inbound-job-dispatch.js", async (importActual) => {
  const actual =
    await importActual<typeof import("../inbound-job-dispatch.js")>();
  return {
    ...actual,
    makeJobController:
      h.makeJobControllerMock as unknown as typeof actual.makeJobController,
    // Bind CURRENT_JOB (so outbound calls seed calling identity exactly as in
    // production) without touching the napi job context / cancel watcher.
    runWithJobContext: (async (
      jobId: string | null,
      deadlineSecs: number | null,
      _controller: unknown,
      body: () => Promise<unknown>,
      _retryOn?: unknown,
      claimEpoch?: number | null,
    ) => {
      const { CURRENT_JOB } = await import("../job-context.js");
      if (!jobId) return body();
      return CURRENT_JOB.run(
        {
          jobId,
          deadlineSecsRemaining: deadlineSecs,
          claimEpoch: claimEpoch ?? null,
        },
        body,
      );
    }) as unknown as typeof actual.runWithJobContext,
  };
});

import { MeshAgent } from "../agent.js";
import { RouteRegistry } from "../route.js";
import { resetSettleStateForTests } from "../settle.js";
import { callMcpTool, DEFAULT_CALL_OPTIONS, runWithPropagatedHeaders } from "../proxy.js";
import { ClaimDispatcher } from "../claim-dispatcher.js";

function makeFastMCPStub() {
  return {
    addTool: vi.fn(),
    start: vi.fn(),
    getApp: vi.fn(),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function captureExecute(fastmcp: any): (args: unknown) => Promise<string> {
  return fastmcp.addTool.mock.calls[0][0].execute as (
    args: unknown,
  ) => Promise<string>;
}

let autoStartSpy: ReturnType<typeof vi.spyOn> | null = null;
let warnSpy: ReturnType<typeof vi.spyOn> | null = null;
const savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  h.completeMock.mockClear();
  h.releaseLeaseMock.mockClear();
  h.makeJobControllerMock.mockClear();
  autoStartSpy = vi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .spyOn(MeshAgent.prototype as any, "_autoStart")
    .mockImplementation(async () => {
      /* no-op */
    });
  warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {
    /* swallow */
  });
  savedEnv.MCP_MESH_SETTLE_TIMEOUT = process.env.MCP_MESH_SETTLE_TIMEOUT;
  savedEnv.MCP_MESH_TOOL_ISOLATION = process.env.MCP_MESH_TOOL_ISOLATION;
  process.env.MCP_MESH_TOOL_ISOLATION = "false";
  process.env.MCP_MESH_SETTLE_TIMEOUT = "0";
  resetSettleStateForTests();
  RouteRegistry.reset();
});

afterEach(async () => {
  await new Promise<void>((resolve) => process.nextTick(resolve));
  autoStartSpy?.mockRestore();
  autoStartSpy = null;
  warnSpy?.mockRestore();
  warnSpy = null;
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  resetSettleStateForTests();
  RouteRegistry.reset();
  vi.restoreAllMocks();
});

describe("inbound dispatch reads the RAW header map (#1570)", () => {
  it("builds a JobController for a task tool carrying x-mesh-job-id", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "dispatch-agent", httpPort: 0 });
    const seen: unknown[] = [];
    agent.addTool({
      name: "render",
      task: true,
      parameters: z.object({}),
      meshJobParamIndex: 1,
      execute: async (_args: unknown, job: unknown) => {
        seen.push(job);
        return "ran";
      },
    });
    const execute = captureExecute(fastmcp);

    await execute({
      _mesh_headers: {
        "x-mesh-job-id": "job-inbound-1570",
        "x-mesh-claim-epoch": "4",
        "x-mesh-timeout": "30",
      },
    });

    expect(h.makeJobControllerMock).toHaveBeenCalledTimes(1);
    const [jobId, , , claimEpoch] = h.makeJobControllerMock.mock.calls[0] as
      unknown as [string, string, string, number | null];
    expect(jobId).toBe("job-inbound-1570");
    expect(claimEpoch).toBe(4);
    // The controller reached the handler's MeshJob slot.
    expect(seen[0]).not.toBeNull();
  });

  it("a task tool called WITHOUT the header still runs controller-less", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "sync-agent", httpPort: 0 });
    const seen: unknown[] = [];
    agent.addTool({
      name: "render",
      task: true,
      parameters: z.object({}),
      meshJobParamIndex: 1,
      execute: async (_args: unknown, job: unknown) => {
        seen.push(job);
        return "ran";
      },
    });
    const execute = captureExecute(fastmcp);

    expect(await execute({})).toBe("ran");
    expect(h.makeJobControllerMock).not.toHaveBeenCalled();
    expect(seen[0]).toBeNull();
  });
});

describe("nested required-dep failure is not a job dispatch (#1570)", () => {
  /**
   * End-to-end caller→callee. The caller is a job handler (the ALS shape the
   * claim dispatcher establishes: propagated headers + an active job context);
   * the wire it produces is captured off a mocked fetch and handed VERBATIM to
   * the callee's `execute` as `_mesh_headers`. Nothing is hand-crafted, so the
   * test fails if EITHER half regresses — the claim dispatcher re-seeding the
   * job id, or `buildMcpRequest` no longer scrubbing it.
   */
  it("the caller's own wire, replayed into the callee, gets a refusal not a lease release", async () => {
    // Caller side is the REAL ClaimDispatcher: it claims a job, binds the job
    // context, seeds the propagated-headers ALS, and the handler makes a
    // nested mesh call. Both halves of the root cause are therefore live —
    // the seeding in claim-dispatcher.ts and the forward in buildMcpRequest.
    let callerWire: Record<string, string> = {};
    let claimCalls = 0;
    globalThis.fetch = vi.fn(async (url: unknown, init?: RequestInit) => {
      const href = String(url);
      if (href.endsWith("/jobs/claim")) {
        // Hand out the job ONCE; the poll loop must not keep re-claiming it.
        claimCalls += 1;
        if (claimCalls > 1) {
          return { status: 204, json: async () => ({}) } as unknown as Response;
        }
        return {
          status: 200,
          json: async () => ({
            claimed: [
              { id: "job-caller", submitted_payload: {}, claim_epoch: 2 },
            ],
          }),
        } as unknown as Response;
      }
      if (href.endsWith("/mcp")) {
        callerWire = (JSON.parse((init?.body as string) ?? "{}")?.params
          ?.arguments?._mesh_headers ?? {}) as Record<string, string>;
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () =>
            JSON.stringify({
              jsonrpc: "2.0",
              id: "x",
              result: { content: [{ type: "text", text: "{}" }] },
            }),
          headers: {
            get: (n: string) =>
              n.toLowerCase() === "content-type" ? "application/json" : null,
          },
        } as unknown as Response;
      }
      return { status: 204, json: async () => ({}) } as unknown as Response;
    }) as unknown as typeof fetch;

    const dispatcher = new ClaimDispatcher(
      "cap",
      "instance-1",
      "http://reg",
      async () => {
        await callMcpTool(
          "http://d:9000",
          "render",
          {},
          DEFAULT_CALL_OPTIONS,
          "cap",
        );
        return null;
      },
    );
    dispatcher.start();
    await new Promise((r) => setTimeout(r, 100));
    await dispatcher.stop();

    // The caller identifies itself, and does NOT hand over its dispatch id.
    expect(callerWire["x-mesh-calling-job-id"]).toBe("job-caller");
    expect(callerWire["x-mesh-job-id"]).toBeUndefined();

    // Callee side: that exact wire, into a task tool whose required dep is down.
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "nested-agent", httpPort: 0 });
    const calls: unknown[] = [];
    agent.addTool({
      name: "render",
      task: true,
      parameters: z.object({}),
      dependencies: [{ capability: "lookup", required: true }],
      execute: async (_args: unknown, dep: unknown) => {
        calls.push(dep);
        return "ran";
      },
    });
    const execute = captureExecute(fastmcp);

    let thrown: unknown;
    try {
      await execute({ _mesh_headers: callerWire });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeInstanceOf(UserError);
    expect(JSON.parse((thrown as Error).message)).toEqual({
      error: "dependency_unavailable",
      capability: "lookup",
    });
    expect(h.releaseLeaseMock).not.toHaveBeenCalled();
    expect(calls).toHaveLength(0);
  });

  it("refuses with dependency_unavailable — it does not release a lease", async () => {
    // The post-fix wire shape, asserted directly.
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "nested-agent", httpPort: 0 });
    const calls: unknown[] = [];
    agent.addTool({
      name: "render",
      task: true,
      parameters: z.object({}),
      dependencies: [{ capability: "lookup", required: true }],
      execute: async (_args: unknown, dep: unknown) => {
        calls.push(dep);
        return "ran";
      },
    });
    const execute = captureExecute(fastmcp);

    let thrown: unknown;
    try {
      await execute({
        _mesh_headers: {
          "x-mesh-calling-job-id": "job-caller",
          "x-mesh-calling-claim-epoch": "2",
        },
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeInstanceOf(UserError);
    expect(JSON.parse((thrown as Error).message)).toEqual({
      error: "dependency_unavailable",
      capability: "lookup",
    });
    expect(h.releaseLeaseMock).not.toHaveBeenCalled();
    expect(calls).toHaveLength(0);
  });
});

describe("version-skew guard (#1570)", () => {
  // A pre-3.8 caller DID forward its job id, and only ever from inside a bound
  // job context — which seeds x-mesh-calling-job-id on the same request. The
  // pair arriving together is a leak, not a dispatch: honouring it would bind
  // this handler to the old caller's row for the length of the skew window.
  it("ignores an inbound job id that arrives with calling identity", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "skew-agent", httpPort: 0 });
    const seen: unknown[] = [];
    agent.addTool({
      name: "render",
      task: true,
      parameters: z.object({}),
      meshJobParamIndex: 1,
      execute: async (_args: unknown, job: unknown) => {
        seen.push(job);
        return "ran";
      },
    });
    const execute = captureExecute(fastmcp);

    expect(
      await execute({
        _mesh_headers: {
          "x-mesh-job-id": "job-caller",
          "x-mesh-calling-job-id": "job-caller",
        },
      }),
    ).toBe("ran");

    expect(h.makeJobControllerMock).not.toHaveBeenCalled();
    expect(seen[0]).toBeNull();
  });

  it("still dispatches a genuine push call, which carries no calling identity", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "push-agent", httpPort: 0 });
    agent.addTool({
      name: "render",
      task: true,
      parameters: z.object({}),
      meshJobParamIndex: 1,
      execute: async () => "ran",
    });
    const execute = captureExecute(fastmcp);

    await execute({ _mesh_headers: { "x-mesh-job-id": "job-push" } });

    expect(h.makeJobControllerMock).toHaveBeenCalledTimes(1);
  });
});

describe("outbound never carries the dispatch trio (#1570)", () => {
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

  it("scrubs the trio from both the HTTP headers and _mesh_headers", async () => {
    mockFetch();
    await runWithPropagatedHeaders(
      {
        "x-mesh-job-id": "job-leaked",
        "x-mesh-claim-epoch": "9",
        "x-mesh-recv-cursor": '{"work":4}',
        "x-mesh-timeout": "30",
      },
      async () => {
        await callMcpTool(
          "http://d:9000",
          "t",
          { a: 1 },
          DEFAULT_CALL_OPTIONS,
          "cap",
        );
      },
    );

    const headers = (captured?.headers ?? {}) as Record<string, string>;
    const body = JSON.parse((captured?.body as string) ?? "{}");
    const meshHeaders = (body?.params?.arguments?._mesh_headers ?? {}) as Record<
      string,
      string
    >;

    for (const name of [
      "x-mesh-job-id",
      "x-mesh-claim-epoch",
      "x-mesh-recv-cursor",
    ]) {
      expect(headers[name]).toBeUndefined();
      expect(meshHeaders[name]).toBeUndefined();
    }
    // A genuinely propagated header is untouched.
    expect(meshHeaders["x-mesh-timeout"]).toBe("30");
  });
});
