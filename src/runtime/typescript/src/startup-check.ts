/**
 * The `startupCheck` hook and the verdict it produces (RFC #1502).
 *
 * `healthCheck` answers "can I serve *right now*?" — a transient answer, and a
 * failing one only pauses the heartbeat so the registry stops selecting this
 * agent until it recovers. `startupCheck` answers the other question: "is this
 * agent configured such that it can *ever* serve?" A missing API key is not
 * going to fix itself, and today it looks exactly like a vendor outage: the
 * agent sits unregistered, the pod runs, and nothing is loud.
 *
 * **What ships today (RFC #1502 step 1).** `startupCheck` is reported by
 * `GET|HEAD /startupz`, and that is the whole effect: a failing check answers
 * 503 there. Nothing else changes — the agent is not withdrawn, the heartbeat
 * is untouched, `/livez` and `/ready` answer exactly as they did.
 *
 * The agent chart's `startupProbe` still points at `/livez`, so nothing acts on
 * the verdict yet. Repointing it at `/startupz` is step 2, and it is what the
 * hook exists for: a pod whose startup check never passes then never becomes
 * ready, never registers, and ends up in `CrashLoopBackOff` — visible. Until
 * then, `/startupz` is a surface to build against and to scrape.
 *
 * Three properties are deliberate, and each is the OPPOSITE of the
 * corresponding `healthCheck` rule:
 *
 * - **A throw fails the check.** `healthCheck` degrades on a throw (a buggy
 *   probe must not withdraw a working provider from a mesh that may have no
 *   other one). Here the question is whether a possibly-misconfigured agent
 *   should be allowed to come up at all, and an indeterminate answer at boot
 *   is not a reason to let it through. The cost of being wrong is also
 *   asymmetric: a false failure crash-loops one pod that was never serving, a
 *   false pass silently registers a broken one.
 * - **Anything short of a clean pass fails.** `degraded`, an unrecognized
 *   return, `undefined` — all fail. There is no partial credit for "am I
 *   configured".
 * - **There is no cache.** A `startupProbe` stops polling after its first
 *   success, so the check runs a handful of times at most. A TTL cache would
 *   only add a way for the endpoint to answer with a verdict older than the
 *   probe that asked for it.
 *
 * An agent that declares no `startupCheck` passes. Default-true is what makes
 * this purely additive: every existing agent behaves exactly as it did.
 *
 * Both hooks are honoured on EVERY agent type, gateways included (RFC #1502).
 * What this one does there is the milder of the two: it never withdraws a
 * running fan-out point, it only stops a misconfigured one from coming up, and
 * a gateway with a broken config should never come up.
 */
import type { MeshHealthResult } from "./health-check.js";

/**
 * A user startup check. May be sync or async — a startup check is often a
 * bare environment-variable read, and forcing `async` on it would be ceremony
 * with no payoff.
 *
 * The accepted return shapes are `healthCheck`'s, so an author writing both
 * hooks writes them the same way. What differs is the verdict mapping: only a
 * clean `healthy` / `true` passes.
 */
export type MeshStartupCheck = () =>
  | boolean
  | MeshHealthResult
  | Promise<boolean | MeshHealthResult>;

/** A normalized startup verdict — what `/startupz` renders. */
export interface StartupVerdict {
  passed: boolean;
  checks: Record<string, unknown>;
  errors: string[];
}

/** Render anything a `throw` can produce, including non-`Error` values. */
function describe(err: unknown): string {
  if (err instanceof Error) return err.message;
  try {
    return String(err);
  } catch {
    return "<unprintable>";
  }
}

function parse(raw: unknown): StartupVerdict {
  if (typeof raw === "boolean") {
    return {
      passed: raw,
      checks: { startup_check: raw },
      errors: raw ? [] : ["Startup check returned false"],
    };
  }

  if (raw !== null && typeof raw === "object") {
    const result = raw as MeshHealthResult;
    const status = String(result.status ?? "healthy").toLowerCase();
    const passed = status === "healthy";
    const errors = Array.isArray(result.errors) ? [...result.errors] : [];
    return {
      passed,
      checks: result.checks ? { ...result.checks } : {},
      errors:
        passed || errors.length > 0
          ? errors
          : [`Startup check reported '${status}'`],
    };
  }

  const typeName = raw === null ? "null" : typeof raw;
  console.warn(
    `[mesh-startup] startupCheck returned '${typeName}', which is not a ` +
      `startup verdict — failing the startup probe. Return a boolean or a ` +
      `{status, checks, errors} object.`,
  );
  return {
    passed: false,
    checks: { startup_check_return_type: false },
    errors: [
      `Invalid return type: ${typeName}. A startup check returns a boolean ` +
        `or a {status, checks, errors} object.`,
    ],
  };
}

/**
 * Run `check` once and report the verdict. Never rejects — a throwing check
 * must not take the endpoint down with it, and unlike `healthCheck` it must
 * not pass either (see the module comment).
 */
export async function runStartupCheck(
  check: MeshStartupCheck | undefined,
  agentName: string,
): Promise<StartupVerdict> {
  if (!check) {
    return { passed: true, checks: {}, errors: [] };
  }

  try {
    // `parse` is INSIDE the guard, not after it. Reducing the return value
    // reads user-controlled properties — a getter, a Proxy, a lazily-computed
    // `status` — and a throw there is exactly as indeterminate as a throw from
    // the check itself. Parsing outside would leave the one path this hook
    // exists for able to reject out of a function documented never to.
    return parse(await check());
  } catch (err) {
    const reason = describe(err);
    console.warn(
      `[mesh-startup] startupCheck for agent '${agentName}' threw — failing ` +
        `the startup probe: ${reason}`,
    );
    return {
      passed: false,
      checks: { startup_check_execution: false },
      errors: [`Startup check failed: ${reason}`],
    };
  }
}

/**
 * `/startupz` body. Mirrors `/ready`'s shape — a `started` boolean in place of
 * `ready`, plus `reason`/`errors` on failure — so an operator reads the two
 * probes the same way. Python's `build_startupz_response` emits the same keys.
 */
export function buildStartupBody(
  agentName: string,
  verdict: StartupVerdict,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    started: verdict.passed,
    agent: agentName,
    ...extra,
    timestamp: new Date().toISOString(),
  };
  if (Object.keys(verdict.checks).length > 0) {
    body.checks = verdict.checks;
  }
  if (!verdict.passed) {
    body.reason = "Startup check failed";
    body.errors = verdict.errors;
  }
  return body;
}

/** HTTP status for a startup verdict: 200 pass, 503 fail. */
export function startupStatusCodeFor(verdict: StartupVerdict): 200 | 503 {
  return verdict.passed ? 200 : 503;
}
