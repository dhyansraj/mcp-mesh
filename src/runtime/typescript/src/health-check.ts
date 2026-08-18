/**
 * Periodic health check that can withdraw this agent from dependency
 * resolution while its own upstream is down (issue #1476).
 *
 * The verdict of the user's `healthCheck` is pushed to the Rust core on
 * every tick. While it is `unhealthy` the core stops heartbeating, the
 * registry's staleness sweep marks the agent unhealthy, and resolution
 * stops selecting it — consumers fail over to a surviving provider.
 * Reporting `healthy` (or `degraded`) again resumes heartbeats and the
 * registry restores the agent through the `410 Gone` re-register path,
 * with no process restart. The TTL is the CADENCE of that check, not the
 * end-to-end latency in either direction: withdrawal costs up to one TTL
 * plus the registry's staleness window once heartbeats stop, and recovery
 * costs up to one TTL plus the heartbeat resume and re-register round trip.
 *
 * TypeScript half of the mechanism shipped for Python in #1472/#1473 and
 * for Java in #1474/#1475; the verdict vocabulary, the "a broken check
 * degrades, it does not withdraw" rule, and the `checks`/`errors` keys
 * are deliberately identical across the three.
 *
 * ## Every agent type is gated, gateways included
 *
 * This loop runs for MCP agents (`mesh(server, ...)`) and for `mesh.route`
 * gateways (`express.ts`) alike. #1476 ran it for providers only, because
 * withdrawing a fan-out point was thought to take the application down;
 * RFC #1502 removed that harm by making `/ready` report the mesh runtime
 * instead of the verdict. Pausing the heartbeat now stops registry traffic
 * ONLY — the HTTP server keeps listening, resolved dependencies are
 * retained (#1131), and the pod stays in its Service endpoints. A gateway
 * that reports unavailable stops being DISCOVERED; it does not go dark.
 *
 * The hook means the same thing on every agent type — "I am not
 * available" — and mesh does the same thing with it everywhere: it stops
 * wiring that agent. What differs is topology, not meaning.
 */

/**
 * The verdict vocabulary shared by all three runtimes.
 *
 * `"healthy"` and `"unhealthy"` are the two answers a check gives; they are
 * the whole routing contract. `"degraded"` is what the RUNTIME records when
 * it has no verdict it can trust — a check that threw, one that missed its
 * deadline, an unusable return type, an unreadable status string — and it
 * keeps the agent in dependency resolution. Returning it from a `healthCheck`
 * is deprecated (issue #1515): it is indistinguishable from `"healthy"` on
 * every mesh path, so {@link normalizeHealthResult} warns and keeps the agent
 * serving.
 */
export type MeshHealthStatus = "healthy" | "degraded" | "unhealthy";

/**
 * The rich shape a `healthCheck` may return. A bare `boolean` is also
 * accepted (`true` → healthy, `false` → unhealthy).
 */
export interface MeshHealthResult {
  /**
   * `"healthy"` or `"unhealthy"`. Omitted means healthy — a result that
   * carries only `checks` is reporting success (Python parity:
   * `user_result.get("status", "healthy")`). A present-but-null status
   * means the same, and warns.
   */
  status?: MeshHealthStatus | string;
  /** Named sub-probes, surfaced verbatim for operators. */
  checks?: Record<string, unknown>;
  /** Human-readable reasons, surfaced verbatim for operators. */
  errors?: string[];
}

/**
 * A user health check. May be sync or async.
 *
 * Return `unhealthy` only for conditions the mesh should route AROUND —
 * the upstream this agent needs is genuinely not serving. An
 * indeterminate probe (cancelled, cut short) says nothing about the
 * upstream, so let it throw: the runtime keeps the agent in dependency
 * resolution rather than withdrawing it on a conclusion never reached.
 */
export type MeshHealthCheck = () =>
  | boolean
  | MeshHealthResult
  | Promise<boolean | MeshHealthResult>;

/** A normalized verdict — what the loop stores and publishes. */
export interface HealthVerdict {
  status: MeshHealthStatus;
  checks: Record<string, unknown>;
  errors: string[];
}

/** Python's `health_check_ttl` default, and Java's `DEFAULT_TTL_SECONDS`. */
export const DEFAULT_HEALTH_CHECK_TTL_SECONDS = 15;

/** Overrides the configured `healthCheckTtl` when set. */
export const HEALTH_CHECK_TTL_ENV = "MCP_MESH_HEALTH_CHECK_TTL";

/** Integers only — `"15s"`, `"1.5"` and `"0x10"` are all rejected. */
const INTEGER_RE = /^[+-]?\d+$/;

/**
 * Render anything a `throw` can produce, including non-`Error` values and
 * objects whose `toString` itself throws. The health loop must survive
 * every one of them: a formatting failure here would take out the very
 * mechanism whose job is to notice failures.
 */
export function describeThrown(err: unknown): string {
  if (err instanceof Error) return err.message || err.name;
  try {
    return String(err);
  } catch {
    return "<unprintable value>";
  }
}

/**
 * `degraded` as a RETURN VALUE is deprecated (issue #1515).
 *
 * The contract a health check answers is binary: stay in dependency
 * resolution, or withdraw. `degraded` and `healthy` are the same answer to
 * it, so the third word buys a 503 on an endpoint nothing probes and costs
 * the failure rate of a name that reads like withdrawal to everyone who
 * picks it when their upstream is down.
 *
 * The BEHAVIOUR is unchanged, deliberately: remapping it to `unhealthy`
 * would fix the common intent and silently withdraw every agent whose
 * author used the word correctly.
 *
 * Warned once per process, not once per refresh — the check re-runs every
 * TTL (15s by default), and a per-tick line would be several thousand
 * identical warnings a day from an agent doing what its author intended.
 */
let degradedReturnWarned = false;

function warnDegradedReturnOnce(): void {
  if (degradedReturnWarned) return;
  degradedReturnWarned = true;
  console.warn(
    `[mesh-health] healthCheck returned 'degraded' — this agent stays in ` +
      `dependency resolution and consumers will keep routing to it. Return ` +
      `false to withdraw.`,
  );
}

/** Re-arm the once-per-process deprecation warning. Tests only. */
export function __resetDegradedReturnWarning(): void {
  degradedReturnWarned = false;
}

/**
 * A null status is a defect in the same shape as a selected `degraded`: it
 * recurs identically on every refresh, so it gets the same dedup. At the 15s
 * default TTL a per-tick line is ~5,760 identical warnings a day.
 */
let nullStatusWarned = false;

function warnNullStatusOnce(): void {
  if (nullStatusWarned) return;
  nullStatusWarned = true;
  console.warn(
    `[mesh-health] health check returned a null status — treating it as ` +
      `healthy (an absent status already means healthy). Return ` +
      `'healthy' or 'unhealthy' if a verdict was intended.`,
  );
}

/** Re-arm the once-per-process null-status warning. Tests only. */
export function __resetNullStatusWarning(): void {
  nullStatusWarned = false;
}

/**
 * Convert whatever a health check returned into a verdict.
 *
 * Never throws. Anything unrecognized becomes `degraded`, NOT
 * `unhealthy`: an unparseable result is a reporting defect, and
 * withdrawing a working agent from the mesh over one is a far worse
 * failure than keeping it. Same rule as Java's `MeshHealthCheckRegistry.coerce`.
 *
 * Those runtime-assigned `degraded` verdicts do NOT warn — nothing the
 * author can act on happened. Only a `degraded` the author SELECTED does.
 */
export function normalizeHealthResult(raw: unknown): HealthVerdict {
  if (typeof raw === "boolean") {
    // Python parity: true → healthy, false → unhealthy.
    return raw
      ? { status: "healthy", checks: { health_check: true }, errors: [] }
      : {
          status: "unhealthy",
          checks: { health_check: false },
          errors: ["Health check returned false"],
        };
  }

  if (raw !== null && typeof raw === "object" && !Array.isArray(raw)) {
    const result = raw as MeshHealthResult;
    const rawStatus = result.status;
    const nullish = rawStatus === undefined || rawStatus === null;
    // A result with no `status` is reporting success (Python parity).
    //
    // A status that is PRESENT and nullish is treated the same way — the same
    // verdict Python reaches — but warns: `{ status: undefined }` is far
    // likelier to be an unset variable than an intent, and the warning is what
    // separates the two cases without changing routing (issue #1517).
    if (nullish && "status" in result) {
      warnNullStatusOnce();
    }
    const status = nullish ? "healthy" : toStatus(rawStatus);
    if (status === null) {
      return {
        status: "degraded",
        checks: { health_check_status_value: false },
        errors: [`Unrecognized health status: ${describeThrown(rawStatus)}`],
      };
    }
    if (status === "degraded") warnDegradedReturnOnce();
    return {
      status,
      checks: isPlainRecord(result.checks) ? result.checks : {},
      errors: Array.isArray(result.errors)
        ? result.errors.map((e) => (typeof e === "string" ? e : describeThrown(e)))
        : [],
    };
  }

  return {
    status: "degraded",
    checks: { health_check_return_type: false },
    errors: [
      `Invalid return type: ${raw === null ? "null" : typeof raw}. A health ` +
        `check returns a boolean or { status, checks, errors }.`,
    ],
  };
}

function toStatus(value: unknown): MeshHealthStatus | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  return normalized === "healthy" ||
    normalized === "degraded" ||
    normalized === "unhealthy"
    ? normalized
    : null;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * Run a health check and normalize its verdict. Never throws and never
 * rejects.
 *
 * A check that THROWS becomes `degraded`, not `unhealthy`: a buggy health
 * check must not be able to withdraw a working agent from the mesh.
 */
export async function runHealthCheck(
  healthCheck: MeshHealthCheck,
  agentName: string,
): Promise<HealthVerdict> {
  try {
    return normalizeHealthResult(await healthCheck());
  } catch (err) {
    const reason = describeThrown(err);
    console.warn(
      `[mesh-health] health check for agent '${agentName}' threw — ` +
        `reporting degraded (the agent keeps heartbeating): ${reason}`,
    );
    return {
      status: "degraded",
      checks: { health_check_execution: false },
      errors: [`Health check failed: ${reason}`],
    };
  }
}

/**
 * Resolve the refresh period, in seconds.
 *
 * Priority: `MCP_MESH_HEALTH_CHECK_TTL` > `healthCheckTtl` > 15s. Every
 * rejected value warns and falls through to the next source rather than
 * throwing — a malformed TTL must not stop an agent from booting, but it
 * must not be silently rounded into something else either.
 *
 * `override` is a parameter rather than an ambient `process.env` read so
 * the resolution rules are testable without mutating the environment.
 *
 * @param configured value from `AgentConfig.healthCheckTtl`
 * @param override raw {@link HEALTH_CHECK_TTL_ENV} value, or null/undefined
 */
export function resolveHealthCheckTtl(
  configured?: number | null,
  override?: string | null,
): number {
  let ttl = DEFAULT_HEALTH_CHECK_TTL_SECONDS;
  // Collected, not logged inline: a warning names the value that is
  // actually used, and that is not known until every source has been
  // considered. Warning "using 15s" while a valid env override goes on to
  // win would print a number the agent never runs with.
  const rejected: string[] = [];

  if (configured !== undefined && configured !== null) {
    if (Number.isInteger(configured) && configured >= 1) {
      ttl = configured;
    } else {
      rejected.push(
        `healthCheckTtl=${describeThrown(configured)} is not a whole number ` +
          `of seconds >= 1`,
      );
    }
  }

  if (typeof override === "string" && override.trim() !== "") {
    const text = override.trim();
    const parsed = INTEGER_RE.test(text) ? Number(text) : Number.NaN;
    if (Number.isInteger(parsed) && parsed >= 1) {
      ttl = parsed;
    } else {
      rejected.push(
        Number.isInteger(parsed)
          ? `${HEALTH_CHECK_TTL_ENV}=${override} is below the 1s minimum`
          : `${HEALTH_CHECK_TTL_ENV}=${override} is not an integer number of ` +
              `seconds`,
      );
    }
  }

  for (const reason of rejected) {
    console.warn(`[mesh-health] ${reason} — using ${ttl}s`);
  }

  return ttl;
}

/** Read {@link HEALTH_CHECK_TTL_ENV} and resolve against it. */
export function resolveHealthCheckTtlFromEnv(configured?: number | null): number {
  return resolveHealthCheckTtl(configured, process.env[HEALTH_CHECK_TTL_ENV]);
}

/**
 * Floor for the deadline a single health check gets. The deadline is the
 * larger of this and one TTL period, so a slow-but-working probe under a
 * short TTL is not abandoned while it is still making progress.
 */
export const HEALTH_CHECK_TIMEOUT_FLOOR_MS = 30_000;

/**
 * Deadline for one publish to the mesh runtime.
 *
 * `updateHealth` sends on a bounded command channel; a runtime that has
 * stopped draining it makes the send wait rather than fail, and without a
 * deadline that wait would be permanent.
 */
export const HEALTH_PUBLISH_TIMEOUT_MS = 10_000;

/** Race result marker — deliberately not a value any caller can produce. */
const TIMED_OUT = Symbol("mesh-health-timed-out");

/**
 * Await `work`, giving up after `ms`.
 *
 * Abandoning is not cancelling: `work` keeps running, and if it settles
 * later the result is dropped. `Promise.race` has already subscribed to
 * it, so a late rejection is handled and cannot surface as an unhandled
 * rejection.
 */
async function withDeadline<T>(
  work: Promise<T>,
  ms: number,
): Promise<T | typeof TIMED_OUT> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      work,
      new Promise<typeof TIMED_OUT>((resolve) => {
        timer = setTimeout(() => resolve(TIMED_OUT), ms);
        // A pending deadline must not hold a finished process open.
        timer.unref?.();
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

export interface HealthCheckLoopOptions {
  agentName: string;
  healthCheck: MeshHealthCheck;
  /** Refresh period in seconds (already resolved). */
  ttlSeconds: number;
  /**
   * Push the verdict to the mesh runtime. Not called for the seed run —
   * see {@link startHealthCheckLoop}.
   */
  publish: (status: MeshHealthStatus) => boolean | Promise<boolean>;
  /** Notified for every verdict, seed included. Must not throw. */
  onVerdict?: (verdict: HealthVerdict) => void;
}

export interface HealthCheckLoop {
  /** The most recent verdict, or null before the seed run completes. */
  latest(): HealthVerdict | null;
  /** Stop refreshing. Idempotent. */
  stop(): void;
  /**
   * Resolves once the seed run (and its scheduling) has settled. Exposed
   * for tests; production code never awaits it — see below.
   */
  seeded(): Promise<void>;
}

/**
 * Start the refresh loop. Returns immediately.
 *
 * ## Startup ordering (deliberate)
 *
 * The seed run is scheduled, not awaited, and does NOT publish. Two
 * reasons, both shared with Python and Java:
 *
 * 1. A scaffolded provider's check is an HTTP call to a vendor. Awaiting
 *    it here would stall agent startup for as long as that vendor takes
 *    to answer — a hung vendor would hang the boot.
 * 2. A check that fails during boot (a pool not warm yet, a lazily built
 *    client) must not withdraw an agent that has only just registered.
 *    The agent registers and becomes visible first; the first PUBLISHED
 *    verdict is one TTL later.
 *
 * ## Failure containment
 *
 * A tick can never stop the loop. `runHealthCheck` already converts a
 * throwing check to `degraded`, and every remaining step — the verdict
 * callback, the publish, and the formatting of their own errors — is
 * guarded, with rescheduling in a `finally`. The failure this prevents is
 * specific and silent: one unhandled rejection would leave the agent
 * running with a health check that never runs again, so it could never
 * be withdrawn, and nothing after the first error would appear in the
 * logs.
 *
 * A promise that never settles would be the same silent death by another
 * route, and it is easy to reach: `await fetch(url)` with no
 * `AbortSignal` against a black-holed host hangs forever (Node applies no
 * connect timeout of its own), and a publish waits on a bounded command
 * channel the runtime may have stopped draining. Both are therefore
 * bounded — see {@link HEALTH_CHECK_TIMEOUT_FLOOR_MS} and
 * {@link HEALTH_PUBLISH_TIMEOUT_MS}. Passing the deadline logs and
 * reschedules; an abandoned check reports `degraded`, because a probe
 * that never answered concluded nothing about the upstream and must not
 * withdraw the agent.
 *
 * The timer is `unref`'d: a pending health refresh must not be the reason
 * a finished Node process stays alive.
 */
export function startHealthCheckLoop(
  options: HealthCheckLoopOptions,
): HealthCheckLoop {
  const { agentName, healthCheck, ttlSeconds, publish, onVerdict } = options;
  const periodMs = ttlSeconds * 1000;
  const checkTimeoutMs = Math.max(periodMs, HEALTH_CHECK_TIMEOUT_FLOOR_MS);

  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let latest: HealthVerdict | null = null;

  const scheduleNext = (): void => {
    if (stopped) return;
    timer = setTimeout(() => {
      timer = null;
      void run();
    }, periodMs);
    // `unref` is Node-only; a non-Node timer shim simply keeps a ref.
    timer.unref?.();
  };

  const tick = async (publishVerdict: boolean): Promise<void> => {
    const outcome = await withDeadline(
      runHealthCheck(healthCheck, agentName),
      checkTimeoutMs,
    );

    let verdict: HealthVerdict;
    if (outcome === TIMED_OUT) {
      console.warn(
        `[mesh-health] health check for agent '${agentName}' did not finish ` +
          `within ${Math.round(checkTimeoutMs / 1000)}s — abandoning this run ` +
          `and reporting degraded (the agent keeps heartbeating); the next ` +
          `refresh is scheduled as usual`,
      );
      verdict = {
        status: "degraded",
        checks: { health_check_completed: false },
        errors: [
          `Health check did not complete within ` +
            `${Math.round(checkTimeoutMs / 1000)}s`,
        ],
      };
    } else {
      verdict = outcome;
    }
    latest = verdict;

    if (onVerdict) {
      try {
        onVerdict(verdict);
      } catch (err) {
        console.warn(
          `[mesh-health] health verdict listener for agent '${agentName}' ` +
            `threw: ${describeThrown(err)}`,
        );
      }
    }

    if (verdict.status === "unhealthy") {
      console.warn(
        `[mesh-health] agent '${agentName}' reports UNHEALTHY: ` +
          `${verdict.errors.join("; ") || "(no detail)"}`,
      );
    }

    if (!publishVerdict || stopped) return;

    try {
      // The arrow turns a publish that throws synchronously into a
      // rejection, so both failure modes land in the same catch.
      const reported = await withDeadline(
        (async () => publish(verdict.status))(),
        HEALTH_PUBLISH_TIMEOUT_MS,
      );
      if (reported === TIMED_OUT) {
        console.warn(
          `[mesh-health] reporting health status '${verdict.status}' for agent ` +
            `'${agentName}' to the mesh runtime did not complete within ` +
            `${Math.round(HEALTH_PUBLISH_TIMEOUT_MS / 1000)}s — abandoning ` +
            `this report; the next refresh is scheduled as usual`,
        );
      }
    } catch (err) {
      console.warn(
        `[mesh-health] failed to report health status '${verdict.status}' for ` +
          `agent '${agentName}' to the mesh runtime: ${describeThrown(err)}`,
      );
    }
  };

  const run = (publishVerdict = true): Promise<void> =>
    tick(publishVerdict)
      .catch((err) => {
        // Defence in depth: `tick` is already total. Reaching here means
        // the guarding itself broke, and the loop must still continue.
        console.warn(
          `[mesh-health] health refresh for agent '${agentName}' failed ` +
            `unexpectedly: ${describeThrown(err)}`,
        );
      })
      .finally(() => scheduleNext());

  const seedPromise = run(false);

  return {
    latest: () => latest,
    stop: () => {
      stopped = true;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    },
    seeded: () => seedPromise,
  };
}
