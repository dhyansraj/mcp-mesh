package com.example.routereq;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * uc34 fixture — Java route perimeter for issue #1249.
 *
 * <p>The {@code /check} route declares {@code @MeshDependency(capability =
 * "base-cap", required = true)}. Contract under test (mirrors the Python
 * {@code @mesh.route} wrapper):
 *
 * <ul>
 *   <li>Provider up: the framework injects the {@code McpMeshTool} proxy and
 *       the handler answers 200 with the provider payload.</li>
 *   <li>Provider down: {@code MeshRouteHandlerInterceptor} answers HTTP 503
 *       with body {@code {"error":"dependency_unavailable","capability":"base-cap"}}
 *       BEFORE user code runs. The handler body calls the proxy unguarded on
 *       purpose — reaching it with a null proxy would blow up as a 500, so a
 *       clean 503 is proof the perimeter fired, not a handler fallback.</li>
 * </ul>
 */
@MeshAgent(
    name = "java-route-consumer",
    version = "1.0.0",
    description = "uc34 consumer proving the #1249 required-route perimeter (503 before user code)",
    port = 9201
)
@SpringBootApplication
public class JavaRouteConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(JavaRouteConsumerApplication.class);

    public static void main(String[] args) {
        log.info("Starting java-route-consumer (uc34 #1249 route perimeter)...");
        SpringApplication.run(JavaRouteConsumerApplication.class, args);
    }

    /**
     * The route under test. Parameter name {@code baseCap} matches the
     * capability {@code base-cap} via the default hyphen-to-camelCase mapping.
     */
    @RestController
    static class CheckController {

        @GetMapping("/check")
        @MeshRoute(dependencies = @MeshDependency(capability = "base-cap", required = true))
        public ResponseEntity<Map<String, Object>> check(McpMeshTool<Map<String, Object>> baseCap) {
            // Deliberately unguarded: the #1249 perimeter must 503 before we
            // ever get here with an unavailable proxy.
            Map<String, Object> result = baseCap.call(Map.of());
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("status", "ok");
            out.put("base", result);
            return ResponseEntity.ok(out);
        }
    }

    /**
     * Liveness anchor: a trivial tool capability so the agent registers on the
     * ordinary tool-agent path and shows up in {@code meshctl list} under its
     * declared name for the registration wait. Not asserted on.
     */
    @Service
    static class PingService {

        @MeshTool(capability = "java-route-ping", description = "uc34 liveness ping")
        public Map<String, Object> ping() {
            return Map.of("ok", true);
        }
    }
}
