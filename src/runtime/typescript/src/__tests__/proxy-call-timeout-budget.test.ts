/**
 * Issue #1584 — the per-call budget a TypeScript caller enforces locally and
 * the one it advertises downstream in `X-Mesh-Timeout` must be the same
 * number, and its default must match Python's and Java's.
 *
 * Before the fix these were two independent computations:
 *
 *   effectiveTimeout = options.timeout                 // (kwargs.timeout ?? 30) * 1000
 *   X-Mesh-Timeout   = MCP_MESH_CALL_TIMEOUT || floor(options.timeout / 1000)
 *
 * so (a) the default budget was 30s in TypeScript against 300s in
 * Python/Java for the identical tool, and (b) setting MCP_MESH_CALL_TIMEOUT
 * moved only the ADVERTISED value — the client still gave up at its own,
 * unchanged deadline, leaving the provider working on a request nobody was
 * waiting for.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createProxy,
  resolveDefaultCallTimeoutSecs,
  DEFAULT_CALL_OPTIONS,
} from "../proxy.js";

vi.mock("@mcpmesh/core", () => ({
  generateTraceId: () => "trace-mock",
  generateSpanId: () => "span-mock",
  injectTraceContext: (argsJson: string) => argsJson,
  publishSpan: vi.fn(async () => false),
  parseSseResponse: (s: string) => s,
  parseSseResponseToObject: (s: string) => JSON.parse(s),
  awaitJobCancel: vi.fn(() => new Promise<void>(() => {})),
  matchesPropagateHeader: () => false,
}));

vi.mock("../http-pool.js", () => ({
  getDispatcher: () => undefined,
}));

const ENDPOINT = "http://producer.local:9000";

function jsonResponse(): Response {
  const body = JSON.stringify({
    jsonrpc: "2.0",
    id: "x",
    result: { content: [{ type: "text", text: "ok" }] },
  });
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => body,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type" ? "application/json" : null,
    },
  } as unknown as Response;
}

/**
 * Call a proxy built from `kwargs` and report both halves of the budget:
 * what went out on the wire, and what the local abort timer was armed for.
 */
async function callAndCapture(
  kwargs?: Parameters<typeof createProxy>[3],
): Promise<{ header: string | undefined; abortMs: number | undefined }> {
  let header: string | undefined;
  globalThis.fetch = vi.fn(async (_url: string, init: RequestInit) => {
    const h = (init.headers ?? {}) as Record<string, string>;
    header = h["X-Mesh-Timeout"] ?? h["x-mesh-timeout"];
    return jsonResponse();
  }) as unknown as typeof fetch;

  // The local budget is whatever `setTimeout(() => abort(), N)` is armed with.
  let abortMs: number | undefined;
  const realSetTimeout = globalThis.setTimeout;
  const spy = vi
    .spyOn(globalThis, "setTimeout")
    .mockImplementation(((fn: () => void, ms?: number, ...rest: unknown[]) => {
      if (abortMs === undefined && typeof ms === "number" && ms > 0) {
        abortMs = ms;
      }
      return (realSetTimeout as unknown as (...a: unknown[]) => unknown)(
        fn,
        ms,
        ...rest,
      );
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    }) as any);

  try {
    const proxy = createProxy(ENDPOINT, "echoer", "echo", kwargs);
    await proxy({ foo: 1 });
  } finally {
    spy.mockRestore();
  }
  return { header, abortMs };
}

describe("#1584 per-call budget: header and abort timer agree", () => {
  let originalFetch: typeof fetch;
  let originalEnv: string | undefined;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    originalEnv = process.env.MCP_MESH_CALL_TIMEOUT;
    delete process.env.MCP_MESH_CALL_TIMEOUT;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    if (originalEnv === undefined) {
      delete process.env.MCP_MESH_CALL_TIMEOUT;
    } else {
      process.env.MCP_MESH_CALL_TIMEOUT = originalEnv;
    }
    vi.restoreAllMocks();
  });

  it("defaults to 300s — matching Python and Java — not 30s", async () => {
    const { header, abortMs } = await callAndCapture();
    expect(header).toBe("300");
    expect(abortMs).toBe(300_000);
  });

  it("honours MCP_MESH_CALL_TIMEOUT for BOTH halves of the budget", async () => {
    process.env.MCP_MESH_CALL_TIMEOUT = "600";
    const { header, abortMs } = await callAndCapture();
    expect(header).toBe("600");
    // The pre-fix bug: the header moved to 600 while this stayed at 30_000.
    expect(abortMs).toBe(600_000);
  });

  it("lets an explicit per-call timeout override the env var, for both halves", async () => {
    process.env.MCP_MESH_CALL_TIMEOUT = "600";
    const { header, abortMs } = await callAndCapture({ timeout: 45 });
    expect(header).toBe("45");
    expect(abortMs).toBe(45_000);
  });

  it("keeps an explicit timeout of 30 meaning 30 — not the 300 default", async () => {
    // The pre-fix `kwargs?.timeout ?? 30` collapsed "asked for 30" and "asked
    // for nothing"; raising the default without separating them would have
    // silently promoted every explicit 30 to 300.
    const { header, abortMs } = await callAndCapture({ timeout: 30 });
    expect(header).toBe("30");
    expect(abortMs).toBe(30_000);
  });

  it("never advertises a sub-second budget as 0", async () => {
    // 0.4s would floor to "0", which every receiver reads as "unset" and
    // replaces with its own (much larger) default.
    const { header, abortMs } = await callAndCapture({ timeout: 0.4 });
    expect(header).toBe("1");
    expect(abortMs).toBe(1_000);
  });

  it("rounds a fractional budget UP on BOTH halves, never down", async () => {
    // Review catch: advertising 3s while aborting at 2400ms leaves the
    // provider working 600ms past the point anyone is listening. The wire
    // carries whole seconds, so the abort timer is quantised to match.
    const { header, abortMs } = await callAndCapture({ timeout: 2.4 });
    expect(header).toBe("3");
    expect(abortMs).toBe(3_000);
  });

  it("keeps a propagated inbound X-Mesh-Timeout instead of overwriting it", async () => {
    const { runWithPropagatedHeaders } = await import("../proxy.js");
    let header: string | undefined;
    globalThis.fetch = vi.fn(async (_url: string, init: RequestInit) => {
      const h = (init.headers ?? {}) as Record<string, string>;
      header = h["X-Mesh-Timeout"] ?? h["x-mesh-timeout"];
      return jsonResponse();
    }) as unknown as typeof fetch;

    const proxy = createProxy(ENDPOINT, "echoer", "echo");
    await runWithPropagatedHeaders({ "x-mesh-timeout": "12" }, async () => {
      await proxy({ foo: 1 });
    });
    expect(header).toBe("12");
  });
});

describe("#1584 streaming budgets still follow MCP_MESH_CALL_TIMEOUT", () => {
  let originalFetch: typeof fetch;
  let originalEnv: string | undefined;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    originalEnv = process.env.MCP_MESH_CALL_TIMEOUT;
    delete process.env.MCP_MESH_CALL_TIMEOUT;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    if (originalEnv === undefined) {
      delete process.env.MCP_MESH_CALL_TIMEOUT;
    } else {
      process.env.MCP_MESH_CALL_TIMEOUT = originalEnv;
    }
    vi.restoreAllMocks();
  });

  it("raises a streaming dependency's budget when the env var is raised", async () => {
    // docs/environment-variables.md tells operators to raise
    // MCP_MESH_CALL_TIMEOUT for long-running chains. Deriving the stream
    // budget from a hard-coded 300 would have silently broken that.
    process.env.MCP_MESH_CALL_TIMEOUT = "900";
    const { header, abortMs } = await callAndCapture({ streaming: true });
    expect(header).toBe("900");
    expect(abortMs).toBe(900_000);
  });

  it("still defaults a streaming dependency to 300", async () => {
    const { header, abortMs } = await callAndCapture({ streaming: true });
    expect(header).toBe("300");
    expect(abortMs).toBe(300_000);
  });

  it("lets an explicit streamTimeout win over the env var", async () => {
    process.env.MCP_MESH_CALL_TIMEOUT = "900";
    const { header, abortMs } = await callAndCapture({
      streaming: true,
      streamTimeout: 120,
    });
    expect(header).toBe("120");
    expect(abortMs).toBe(120_000);
  });

  it("documents that `timeout` does not apply to a streaming dependency", async () => {
    // Pre-existing behaviour, asserted so the carve-out in the
    // DependencyKwargs docs stays honest.
    const { header, abortMs } = await callAndCapture({
      streaming: true,
      timeout: 45,
    });
    expect(header).toBe("300");
    expect(abortMs).toBe(300_000);
  });
});

describe("#1584 resolveDefaultCallTimeoutSecs", () => {
  let originalEnv: string | undefined;

  beforeEach(() => {
    originalEnv = process.env.MCP_MESH_CALL_TIMEOUT;
  });

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.MCP_MESH_CALL_TIMEOUT;
    } else {
      process.env.MCP_MESH_CALL_TIMEOUT = originalEnv;
    }
    vi.restoreAllMocks();
  });

  it("falls back to 300 when unset or blank", () => {
    delete process.env.MCP_MESH_CALL_TIMEOUT;
    expect(resolveDefaultCallTimeoutSecs()).toBe(300);
    process.env.MCP_MESH_CALL_TIMEOUT = "   ";
    expect(resolveDefaultCallTimeoutSecs()).toBe(300);
  });

  it("falls back to 300 (with a warning) on unparseable or non-positive values", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    for (const bad of ["abc", "0", "-5", "NaN"]) {
      process.env.MCP_MESH_CALL_TIMEOUT = bad;
      expect(resolveDefaultCallTimeoutSecs()).toBe(300);
    }
    expect(warn).toHaveBeenCalled();
  });

  it("is read at call time, so DEFAULT_CALL_OPTIONS tracks the env var", () => {
    process.env.MCP_MESH_CALL_TIMEOUT = "120";
    expect(resolveDefaultCallTimeoutSecs()).toBe(120);
    expect(DEFAULT_CALL_OPTIONS.timeout).toBe(120_000);
    process.env.MCP_MESH_CALL_TIMEOUT = "45";
    expect(DEFAULT_CALL_OPTIONS.timeout).toBe(45_000);
  });
});
