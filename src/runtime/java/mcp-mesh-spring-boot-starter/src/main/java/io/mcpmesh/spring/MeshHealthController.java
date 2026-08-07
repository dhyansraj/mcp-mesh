package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.stereotype.Controller;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Health endpoint controller for MCP Mesh Java agents.
 *
 * <p>Provides {@code GET}/{@code HEAD} for {@code /health}, {@code /ready},
 * {@code /livez} and {@code /startupz} for Kubernetes probes, load balancers,
 * and Docker Compose healthchecks.
 *
 * <p>Unlike Python and TypeScript, which serve their provider and gateway
 * probes from two different places, Java serves every agent type from this one
 * controller — the starter mounts it whatever the agent is. Since RFC #1502
 * every endpoint here answers the same way for every agent type, so there is
 * nothing left for the other two runtimes to keep in step with either.
 *
 * <p>Liveness and readiness are deliberately DIFFERENT endpoints (issue #1467).
 * When both probes share a URL, anything that makes an agent unready also makes
 * Kubernetes restart it — a remedy that cannot fix a dependency outage and that
 * erases the evidence the agent was failing. {@code /livez} therefore answers
 * 200 unconditionally, while {@code /ready} reports whether the agent should be
 * receiving traffic.
 *
 * <p>{@code /ready} reports whether the mesh runtime is up, on every agent type
 * (RFC #1502). The user's {@link io.mcpmesh.MeshHealthCheck} does NOT reach it.
 * A failing check already withdraws the agent by pausing the heartbeat — the
 * registry ages it out and resolution stops selecting it — and answering 503
 * here as well is not defence in depth but a regression: mesh traffic traverses
 * the Kubernetes Service, so emptying the Service endpoints while the registry
 * may still be selecting the agent turns a consumer's failover into a
 * connection error.
 *
 * <p>Readiness is not unconditional either. {@link io.mcpmesh.MeshStartupCheck}
 * defaults to passing, so {@code /startupz} answers 200 before the mesh runtime
 * has started in the Spring lifecycle; without the runtime floor a pod could go
 * Ready with no runtime behind it. The floor is also the only probe that can
 * notice a runtime that dies while the JVM lives, since {@code /livez} consults
 * nothing.
 *
 * <p>This subsumes #1488's gateway carve-out: readiness now reports the runtime
 * on a gateway and on a provider alike, so there is no longer a branch to take.
 * Nor is there one anywhere else — RFC #1502 step 3 reversed #1473's route/A2A
 * exemption in {@link MeshHealthCheckScheduler} too, so no code in this package
 * asks what type of agent it is running in.
 *
 * <p>{@code /health} is unchanged: it carries the verdict, its {@code checks}
 * and its {@code errors}, and answers 503 when the verdict is not healthy.
 * Nothing probes it, so its status code is free to carry information — which
 * means {@code /ready} and {@code /health} now diverge on every agent type, by
 * design.
 */
@Controller
public class MeshHealthController {

    private final MeshRuntime runtime;
    private final MeshHealthCheckRegistry healthChecks;
    private final MeshStartupCheckRegistry startupChecks;

    public MeshHealthController(MeshRuntime runtime) {
        this(runtime, null, null);
    }

    public MeshHealthController(MeshRuntime runtime, MeshHealthCheckRegistry healthChecks) {
        this(runtime, healthChecks, null);
    }

    public MeshHealthController(MeshRuntime runtime,
                                MeshHealthCheckRegistry healthChecks,
                                MeshStartupCheckRegistry startupChecks) {
        this.runtime = runtime;
        this.healthChecks = healthChecks;
        this.startupChecks = startupChecks;
    }

    /**
     * The effective verdict: the user's health check, floored by the mesh
     * runtime state.
     *
     * <p>The floor is not redundant with the user's check. A check that probes
     * a vendor API says nothing about whether this agent is registered and
     * reachable; a runtime that is down means no traffic should arrive here
     * whatever the vendor's status is. Taking the worse of the two is the only
     * answer that is true in both directions.
     */
    private MeshHealthStatus effectiveStatus(MeshHealth latest) {
        boolean running = runtime != null && runtime.isRunning();
        if (!running) {
            return MeshHealthStatus.UNHEALTHY;
        }
        return latest == null ? MeshHealthStatus.HEALTHY : latest.status();
    }

    /**
     * The readiness verdict: the mesh runtime state, and nothing else (RFC
     * #1502).
     *
     * <p>Takes no {@link MeshHealth} argument on purpose. A parameter the method
     * ignores is an invitation to start consulting it again, and the whole point
     * of this change is that the user's check has no path to the readiness
     * probe. See the class comment for why 503-ing readiness on a failing check
     * makes an outage worse rather than safer.
     */
    private MeshHealthStatus readyStatus() {
        return runtime != null && runtime.isRunning()
            ? MeshHealthStatus.HEALTHY
            : MeshHealthStatus.UNHEALTHY;
    }

    /**
     * Snapshot the latest verdict ONCE per request.
     *
     * <p>{@code latest} is written by the health-check thread between calls, so
     * reading it more than once while building a response can mix two different
     * results — a body whose {@code status} came from one verdict and whose
     * {@code checks} / {@code errors} came from the next. Every handler takes
     * one snapshot and derives the whole response from it.
     */
    private MeshHealthCheckRegistry.Result latestResult() {
        return healthChecks == null ? null : healthChecks.latest();
    }

    private static MeshHealth healthOf(MeshHealthCheckRegistry.Result result) {
        return result == null ? null : result.health();
    }

    /**
     * Whether a status maps to 200. Only {@link MeshHealthStatus#HEALTHY} does —
     * exactly Python's {@code build_health_response}, which is {@code 200 if
     * status == "healthy" else 503}.
     *
     * <p>So {@code degraded} answers 503 on {@code /health} while the agent
     * keeps heartbeating and stays in dependency resolution. Nothing probes
     * {@code /health}, so its status code is free to carry the verdict. The
     * probe the kubelet actually reads is {@code /ready}, and the only statuses
     * that reach this from there are the two {@link #readyStatus} produces from
     * the runtime state.
     */
    private static boolean serving(MeshHealthStatus status) {
        return status == MeshHealthStatus.HEALTHY;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        MeshHealthCheckRegistry.Result result = latestResult();
        MeshHealthStatus status = effectiveStatus(healthOf(result));

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", status.wireValue());
        if (runtime != null && runtime.getAgentSpec() != null) {
            body.put("agent", runtime.getAgentSpec().getName());
        }
        if (result != null) {
            body.put("checks", result.health().checks());
            body.put("errors", result.health().errors());
            body.put("timestamp", result.timestamp().toString());
        }
        return ResponseEntity.status(serving(status) ? 200 : 503).body(body);
    }

    @RequestMapping(value = "/health", method = RequestMethod.HEAD)
    public ResponseEntity<Void> healthHead() {
        return ResponseEntity.status(
            serving(effectiveStatus(healthOf(latestResult()))) ? 200 : 503).build();
    }

    /**
     * Kubernetes readiness probe.
     *
     * <p>Reports whether the mesh runtime is up, and nothing else (see
     * {@link #readyStatus}). It does NOT restart anything — see the class
     * comment on why this is a separate endpoint from {@code /livez}, and on why
     * the user's health check reaches {@code /health} but not this.
     */
    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> ready() {
        MeshHealthStatus status = readyStatus();
        boolean ready = serving(status);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ready", ready);
        body.put("status", status.wireValue());
        if (!ready) {
            body.put("reason", "mesh runtime is not running");
        }
        return ResponseEntity.status(ready ? 200 : 503).body(body);
    }

    @RequestMapping(value = "/ready", method = RequestMethod.HEAD)
    public ResponseEntity<Void> readyHead() {
        // Same verdict as GET — a HEAD probe that disagreed with the GET would
        // be the #1488 bug again for anyone who configured HEAD.
        return ResponseEntity.status(serving(readyStatus()) ? 200 : 503).build();
    }

    /**
     * Kubernetes liveness probe — always 200 while the application is serving.
     *
     * <p>Deliberately does NOT consult {@link MeshRuntime#isRunning()} or the
     * user's health check: the mesh runtime starts late in the Spring
     * lifecycle, so a liveness probe gated on it would restart-loop an agent
     * through a slow boot, and a restart cannot fix a vendor outage — it only
     * erases the evidence. Reaching this handler at all proves the servlet
     * container is alive, which is the only failure a restart can repair.
     */
    @GetMapping("/livez")
    public ResponseEntity<Map<String, Object>> livez() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("alive", true);
        // Best-effort agent name. `runtime` is a lazy proxy — resolving it can
        // raise while the context is still coming up, and liveness must answer
        // 200 regardless of whether the name is available.
        try {
            if (runtime != null && runtime.getAgentSpec() != null) {
                body.put("agent", runtime.getAgentSpec().getName());
            }
        } catch (Exception ignored) {
            // Name is decoration; liveness is not conditional on it.
        }
        body.put("timestamp", Instant.now().toString());
        return ResponseEntity.ok(body);
    }

    @RequestMapping(value = "/livez", method = RequestMethod.HEAD)
    public ResponseEntity<Void> livezHead() {
        return ResponseEntity.ok().build();
    }

    /**
     * Run the agent's {@link io.mcpmesh.MeshStartupCheck}, or pass when none is
     * declared.
     *
     * <p>Never throws: {@link MeshStartupCheckRegistry#execute} already turns a
     * throwing check into a failing verdict, and a missing registry (the
     * two-argument constructor, used by tests and by anyone wiring this
     * controller by hand) means no check, which passes.
     *
     * <p>Deliberately does NOT consult {@link MeshRuntime#isRunning()}. The mesh
     * runtime starts late in the Spring lifecycle, and {@code startupProbe}
     * exists precisely to cover that window — flooring the startup verdict on
     * the runtime would make the probe fail for the entire boot it is supposed
     * to be waiting through.
     */
    private MeshStartupCheckRegistry.Verdict startupVerdict() {
        if (startupChecks == null) {
            return MeshStartupCheckRegistry.Verdict.pass();
        }
        return startupChecks.execute();
    }

    /**
     * Kubernetes startup probe (RFC #1502).
     *
     * <p>Reports whether this agent is configured well enough to serve at all,
     * as opposed to {@code /ready}'s "should traffic reach me now". The chart's
     * {@code startupProbe} asks for this path, so a check that never passes
     * keeps the pod from ever becoming ready and lands it in
     * {@code CrashLoopBackOff}, where a misconfiguration is visible instead of
     * looking like a vendor outage. {@code /livez}, {@code /ready} and the
     * heartbeat are unaffected by it.
     *
     * <p>A NEW endpoint rather than a reuse of {@code /livez}: the chart points
     * both {@code startupProbe} and {@code livenessProbe} at {@code /livez}, and
     * an endpoint cannot tell which probe called it, so sharing one would let a
     * failing startup check kill a running pod every ten seconds.
     *
     * <p>The check runs on every hit. A {@code startupProbe} stops polling after
     * its first success, so there is nothing to cache.
     */
    @GetMapping("/startupz")
    public ResponseEntity<Map<String, Object>> startupz() {
        MeshStartupCheckRegistry.Verdict verdict = startupVerdict();

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("started", verdict.passed());
        // Best-effort agent name, for the same reason as /livez: `runtime` is a
        // lazy proxy and resolving it can raise while the context comes up —
        // which is exactly when the startup probe fires.
        try {
            if (runtime != null && runtime.getAgentSpec() != null) {
                body.put("agent", runtime.getAgentSpec().getName());
            }
        } catch (Exception ignored) {
            // Name is decoration; the verdict is not conditional on it.
        }
        if (!verdict.checks().isEmpty()) {
            body.put("checks", verdict.checks());
        }
        if (!verdict.passed()) {
            body.put("reason", "Startup check failed");
            body.put("errors", verdict.errors());
        }
        body.put("timestamp", Instant.now().toString());
        return ResponseEntity.status(verdict.passed() ? 200 : 503).body(body);
    }

    @RequestMapping(value = "/startupz", method = RequestMethod.HEAD)
    public ResponseEntity<Void> startupzHead() {
        // Same verdict as GET — a HEAD probe that disagreed with the GET would
        // be the #1488 bug again for anyone who configured HEAD.
        return ResponseEntity.status(startupVerdict().passed() ? 200 : 503).build();
    }
}
