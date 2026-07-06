/**
 * Unit tests for issue #1278: typed supersession signal (TypeScript half).
 *
 * A provider tool that detects it is being called by a SUPERSEDED executor (the
 * app compares the calling job's epoch via `callingJob()` — issue #1263)
 * rejects the call by throwing a typed `MeshSupersededError`. That crosses the
 * wire as the reserved `{"error":"claim_superseded"}` app envelope (plus an
 * optional `"detail"`), and the CALLING side's injected proxy recognizes the
 * envelope and re-throws `MeshSupersededError` — so a superseded caller unwinds
 * with one `instanceof MeshSupersededError` instead of string-matching
 * `claim_superseded` after every mutating call.
 *
 * Structural parallel of the `dependency_unavailable` refusal (issue #1273):
 * both throw a `UserError` whose message is a reserved JSON envelope, so the
 * contract (not the carrier) drives classification. Mirrors
 * direct-invoke-required.spec.ts + proxy-tool-error.test.ts.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { UserError } from "fastmcp";
import {
  MeshSupersededError,
  CLAIM_SUPERSEDED_MARKER,
  parseSupersededEnvelope,
} from "../superseded.js";
import { callMcpTool, DEFAULT_CALL_OPTIONS } from "../proxy.js";

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

describe("MeshSupersededError class (#1278)", () => {
  it("uses the SAME canonical marker as the job path", () => {
    // The reserved marker is the SAME string the job path uses on the wire
    // (Rust task_backend.rs CLAIM_SUPERSEDED_REASON / Go).
    expect(CLAIM_SUPERSEDED_MARKER).toBe("claim_superseded");
  });

  it("is a UserError subclass (so `instanceof UserError` still catches it)", () => {
    const err = new MeshSupersededError("x");
    expect(err).toBeInstanceOf(UserError);
    expect(err).toBeInstanceOf(MeshSupersededError);
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("MeshSupersededError");
  });

  it("serializes the reserved envelope WITH detail", () => {
    // fastmcp maps a thrown UserError to {content:[{text: error.message}],
    // isError:true} (verified in fastmcp dist: `if (error instanceof
    // UserError) return {content:[{text: error.message}], isError:true}`), so
    // err.message IS the isError tool-result text a provider auto-emits.
    const err = new MeshSupersededError("stale epoch 3");
    expect(JSON.parse(err.message)).toEqual({
      error: "claim_superseded",
      detail: "stale epoch 3",
    });
    expect(err.detail).toBe("stale epoch 3");
  });

  it("OMITS the detail key entirely when no detail is supplied", () => {
    const err = new MeshSupersededError();
    expect(JSON.parse(err.message)).toEqual({ error: "claim_superseded" });
    expect(err.detail).toBeUndefined();
  });
});

describe("parseSupersededEnvelope recognizer (#1278)", () => {
  it("recognizes the bare marker (no detail)", () => {
    const err = parseSupersededEnvelope('{"error":"claim_superseded"}');
    expect(err).toBeInstanceOf(MeshSupersededError);
    expect(err?.detail).toBeUndefined();
  });

  it("carries a string detail through", () => {
    const err = parseSupersededEnvelope(
      '{"error":"claim_superseded","detail":"stale"}',
    );
    expect(err).toBeInstanceOf(MeshSupersededError);
    expect(err?.detail).toBe("stale");
  });

  it("returns null for non-JSON text", () => {
    expect(parseSupersededEnvelope("boom, plain text error")).toBeNull();
  });

  it("returns null for JSON that is not a plain object", () => {
    expect(parseSupersededEnvelope('"claim_superseded"')).toBeNull();
    expect(parseSupersededEnvelope("[1,2,3]")).toBeNull();
    expect(parseSupersededEnvelope("null")).toBeNull();
  });

  it("does NOT misclassify a sibling dependency_unavailable envelope", () => {
    expect(
      parseSupersededEnvelope(
        '{"error":"dependency_unavailable","capability":"lookup"}',
      ),
    ).toBeNull();
  });

  it("returns null for a generic error object", () => {
    expect(parseSupersededEnvelope('{"error":"boom"}')).toBeNull();
  });

  it("drops a non-string detail (marker still recognized)", () => {
    const err = parseSupersededEnvelope(
      '{"error":"claim_superseded","detail":42}',
    );
    expect(err).toBeInstanceOf(MeshSupersededError);
    expect(err?.detail).toBeUndefined();
  });
});

// --- Consumer recognize path: driven end-to-end through callMcpTool, whose
// injected-proxy error path re-throws the typed error. Mirrors
// proxy-tool-error.test.ts fixtures. ---

const ENDPOINT = "http://producer.local:9000";
const TOOL = "mutate";
const CAPABILITY = "mutator";

function jsonResponse(envelope: object): Response {
  const body = JSON.stringify({ jsonrpc: "2.0", id: "x", ...envelope });
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

function sseResponse(envelopes: object[]): Response {
  const encoder = new TextEncoder();
  const blocks = envelopes.map(
    (e) =>
      `event: message\ndata: ${JSON.stringify({ jsonrpc: "2.0", id: "x", ...e })}\n\n`,
  );
  let i = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < blocks.length) {
        controller.enqueue(encoder.encode(blocks[i]));
        i += 1;
      } else {
        controller.close();
      }
    },
  });
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    body: stream,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type" ? "text/event-stream" : null,
    },
  } as unknown as Response;
}

/** An isError CallToolResult carrying `text` in its single content item. */
function isErrorResult(text: string): object {
  return { isError: true, content: [{ type: "text", text }] };
}

async function callAndCatch(makeResponse: () => Response): Promise<unknown> {
  const fetchMock = vi.fn(async () => makeResponse());
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  try {
    await callMcpTool(ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY);
    return { caught: null, fetchMock };
  } catch (err) {
    return { caught: err, fetchMock };
  }
}

describe("consumer recognize path — JSON transport (#1278)", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("re-throws the TYPED MeshSupersededError for the reserved envelope (with detail)", async () => {
    const { caught } = (await callAndCatch(() =>
      jsonResponse({
        result: isErrorResult('{"error":"claim_superseded","detail":"stale"}'),
      }),
    )) as { caught: unknown };
    // The swallow-point: the retry loop / post-loop `throw lastError` must NOT
    // re-wrap it into a generic `MCP tool error: …` Error.
    expect(caught).toBeInstanceOf(MeshSupersededError);
    expect((caught as MeshSupersededError).detail).toBe("stale");
  });

  it("re-throws MeshSupersededError for the bare marker (no detail)", async () => {
    const { caught } = (await callAndCatch(() =>
      jsonResponse({ result: isErrorResult('{"error":"claim_superseded"}') }),
    )) as { caught: unknown };
    expect(caught).toBeInstanceOf(MeshSupersededError);
    expect((caught as MeshSupersededError).detail).toBeUndefined();
  });

  it("does NOT retry a superseded rejection (deliberate provider refusal)", async () => {
    const { caught, fetchMock } = (await callAndCatch(() =>
      jsonResponse({ result: isErrorResult('{"error":"claim_superseded"}') }),
    )) as { caught: unknown; fetchMock: ReturnType<typeof vi.fn> };
    expect(caught).toBeInstanceOf(MeshSupersededError);
    // maxAttempts defaults > 1; the guard re-throws untouched, one fetch only.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("still throws a GENERIC Error for an ordinary isError result", async () => {
    const { caught } = (await callAndCatch(() =>
      jsonResponse({ result: isErrorResult("some ordinary tool failure") }),
    )) as { caught: unknown };
    expect(caught).toBeInstanceOf(Error);
    expect(caught).not.toBeInstanceOf(MeshSupersededError);
    expect((caught as Error).message).toContain("MCP tool error");
  });

  it("leaves a sibling dependency_unavailable envelope GENERIC", async () => {
    const { caught } = (await callAndCatch(() =>
      jsonResponse({
        result: isErrorResult(
          '{"error":"dependency_unavailable","capability":"lookup"}',
        ),
      }),
    )) as { caught: unknown };
    expect(caught).toBeInstanceOf(Error);
    expect(caught).not.toBeInstanceOf(MeshSupersededError);
  });
});

describe("consumer recognize path — SSE transport (#1278)", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("re-throws the TYPED MeshSupersededError over SSE (transport-symmetric)", async () => {
    const { caught } = (await callAndCatch(() =>
      sseResponse([
        {
          result: isErrorResult(
            '{"error":"claim_superseded","detail":"stale"}',
          ),
        },
      ]),
    )) as { caught: unknown };
    expect(caught).toBeInstanceOf(MeshSupersededError);
    expect((caught as MeshSupersededError).detail).toBe("stale");
  });

  it("still throws a generic Error for an ordinary isError result over SSE", async () => {
    const { caught } = (await callAndCatch(() =>
      sseResponse([{ result: isErrorResult("boom: division by zero") }]),
    )) as { caught: unknown };
    expect(caught).toBeInstanceOf(Error);
    expect(caught).not.toBeInstanceOf(MeshSupersededError);
  });
});
