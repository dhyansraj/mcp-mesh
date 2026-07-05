package io.mcpmesh.spring;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Settling-window dependency grace (issue #1193).
 *
 * <p>Dependency injection resolves asynchronously: declared dependencies
 * become available when the first full heartbeat cycle completes and
 * {@code dependency_available} events land. A tool call (or {@code @MeshRoute}
 * request) that fires during that settling window would otherwise see a
 * declared-but-unresolved dependency as {@code null} / unavailable even
 * though resolution typically lands moments later.
 *
 * <p>Process-wide settle state:
 * <ul>
 *   <li>The agent is <b>unsettled</b> from process start until EITHER every
 *       declared dependency capability has resolved at least once OR the
 *       settle window (wall clock from start,
 *       {@code MCP_MESH_SETTLE_TIMEOUT} seconds, default 20) expires.</li>
 *   <li>While unsettled, invocation paths block — bounded by the REMAINING
 *       settle budget — on a per-key {@link CountDownLatch} that the
 *       existing dependency-update handling counts down the moment a real
 *       endpoint lands. Resolution at 800ms unblocks at 800ms; the budget is
 *       a ceiling only, never a sleep. Blocking is safe: both the MCP tool
 *       dispatch and Spring MVC route handling run on dedicated request
 *       threads (Tomcat/Spring pool), never an event loop.</li>
 *   <li>Once settled — either way — the latch is permanent: calls never
 *       touch the wait primitives again and fail-fast behavior is
 *       byte-identical to the pre-grace behavior (unresolved deps inject
 *       {@code null} / unavailable proxies exactly as before).</li>
 * </ul>
 *
 * <p>Key spaces (two, by consumer type):
 * <ul>
 *   <li><b>Tool wrappers</b> use per-consumer-slot composite keys
 *       ({@code funcId:dep_N}, mirroring the Python/TypeScript composite
 *       keys), counted down by {@link MeshToolWrapper#updateDependency}
 *       AFTER that wrapper's array slot is written. Capability-level
 *       keying was wrong here: with tools A and B both depending on the
 *       same capability, A's resolution event would wake B's waiter
 *       before B's slot was written — B proceeded with {@code null}.</li>
 *   <li><b>{@code @MeshRoute} requests</b> use capability keys, counted
 *       down by {@link MeshDependencyInjector#updateToolDependency}. That
 *       keying is safe for routes because every route resolves through
 *       the injector's SHARED per-capability proxy, which is updated
 *       ({@code updateEndpoint}) immediately before the countdown — a
 *       woken route request re-reads a live proxy regardless of which
 *       consumer's event fired.</li>
 * </ul>
 *
 * <p>Scope (deliberate): the grace covers the dependency-injection
 * invocation paths only — {@link MeshToolWrapper} argument building and the
 * {@code @MeshRoute} interceptor. Startup-hook dependency usage and
 * {@code @MeshLlm} provider/filter assembly (registration-time, with its own
 * update mechanism) are NOT covered.
 *
 * <p>This is environmental, not a declaration mistake: strict-DI style
 * diagnostics never interact with the settle window in any way.
 */
public final class MeshSettleState {

    private static final Logger log = LoggerFactory.getLogger(MeshSettleState.class);

    /** Default settle window in seconds. */
    public static final double SETTLE_TIMEOUT_DEFAULT_SECONDS = 20.0;

    /**
     * Process-wide (JVM-static) instance. Static on purpose: the settle
     * window is a process-level posture and the consumers (wrapper
     * registry, event processor, route interceptor) live in the Spring
     * context while resolution events arrive from the Rust core's event
     * loop. NOTE: being static, the state PERSISTS across Spring context
     * refreshes in the same JVM (e.g. test suites rebuilding the
     * application context) — acceptable because the window is bounded by
     * expiry: a refreshed context inherits at most the remainder of the
     * original window, never a fresh or unbounded one. Tests reset via
     * {@link #resetForTests()}.
     */
    private static volatile MeshSettleState instance = new MeshSettleState();

    /** Get the process-wide settle state. */
    public static MeshSettleState getInstance() {
        return instance;
    }

    /**
     * Replace the settle state with a DISABLED one (timeout=0) — test
     * support only. Default-disabled so a test class that exercised the
     * grace never leaks a live window into subsequent test classes in the
     * same JVM; suites that test the grace arm an explicit window via
     * {@link #resetForTests(double)} per test. Installed suite-wide before
     * EVERY test class by the auto-registered
     * {@code MeshSettleDisabledExtension} (test sources), so the opt-out
     * never depends on test-class ordering.
     */
    static void resetForTests() {
        instance = new MeshSettleState(0.0);
    }

    /** Replace the settle state with an explicit window (test support only). */
    static void resetForTests(double timeoutSeconds) {
        instance = new MeshSettleState(timeoutSeconds);
    }

    /**
     * Window anchor: set when the static instance is created on first
     * class load — i.e. the window anchors at first CLASS TOUCH, not at
     * the first dependency declaration as in Python/TypeScript; that is
     * acceptable because in practice the class is first touched during
     * startup wrapper/route wiring, moments before the first declaration,
     * so the two anchors coincide.
     */
    private final long startNanos = System.nanoTime();
    /** Read once per process (per instance) — process-level posture. */
    private final double timeoutSeconds;
    private final Set<String> declared = ConcurrentHashMap.newKeySet();
    private final Set<String> resolved = ConcurrentHashMap.newKeySet();
    private final Map<String, CountDownLatch> latches = new ConcurrentHashMap<>();
    /** Capabilities whose first wait was already logged at INFO. */
    private final Set<String> loggedWaits = ConcurrentHashMap.newKeySet();
    private volatile boolean settled;
    /**
     * Diagnostic counter: number of actual bounded waits performed. Used by
     * tests to prove the settled steady-state path never touches the wait
     * primitives.
     */
    private volatile int waitCount;

    private MeshSettleState() {
        this(readTimeoutSeconds(System.getenv("MCP_MESH_SETTLE_TIMEOUT")));
    }

    private MeshSettleState(double timeoutSeconds) {
        this.timeoutSeconds = timeoutSeconds;
    }

    static double readTimeoutSeconds(String raw) {
        if (raw == null || raw.trim().isEmpty()) {
            return SETTLE_TIMEOUT_DEFAULT_SECONDS;
        }
        try {
            double parsed = Double.parseDouble(raw.trim());
            if (!Double.isFinite(parsed) || parsed < 0) {
                log.warn("MCP_MESH_SETTLE_TIMEOUT must be >= 0 (got '{}'); using default {}s",
                    raw, (long) SETTLE_TIMEOUT_DEFAULT_SECONDS);
                return SETTLE_TIMEOUT_DEFAULT_SECONDS;
            }
            return parsed;
        } catch (NumberFormatException e) {
            log.warn("MCP_MESH_SETTLE_TIMEOUT is not a number (got '{}'); using default {}s",
                raw, (long) SETTLE_TIMEOUT_DEFAULT_SECONDS);
            return SETTLE_TIMEOUT_DEFAULT_SECONDS;
        }
    }

    /**
     * Record a declared dependency key (registration time).
     *
     * <p>Tool wrappers declare per-consumer-slot composite keys
     * ({@code funcId:dep_N}); routes declare capability keys — see the
     * class javadoc's key-spaces section.
     */
    public void registerDeclared(String depKey) {
        if (depKey == null || depKey.isEmpty()) {
            return;
        }
        declared.add(depKey);
    }

    /**
     * Record a resolution and wake any waiter on this key.
     *
     * <p>"Resolved at least once" semantics: a later unavailability does NOT
     * un-resolve the key — the settle window only measures initial
     * topology convergence. The agent-settled latch flips on per-key
     * resolution: every declared key (per-slot for tools, per-capability
     * for routes) must resolve before the agent settles eagerly.
     */
    public void markResolved(String depKey) {
        if (depKey == null || depKey.isEmpty()) {
            return;
        }
        resolved.add(depKey);
        latches.computeIfAbsent(depKey, c -> new CountDownLatch(1)).countDown();
        if (!settled && !declared.isEmpty() && resolved.containsAll(declared)) {
            // Eager latch: the LAST declared dependency just resolved.
            settled = true;
        }
    }

    /** Permanent latch check; flips on window expiry or timeout=0. */
    public boolean isSettled() {
        if (settled) {
            return true;
        }
        if (timeoutSeconds <= 0 || elapsedSeconds() >= timeoutSeconds) {
            settled = true;
            return true;
        }
        return false;
    }

    /** Remaining settle budget in milliseconds (>= 0). */
    public long remainingMillis() {
        double remaining = (timeoutSeconds - elapsedSeconds()) * 1000.0;
        return remaining > 0 ? (long) remaining : 0L;
    }

    public boolean isResolved(String depKey) {
        return resolved.contains(depKey);
    }

    /** Test accessor: whether {@code depKey} was registered as declared. */
    boolean isDeclared(String depKey) {
        return declared.contains(depKey);
    }

    int getWaitCount() {
        return waitCount;
    }

    private double elapsedSeconds() {
        return (System.nanoTime() - startNanos) / 1_000_000_000.0;
    }

    /**
     * Block the current (request) thread until {@code depKey} resolves
     * or the remaining settle budget elapses. Event-driven: the per-key
     * latch is counted down by the existing dependency-update handling,
     * so resolution unblocks immediately — never a fixed sleep.
     *
     * <p>On timeout the caller simply proceeds — the unresolved dep injects
     * {@code null} / unavailable exactly as today; the existing
     * unresolved-dep warning paths cover the diagnostic.
     *
     * @param depKey     wait key — per-slot composite key for tools,
     *                   capability for routes (see class javadoc)
     * @param capability human-readable capability name for the log lines
     */
    public void awaitDependency(String depKey, String capability) {
        long remainingMs = remainingMillis();
        if (remainingMs <= 0 || resolved.contains(depKey)) {
            return;
        }
        CountDownLatch latch = latches.computeIfAbsent(depKey, c -> new CountDownLatch(1));
        if (latch.getCount() == 0) {
            return;
        }
        if (loggedWaits.add(capability)) {
            log.info("waiting up to {}s for dependency '{}' to settle",
                String.format("%.1f", remainingMs / 1000.0), capability);
        } else {
            log.debug("waiting up to {}s for dependency '{}' to settle",
                String.format("%.1f", remainingMs / 1000.0), capability);
        }
        waitCount++;
        try {
            latch.await(remainingMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
