/**
 * Worker entry for the mesh tool worker pool.
 *
 * Launched as a `worker_threads.Worker` from `tool-worker-pool.ts`. Each
 * worker:
 *
 * 1. Resolves the user's `tsx` loader from THEIR node_modules (the Worker
 *    `execArgv` does not propagate the parent process's tsx loader, so .ts
 *    imports would otherwise throw `ERR_UNKNOWN_FILE_EXTENSION`).
 * 2. Sets a worker-mode symbol on `globalThis` so the SDK skips main-thread
 *    init (HTTP server, registry heartbeat, Rust core agent start) when the
 *    user module imports `mesh()`.
 * 3. Dynamic-imports the user module — this triggers `agent.addTool(...)` calls
 *    which the SDK redirects into a worker-local tool map.
 * 4. Reports `ready` to the parent.
 * 5. Listens for `{kind: "call"}` messages, executes the tool with
 *    reconstructed DI proxies + restored ALS scope, and replies with
 *    `{kind: "result"}` or `{kind: "error"}`.
 */

import { parentPort, workerData, isMainThread } from "node:worker_threads";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

if (isMainThread) {
  throw new Error("tool-worker-entry.js must be loaded inside a worker thread");
}
if (!parentPort) {
  throw new Error("tool-worker-entry.js requires a parent port");
}

interface WorkerData {
  userModulePath: string;
  sdkEntryPath: string;
  slotIdx: number;
}

const data = workerData as WorkerData;
const userModulePath = data.userModulePath;
const sdkEntryPath = data.sdkEntryPath;

// Mark worker mode BEFORE importing the user module. The SDK checks this
// symbol in MeshAgent.constructor / addTool to short-circuit main-thread
// init and stash tool functions in a worker-local map instead.
const WORKER_MODE_SYMBOL = Symbol.for("@mcpmesh/sdk/worker-mode");
(globalThis as unknown as Record<symbol, boolean>)[WORKER_MODE_SYMBOL] = true;

// User-facing in-worker flag. Distinct from the SDK-internal worker-mode flag
// above. User code can check this to guard their own top-level side effects
// (custom HTTP servers, OTel init, prometheus registries) that should not
// run in worker threads. Exported as IN_WORKER_SYMBOL from the SDK index.
(globalThis as any)[Symbol.for("@mcpmesh/sdk/in-worker")] = true;

async function bootstrap(): Promise<void> {
  // 1. Register tsx loader for the worker if user runs .ts directly.
  const isTs =
    userModulePath.endsWith(".ts") || userModulePath.endsWith(".mts");
  if (isTs) {
    try {
      const userRequire = createRequire(userModulePath);
      const tsxApiPath = userRequire.resolve("tsx/esm/api");
      const tsxApi = await import(pathToFileURL(tsxApiPath).href);
      if (typeof tsxApi.register === "function") {
        tsxApi.register();
      } else {
        throw new Error("tsx/esm/api does not export register()");
      }
    } catch (e) {
      const msg =
        "MCP_MESH_TOOL_ISOLATION requires `tsx` in your dependencies when " +
        "running .ts directly. Add `tsx` to package.json or set " +
        "MCP_MESH_TOOL_ISOLATION=false to disable isolation.";
      parentPort!.postMessage({
        kind: "fatal",
        error: {
          name: "TsxResolutionError",
          message: msg,
          cause: String(e),
        },
      });
      process.exit(1);
      return;
    }
  }

  // 2. Import the SDK first so the worker-mode flag takes effect before the
  //    user's import of mesh() touches MeshAgent.constructor.
  const sdk = await import(pathToFileURL(sdkEntryPath).href);

  // 3. Import the user's module — fires addTool() calls.
  await import(pathToFileURL(userModulePath).href);

  // 4. Pull the tool map populated during user module init.
  const tools: Map<string, (...args: unknown[]) => unknown> =
    typeof sdk.__getWorkerToolMap === "function"
      ? sdk.__getWorkerToolMap()
      : new Map();

  // 5. Get ALS helpers + proxy factory for per-call setup.
  const { createProxy, runWithTraceContext, runWithPropagatedHeaders } = sdk;

  parentPort!.on("message", (msg: unknown) => {
    handleMessage(msg, tools, createProxy, runWithTraceContext, runWithPropagatedHeaders);
  });

  parentPort!.postMessage({ kind: "ready" });
}

function serializeError(err: any): { name: string; message: string; stack?: string; code?: string; cause?: any } {
  if (!(err instanceof Error)) {
    return { name: "Error", message: String(err) };
  }
  const out: any = { name: err.name, message: err.message, stack: err.stack };
  if ((err as any).code !== undefined) out.code = (err as any).code;
  if ((err as any).cause !== undefined) out.cause = serializeError((err as any).cause);
  return out;
}

interface CallMessage {
  id: number;
  kind: "call";
  toolName: string;
  cleanArgs: unknown;
  depsConfig: ({
    endpoint: string;
    capability: string;
    functionName: string;
    kwargs: Record<string, unknown>;
  } | null)[];
  traceContext: { traceId: string; parentSpanId: string | null } | null;
  propagatedHeaders: Record<string, string>;
}

function handleMessage(
  msg: unknown,
  tools: Map<string, (...args: unknown[]) => unknown>,
  createProxy: (
    endpoint: string,
    capability: string,
    functionName: string,
    kwargs?: Record<string, unknown>
  ) => unknown,
  runWithTraceContext: <T>(ctx: unknown, fn: () => T | Promise<T>) => T | Promise<T>,
  runWithPropagatedHeaders: <T>(headers: Record<string, string>, fn: () => T | Promise<T>) => T | Promise<T>
): void {
  if (!msg || typeof msg !== "object") return;
  const m = msg as CallMessage;
  if (m.kind !== "call" || typeof m.id !== "number") return;

  const respond = (payload: Record<string, unknown>) => {
    parentPort!.postMessage({ id: m.id, ...payload });
  };

  const tool = tools.get(m.toolName);
  if (!tool) {
    respond({
      kind: "error",
      error: {
        name: "ToolNotFound",
        message: `Tool '${m.toolName}' not registered in worker`,
      },
    });
    return;
  }

  // Reconstruct DI proxies — workers can't share the main-thread proxies, so
  // each worker builds its own with its own undici Agent (Python parity).
  const deps = m.depsConfig.map((cfg) =>
    cfg === null
      ? null
      : createProxy(cfg.endpoint, cfg.capability, cfg.functionName, cfg.kwargs)
  );

  // Restore ALS scopes so user code sees the same trace context + headers as
  // the main-thread caller, then invoke the tool.
  const headers = m.propagatedHeaders ?? {};
  const traceCtx = m.traceContext ?? { traceId: "", parentSpanId: null };

  Promise.resolve()
    .then(() =>
      runWithTraceContext(traceCtx, () =>
        runWithPropagatedHeaders(headers, () =>
          (tool as (...args: unknown[]) => unknown)(m.cleanArgs, ...deps)
        )
      )
    )
    .then((value) => respond({ kind: "result", value }))
    .catch((err: unknown) => {
      respond({ kind: "error", error: serializeError(err) });
    });
}

bootstrap().catch((e: unknown) => {
  const err = e as Error;
  try {
    parentPort!.postMessage({
      kind: "fatal",
      error: {
        name: err?.name ?? "Error",
        message: err?.message ?? String(e),
        stack: err?.stack,
      },
    });
  } catch {
    // ignore
  }
  process.exit(1);
});
