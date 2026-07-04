/**
 * Issue #1273: direct `tools/call` dispatch must refuse when a `required=true`
 * dependency slot is unresolved at invocation time.
 *
 * The claim path (#1268, requiredProbe) and the @mesh.route perimeter (#1249,
 * 503) already refuse before a handler can observe a null required dependency;
 * this closes the same DOWN→UP flap window on the plain tool-dispatch path.
 * The guard is FLAVOR-AWARE (review follow-up):
 *   - plain tools/call → structured `dependency_unavailable` refusal (a
 *     `UserError` whose message carries the JSON envelope → FastMCP `isError`
 *     result, the SAME semantic class as the route perimeter's 503), so the
 *     caller classifies it as retryable topology.
 *   - inbound JOB dispatch (task tool + X-Mesh-Job-Id) → RELEASE the lease so
 *     the claimed row re-queues, mirroring the claim path — never a bare throw
 *     (which would strand the row `working` until lease expiry).
 * Optional deps keep their null-passthrough. The guard runs AFTER the settle
 * wait (deps are built post-settle).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { UserError } from "fastmcp";

// Only `makeJobController` is mocked (it wraps a napi JobController handle that
// hits the registry). The REAL `readJobHeaders` runs against the raw inbound
// `_mesh_headers` the test passes through `execute(...)` — so the job-header
// extraction path (item 1's fix: raw headers, not the allowlist-filtered map)
// is exercised end-to-end. Declared via vi.hoisted so the hoisted vi.mock
// factory below can reference them (TDZ otherwise).
const h = vi.hoisted(() => {
  const releaseLeaseMock = vi.fn(async () => {});
  const makeJobControllerMock = vi.fn(() => ({ releaseLease: releaseLeaseMock }));
  return { releaseLeaseMock, makeJobControllerMock };
});

vi.mock("../inbound-job-dispatch.js", async (importActual) => {
  const actual =
    await importActual<typeof import("../inbound-job-dispatch.js")>();
  return {
    ...actual,
    makeJobController:
      h.makeJobControllerMock as unknown as typeof actual.makeJobController,
  };
});

import { MeshAgent } from "../agent.js";
import { RouteRegistry } from "../route.js";
import { resetSettleStateForTests } from "../settle.js";

function makeFastMCPStub() {
  return {
    addTool: vi.fn(),
    start: vi.fn(),
    getApp: vi.fn(),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

let autoStartSpy: ReturnType<typeof vi.spyOn> | null = null;
let warnSpy: ReturnType<typeof vi.spyOn> | null = null;
const savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
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
  // Settle immediately so an unresolved required slot is genuinely unresolved,
  // not merely still-settling.
  process.env.MCP_MESH_SETTLE_TIMEOUT = "0";
  resetSettleStateForTests();
  RouteRegistry.reset();
});

afterEach(() => {
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
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function captureExecute(fastmcp: any): (args: unknown) => Promise<string> {
  return fastmcp.addTool.mock.calls[0][0].execute as (
    args: unknown,
  ) => Promise<string>;
}

describe("direct-invoke required-dep guard (#1273)", () => {
  it("refuses with dependency_unavailable when a required slot is unresolved", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "guard-agent", httpPort: 0 });
    const calls: unknown[] = [];
    agent.addTool({
      name: "enrich",
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
      await execute({});
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeInstanceOf(UserError);
    const body = JSON.parse((thrown as Error).message);
    expect(body).toEqual({
      error: "dependency_unavailable",
      capability: "lookup",
    });
    expect(calls).toHaveLength(0); // handler must NOT run
    expect(h.releaseLeaseMock).not.toHaveBeenCalled(); // not a job flavor
  });

  it("invokes the handler once the required dep resolves", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "resolved-agent", httpPort: 0 });
    const calls: unknown[] = [];
    agent.addTool({
      name: "enrich",
      parameters: z.object({}),
      dependencies: [{ capability: "lookup", required: true }],
      execute: async (_args: unknown, dep: unknown) => {
        calls.push(dep);
        return "ran";
      },
    });

    // Resolve the required dependency so a real proxy lands in the slot.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable(
      "lookup",
      "http://localhost:19999",
      "remote_fn",
      "provider-agent",
      "enrich",
      0,
    );

    const execute = captureExecute(fastmcp);
    expect(await execute({})).toBe("ran");
    expect(calls).toHaveLength(1);
    expect(calls[0]).not.toBeNull(); // ran with the live proxy
  });

  it("passes null through for an unresolved OPTIONAL dep (regression)", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "optional-agent", httpPort: 0 });
    const calls: unknown[] = [];
    agent.addTool({
      name: "enrich",
      parameters: z.object({}),
      // No `required` → optional; null passthrough preserved.
      dependencies: [{ capability: "lookup" }],
      execute: async (_args: unknown, dep: unknown) => {
        calls.push(dep);
        return dep ? "wired" : "unwired";
      },
    });
    const execute = captureExecute(fastmcp);

    expect(await execute({})).toBe("unwired");
    expect(calls).toEqual([null]); // handler ran with null, no refusal
  });
});

describe("job-header path releases the lease, never throws (#1273)", () => {
  it("releases the lease (not a throw) when an inbound JOB dispatch hits an unresolved required dep", async () => {
    // registryUrl defaults from env (MCP_MESH_REGISTRY_URL →
    // http://localhost:8000), so this.config.registryUrl is non-empty.
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, {
      name: "job-guard-agent",
      httpPort: 0,
    });
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

    // Present an inbound JOB dispatch by passing the job headers through the
    // REAL extraction path in _mesh_headers. x-mesh-job-id is NOT in the
    // propagate allowlist, so this only works because the guard reads the RAW
    // inbound headers (item 1's fix), not the allowlist-filtered map.
    const result = await execute({
      _mesh_headers: {
        "x-mesh-job-id": "job-77",
        "x-mesh-claim-epoch": "3",
      },
    });

    // Must NOT throw — the job-flavored path releases the lease instead.
    expect(result).toBe("");
    expect(calls).toHaveLength(0); // handler MUST NOT run
    expect(h.makeJobControllerMock).toHaveBeenCalledTimes(1);
    // makeJobController(jobId, agentId, registryUrl, claimEpoch)
    const ctorArgs = h.makeJobControllerMock.mock
      .calls[0] as unknown as unknown[];
    expect(ctorArgs[0]).toBe("job-77");
    expect(ctorArgs[3]).toBe(3);
    expect(h.releaseLeaseMock).toHaveBeenCalledTimes(1);
    const releaseArgs = h.releaseLeaseMock.mock.calls[0] as unknown as unknown[];
    expect(String(releaseArgs[0])).toContain("lookup");
  });
});
