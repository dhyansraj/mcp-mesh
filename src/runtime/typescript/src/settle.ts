/**
 * Settling-window dependency grace (issue #1193).
 *
 * Dependency injection resolves asynchronously: declared dependencies become
 * available when the first full heartbeat cycle completes and
 * `dependency_available` events land. A call that fires during that settling
 * window would otherwise see a declared-but-unresolved dependency as `null`
 * even though resolution typically lands moments later.
 *
 * Process-wide settle state:
 *
 * - The settle window is ANCHORED at the first dependency declaration (the
 *   first `registerDeclared()` call during startup wiring) — not at module
 *   import — so slow imports or pre-registration work never eat into the
 *   grace budget. The agent is **unsettled** from that anchor until EITHER
 *   every declared dependency has resolved at least once OR the settle
 *   window (`MCP_MESH_SETTLE_TIMEOUT` seconds, default 20) expires.
 * - While unsettled, invocation paths await — bounded by the REMAINING settle
 *   budget — a per-dependency promise that the existing
 *   `handleDependencyAvailable` handling resolves the moment the dependency
 *   lands. Resolution at 800ms unblocks at 800ms; the budget is a ceiling
 *   only, never a sleep.
 * - Once settled — either way — the latch is permanent: calls never touch the
 *   wait primitives again and fail-fast behavior is byte-identical to the
 *   pre-grace behavior (unresolved deps inject `null` exactly as before).
 *
 * Scope (deliberate): the grace covers the dependency-injection invocation
 * paths only — the MCP tool execute wrapper, the claim-dispatch handler, and
 * the `mesh.route` middleware. Module-scope captured deps and `mesh.llm`
 * provider/filter assembly (registration-time, with its own update mechanism)
 * are NOT covered.
 *
 * This is environmental, not a declaration mistake: strict-DI style
 * diagnostics never interact with the settle window in any way.
 */

export const SETTLE_TIMEOUT_DEFAULT_SECONDS = 20;

/**
 * Cached per-process resolution of MCP_MESH_SETTLE_TIMEOUT — the settle
 * window is a process-level posture, not a per-call toggle.
 */
let cachedTimeoutSecs: number | null = null;

/**
 * Settle window in seconds. `0` disables the grace entirely.
 *
 * Configurable via `MCP_MESH_SETTLE_TIMEOUT` (float seconds, default 20).
 * Read once per process and cached. Negative or unparseable values fall
 * back to the default with a warning.
 */
export function getSettleTimeoutSeconds(): number {
  if (cachedTimeoutSecs === null) {
    const raw = process.env.MCP_MESH_SETTLE_TIMEOUT;
    if (raw === undefined || raw.trim() === "") {
      cachedTimeoutSecs = SETTLE_TIMEOUT_DEFAULT_SECONDS;
    } else {
      const parsed = Number.parseFloat(raw);
      if (!Number.isFinite(parsed) || parsed < 0) {
        console.warn(
          `MCP_MESH_SETTLE_TIMEOUT must be >= 0 (got '${raw}'); ` +
            `using default ${SETTLE_TIMEOUT_DEFAULT_SECONDS}s`,
        );
        cachedTimeoutSecs = SETTLE_TIMEOUT_DEFAULT_SECONDS;
      } else {
        cachedTimeoutSecs = parsed;
      }
    }
  }
  return cachedTimeoutSecs;
}

interface DepWaiter {
  promise: Promise<void>;
  resolve: () => void;
}

/** A declared-but-unresolved dependency an invocation is about to inject. */
export interface PendingSettleDep {
  depKey: string;
  capability: string;
}

/**
 * Process-wide settle latch + per-dependency resolution promises.
 *
 * Dependencies are tracked at the AGENT level as the union of declared
 * dependency keys across all tools/routes (the same composite
 * `"<owner>:dep_<N>"` keys the resolution paths already use). The latch
 * flips eagerly when the last declared key resolves, or lazily when
 * `isSettled()` observes window expiry.
 */
export class SettleState {
  /** Window anchor — set by the FIRST registerDeclared() call. */
  private startMs: number | null = null;
  private readonly declared = new Set<string>();
  private readonly resolved = new Set<string>();
  private readonly waiters = new Map<string, DepWaiter>();
  /** Capabilities whose first wait was already logged (INFO once). */
  private readonly loggedWaits = new Set<string>();
  private settled = false;
  /**
   * Diagnostic counter: number of actual bounded waits performed. Used by
   * tests to prove the settled steady-state path never touches the wait
   * primitives.
   */
  waitCount = 0;

  /**
   * Record a declared dependency key (registration time).
   *
   * The FIRST declaration anchors the settle window — the window measures
   * topology convergence from the moment the agent starts declaring
   * dependencies, not from module import.
   */
  registerDeclared(depKey: string): void {
    if (this.startMs === null) {
      this.startMs = Date.now();
    }
    this.declared.add(depKey);
  }

  /**
   * Record a resolution and wake any waiter on this key.
   *
   * "Resolved at least once" semantics: a later unavailability does NOT
   * un-resolve the key — the settle window only measures initial topology
   * convergence.
   */
  markResolved(depKey: string): void {
    this.resolved.add(depKey);
    const waiter = this.waiters.get(depKey);
    if (waiter) {
      waiter.resolve();
    }
    if (!this.settled && this.declared.size > 0) {
      let all = true;
      for (const key of this.declared) {
        if (!this.resolved.has(key)) {
          all = false;
          break;
        }
      }
      if (all) {
        // Eager latch: the LAST declared dependency just resolved.
        this.settled = true;
      }
    }
  }

  /**
   * Migrate a declared/resolved/waiting key to a new name. Needed by the
   * Express route registry whose placeholder route IDs are remapped to
   * `METHOD:path` after introspection.
   *
   * A pending waiter on the old key is never dropped unresolved: when the
   * new key already resolved it is released immediately; on a key
   * collision (the new key already has its own waiter) the displaced
   * waiter is chained to the survivor so both resolve together.
   */
  renameDeclared(oldKey: string, newKey: string): void {
    if (this.declared.delete(oldKey)) {
      this.declared.add(newKey);
    }
    if (this.resolved.delete(oldKey)) {
      this.resolved.add(newKey);
    }
    const waiter = this.waiters.get(oldKey);
    if (waiter) {
      this.waiters.delete(oldKey);
      if (this.resolved.has(newKey)) {
        // The surviving key already resolved — release the migrated waiter.
        waiter.resolve();
      } else {
        const survivor = this.waiters.get(newKey);
        if (survivor) {
          // Chain to the survivor: when the surviving key's resolution
          // lands, the displaced waiter wakes too.
          void survivor.promise.then(() => waiter.resolve());
        } else {
          this.waiters.set(newKey, waiter);
        }
      }
    }
  }

  /** Permanent latch check; flips on window expiry or timeout=0. */
  isSettled(): boolean {
    if (this.settled) {
      return true;
    }
    const timeoutSecs = getSettleTimeoutSeconds();
    if (timeoutSecs <= 0) {
      this.settled = true;
      return true;
    }
    if (this.startMs === null) {
      // Window not yet anchored — no dependency has been declared, so
      // nothing can be pending. Report settled WITHOUT latching: the
      // window must still open when the first declaration lands.
      return true;
    }
    if (Date.now() - this.startMs >= timeoutSecs * 1000) {
      this.settled = true;
      return true;
    }
    return false;
  }

  /** Remaining settle budget in milliseconds (>= 0). */
  remainingMs(): number {
    if (this.startMs === null) {
      return 0;
    }
    return Math.max(
      0,
      getSettleTimeoutSeconds() * 1000 - (Date.now() - this.startMs),
    );
  }

  isResolved(depKey: string): boolean {
    return this.resolved.has(depKey);
  }

  private waiterFor(depKey: string): DepWaiter {
    let waiter = this.waiters.get(depKey);
    if (!waiter) {
      let resolveFn: () => void = () => {};
      const promise = new Promise<void>((resolve) => {
        resolveFn = resolve;
      });
      waiter = { promise, resolve: resolveFn };
      this.waiters.set(depKey, waiter);
    }
    return waiter;
  }

  /**
   * Wait until `depKey` resolves or the remaining settle budget elapses.
   * Event-driven: the dependency's resolution promise is raced against a
   * timer bounded by the remaining window — never a fixed sleep.
   */
  async waitFor(depKey: string, capability: string): Promise<void> {
    const remaining = this.remainingMs();
    if (remaining <= 0 || this.resolved.has(depKey)) {
      return;
    }
    const waiter = this.waiterFor(depKey);
    const remainingSecs = (remaining / 1000).toFixed(1);
    const message = `waiting up to ${remainingSecs}s for dependency '${capability}' to settle`;
    if (!this.loggedWaits.has(capability)) {
      // One INFO line per capability per process; later waits at DEBUG
      // (matches the Python/Java log cadence).
      this.loggedWaits.add(capability);
      console.log(message);
    } else {
      console.debug(message);
    }
    this.waitCount++;
    let timer: NodeJS.Timeout | undefined;
    try {
      await Promise.race([
        waiter.promise,
        new Promise<void>((resolve) => {
          timer = setTimeout(resolve, remaining);
          // Never keep the process alive just for a settle timer.
          timer.unref?.();
        }),
      ]);
    } finally {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    }
    // On timeout we simply proceed — the unresolved dep injects null
    // exactly as today; the existing unresolved-dep handling covers the
    // diagnostic (no double-logging here).
  }

  /**
   * Await every pending dependency in turn. The per-wait budget is the
   * REMAINING window, so the total wait is bounded by the settle window
   * regardless of how many deps are pending.
   */
  async awaitPending(pending: PendingSettleDep[]): Promise<void> {
    for (const { depKey, capability } of pending) {
      await this.waitFor(depKey, capability);
    }
  }
}

let settleState = new SettleState();

/** Get the process-wide settle state. */
export function getSettleState(): SettleState {
  return settleState;
}

/** Replace the settle state and drop the cached timeout (test support). */
export function resetSettleStateForTests(): void {
  settleState = new SettleState();
  cachedTimeoutSecs = null;
}
