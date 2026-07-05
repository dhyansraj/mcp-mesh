package com.example.serviceview;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.types.MeshServiceUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * uc37 fixture — Java consumer proving RFC #1280 {@code @McpMeshService}
 * service views end-to-end.
 *
 * <p>Two views are discovered from this package:
 * <ul>
 *   <li>{@link ReportService} — alpha/bravo (optional) + charlie (required),
 *       three capabilities backed by three DIFFERENT Python provider agents.</li>
 *   <li>{@link FlooredService} — alpha+bravo with {@code minAvailable = 2}.</li>
 * </ul>
 *
 * <p>The registration must expand to exactly THREE dependency edges under the
 * synthetic {@code __mesh_service_deps} tool (the FlooredService bindings
 * dedupe onto the ReportService edges), so the registry reports
 * {@code total_dependencies == 3} (tc04).
 *
 * <p>The {@code @MeshTool} surfaces below are the observation points the TCs
 * call via {@code meshctl call}:
 * <ul>
 *   <li>{@code view_report} — calls all three ReportService methods, catching
 *       per-method failures, and reports which agent served each (flat
 *       {@code <method>_agent}/{@code <method>_cap} keys on success,
 *       {@code <method>_error}/{@code <method>_error_message} on failure).
 *       Proves per-method multi-agent resolution (tc01) and independent
 *       degradation/rebinding (tc02).</li>
 *   <li>{@code view_critical} — calls the REQUIRED {@code charlie()} method
 *       UNGUARDED. With provider-charlie down the call fails as a tool ERROR
 *       naming the missing edge: the facade raises
 *       {@code MeshToolUnavailableException} and the wrapper surfaces it
 *       through the ordinary error path (tc03). NOTE: deliberately NOT the
 *       issue #1273 pre-invoke {@code {"error":"dependency_unavailable"}}
 *       envelope — that refusal is a property of tool-DECLARED dependency
 *       slots ({@code @MeshTool(dependencies=...)}). A view is a CLASS-LEVEL
 *       edge (same class as {@code @MeshDependsOn}): the framework cannot
 *       know which tool bodies call which view methods, so RFC #1280's
 *       contract is "availability per method, identical to standalone
 *       edges". Do not rewrite this fixture (or tc03) to expect the
 *       envelope; a consumer wanting the pre-invoke refusal declares the
 *       capability as a tool dependency slot.</li>
 *   <li>{@code view_floored} — calls {@code FlooredService.alphaFloored()},
 *       reporting a floor breach via the typed
 *       {@link MeshServiceUnavailableException} getters. With provider-bravo
 *       down the ALPHA call must fail on the floor even though provider-alpha
 *       is healthy (tc05). Any other exception propagates on purpose: a
 *       MeshToolUnavailableException here would mean the floor did NOT gate
 *       the call, and the raw tool error fails the tc05 assertions.</li>
 * </ul>
 */
@MeshAgent(
    name = "java-view-consumer",
    version = "1.0.0",
    description = "uc37 consumer proving RFC #1280 @McpMeshService service views",
    port = 9201
)
@SpringBootApplication
public class JavaViewConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(JavaViewConsumerApplication.class);

    public static void main(String[] args) {
        log.info("Starting java-view-consumer (uc37 RFC #1280 service views)...");
        SpringApplication.run(JavaViewConsumerApplication.class, args);
    }

    @Service
    static class ViewTools {

        private final ReportService reportService;
        private final FlooredService flooredService;

        /**
         * Constructor injection of the auto-registered facade beans — the
         * facade must exist before user singletons are wired (registrar runs
         * as a BeanDefinitionRegistryPostProcessor). A boot failure here means
         * discovery/registration broke.
         */
        ViewTools(ReportService reportService, FlooredService flooredService) {
            this.reportService = reportService;
            this.flooredService = flooredService;
        }

        @MeshTool(
            capability = "view_report",
            description = "Call all three ReportService view methods and report which agent served each")
        public Map<String, Object> reportAll() {
            Map<String, Object> out = new LinkedHashMap<>();
            reportOne(out, "alpha", () -> reportService.alpha());
            reportOne(out, "bravo", () -> reportService.bravo());
            reportOne(out, "charlie", () -> reportService.charlie());
            return out;
        }

        @MeshTool(
            capability = "view_critical",
            description = "Call the REQUIRED charlie() view method unguarded (tc03 refusal surface)")
        public Map<String, Object> callCharlie() {
            // Deliberately unguarded: with provider-charlie down, charlie()
            // raises MeshToolUnavailableException here and the wrapper
            // surfaces it as a tool error naming the edge — class-level view
            // edges get no #1273 pre-invoke envelope (see class javadoc).
            Map<String, Object> payload = reportService.charlie();
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("status", "ok");
            out.put("charlie_agent", payload.get("agent"));
            return out;
        }

        @MeshTool(
            capability = "view_floored",
            description = "Call FlooredService.alphaFloored(), reporting a minAvailable floor breach")
        public Map<String, Object> flooredAlpha() {
            Map<String, Object> out = new LinkedHashMap<>();
            try {
                Map<String, Object> payload = flooredService.alphaFloored();
                out.put("floored_agent", payload.get("agent"));
            } catch (MeshServiceUnavailableException e) {
                // Typed floor breach: report the exception's own accounting so
                // the TC asserts the exact floor arithmetic, not just a message.
                out.put("floor_error", e.getClass().getSimpleName());
                out.put("floor_service", e.getService());
                out.put("floor_available", e.getMethodsAvailable());
                out.put("floor_total", e.getMethodsTotal());
                out.put("floor_min", e.getMinAvailable());
            }
            return out;
        }

        private void reportOne(Map<String, Object> out, String key, ViewCall call) {
            try {
                Map<String, Object> payload = call.invoke();
                out.put(key + "_agent", payload.get("agent"));
                out.put(key + "_cap", payload.get("cap"));
            } catch (RuntimeException e) {
                log.info("view method {} degraded: {}: {}", key,
                    e.getClass().getSimpleName(), e.getMessage());
                out.put(key + "_error", e.getClass().getSimpleName());
                out.put(key + "_error_message", e.getMessage());
            }
        }

        @FunctionalInterface
        private interface ViewCall {
            Map<String, Object> invoke();
        }
    }
}
