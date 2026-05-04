package com.example.streaming;

import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshSse;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.Map;

/**
 * Java SSE streaming gateway for cross-runtime tests (issue #854 Phase A).
 *
 * <p>Has no {@code @MeshAgent} annotation, so the framework auto-starts in
 * consumer-only mode (agent_type="api") — same pattern as the
 * {@code rest-api-consumer} example. The controller declares a mesh
 * dependency on {@code trip_planning} via {@code @MeshRoute /
 * @MeshDependency} and forwards the resulting {@code Flow.Publisher<String>}
 * to a Spring {@link SseEmitter} via {@link MeshSse#forward(SseEmitter, java.util.concurrent.Flow.Publisher)}.
 *
 * <p>Wire format mirrors the Python {@code mesh.route} SSE adapter and the
 * TypeScript {@code mesh.sseStream} helper: one {@code data: <chunk>\n\n}
 * frame per upstream chunk, terminated by {@code data: [DONE]\n\n}.
 */
@SpringBootApplication
public class Application {

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}

@RestController
class GatewayController {

    private static final Logger log = LoggerFactory.getLogger(GatewayController.class);

    // No custom /health — mcp-mesh-spring-boot-starter ships
    // io.mcpmesh.spring.MeshHealthController which auto-registers
    // GET /health returning {"status":"healthy"} when the runtime
    // is up. The test asserts that response shape directly, and
    // having both controllers map /health would yield Spring's
    // "Ambiguous mapping" error at startup.

    /**
     * SSE-framed forwarder for the {@code trip_planning} mesh capability.
     *
     * <p>The request body is passed through verbatim to the upstream
     * tool's {@code stream(args)} method, mirroring the TS gateway's
     * {@code trip_planning.stream(req.body)}.
     */
    // Parameter name MUST match the capability name (snake_case → snake_case)
    // so MeshInjectArgumentResolver resolves the dep by parameter name.
    // This mirrors the rest-api-consumer example exactly.
    @PostMapping("/plan")
    @MeshRoute(dependencies = @MeshDependency(capability = "trip_planning"))
    public SseEmitter plan(
            @RequestBody(required = false) Map<String, Object> body,
            McpMeshTool<String> trip_planning) {

        // 0L = no timeout — the producer controls when the stream ends.
        SseEmitter emitter = new SseEmitter(0L);

        if (trip_planning == null || !trip_planning.isAvailable()) {
            log.warn("trip_planning capability is unavailable");
            try {
                emitter.send(SseEmitter.event()
                        .name("error")
                        .data("{\"error\":\"trip_planning unavailable\"}"));
                emitter.complete();
            } catch (Exception e) {
                emitter.completeWithError(e);
            }
            return emitter;
        }

        Map<String, Object> args = (body != null) ? body : Map.of();
        log.info("Forwarding /plan to trip_planning with args={}", args);
        MeshSse.forward(emitter, trip_planning.stream(args));
        return emitter;
    }
}
