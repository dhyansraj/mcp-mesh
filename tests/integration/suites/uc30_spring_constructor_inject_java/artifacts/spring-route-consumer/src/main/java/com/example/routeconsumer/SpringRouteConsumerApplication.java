package com.example.routeconsumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.SchemaMode;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.types.McpMeshTool;
import jakarta.validation.constraints.NotNull;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * uc30 fixture — Java Spring Boot agent under test for issue #1088
 * (GRANULAR, single declaration source: @MeshRoute ONLY).
 *
 * <p>Issue #1088: a Spring {@code @Component}/{@code @Service} that does
 * CONSTRUCTOR injection of {@code @Qualifier("cap") McpMeshTool<T>} for a
 * capability DECLARED via {@code @MeshRoute(dependencies=...)}. Before the fix
 * the early-phase {@code BeanDefinitionRegistryPostProcessor} only registered
 * proxy beans for {@code @MeshDependsOn}-declared capabilities, so a
 * constructor that required {@code @Qualifier("greeting_service") McpMeshTool}
 * failed with {@code NoSuchBeanDefinitionException} and the Spring context
 * never refreshed — the agent never booted (never appears in /agents).
 *
 * <p>This agent isolates EXACTLY ONE declaration source — {@code @MeshRoute} —
 * with NO {@code @MeshA2A} anywhere, so its {@code agent_type} stays a plain
 * tool agent and the registry resolves the route-declared dependency. The
 * companion {@code spring-a2a-consumer} covers the {@code @MeshA2A} source.
 */
@MeshAgent(
    name = "spring-route-consumer",
    version = "1.0.0",
    description = "uc30 consumer proving #1088 constructor injection of a @MeshRoute-declared cap",
    port = 9201
)
@SpringBootApplication
public class SpringRouteConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(SpringRouteConsumerApplication.class);

    public static void main(String[] args) {
        log.info("Starting spring-route-consumer (uc30 #1088, @MeshRoute source)...");
        SpringApplication.run(SpringRouteConsumerApplication.class, args);
    }

    // ---- Typed response record for the provider capability ----

    /**
     * Typed shape returned by the Python {@code greeting_service} capability.
     *
     * <p>{@code @NotNull} on the component is required so the Java schema
     * generator (NULLABLE_FIELDS_BY_DEFAULT) emits {@code type: "string"} rather
     * than {@code type: ["string","null"]}. The provider publishes a
     * non-nullable {@code message}; without {@code @NotNull} the consumer's
     * extra {@code "null"} branch has no producer counterpart and the SUBSET
     * matcher evicts the provider (type_mismatch). Mirrors
     * {@code examples/schema/java/consumer/Employee}.
     */
    public record GreetingResponse(@NotNull String message) {}

    // ---- Declaration source: @MeshRoute declares greeting_service ----

    /**
     * The {@code @MeshRoute} method is the DECLARATION SOURCE for the
     * {@code greeting_service} capability. The route itself is not invoked by
     * the test — its only job is to declare the dependency so the early-phase
     * registrar registers the qualified {@code McpMeshTool} proxy bean.
     */
    @RestController
    static class RouteDeclController {

        @PostMapping("/route-decl")
        @MeshRoute(dependencies = @MeshDependency(
            capability = "greeting_service",
            expectedType = GreetingResponse.class,
            schemaMode = SchemaMode.SUBSET))
        public String routeDecl() {
            return "ok";
        }
    }

    // ---- Consumer: CONSTRUCTOR injection of the @MeshRoute-declared cap ----

    /**
     * Issue #1088 core: constructor injection of a capability declared ONLY
     * via {@code @MeshRoute}. If the early-phase registrar does not register
     * the {@code greeting_service} proxy bean, this constructor fails to
     * autowire with {@code NoSuchBeanDefinitionException} and the whole
     * context refresh fails — the agent never boots.
     */
    @Service
    static class RouteForwarder {

        private final McpMeshTool<GreetingResponse> greeting;

        RouteForwarder(@Qualifier("greeting_service") McpMeshTool<GreetingResponse> greeting) {
            this.greeting = greeting;
        }

        @MeshTool(
            capability = "forward_via_route",
            description = "Call the @MeshRoute-declared, constructor-injected greeting proxy",
            tags = {"forward"})
        public Map<String, Object> forwardViaRoute(
                @Param(value = "name", description = "Name to greet") String name) {
            // Typed call proves the expectedType flowed through.
            GreetingResponse r = greeting.call(Map.of("name", name));
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("forwarded", r.message());
            return out;
        }
    }
}
