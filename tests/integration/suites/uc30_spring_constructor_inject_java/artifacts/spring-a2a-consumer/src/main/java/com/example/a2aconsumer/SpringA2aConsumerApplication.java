package com.example.a2aconsumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.SchemaMode;
import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.types.McpMeshTool;
import jakarta.validation.constraints.NotNull;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Component;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * uc30 fixture — Java Spring Boot agent under test for issue #1088
 * (GRANULAR, single declaration source: @MeshA2A ONLY).
 *
 * <p>Issue #1088: a Spring {@code @Component}/{@code @Service} that does
 * CONSTRUCTOR injection of {@code @Qualifier("cap") McpMeshTool<T>} for a
 * capability DECLARED via {@code @MeshA2A(dependencies=...)}. Before the fix
 * the early-phase {@code BeanDefinitionRegistryPostProcessor} only registered
 * proxy beans for {@code @MeshDependsOn}-declared capabilities, so a
 * constructor that required {@code @Qualifier("farewell_service") McpMeshTool}
 * failed with {@code NoSuchBeanDefinitionException} and the Spring context
 * never refreshed — the agent never booted (never appears in /agents).
 *
 * <p>This agent isolates EXACTLY ONE declaration source — {@code @MeshA2A} —
 * with NO {@code @MeshRoute} anywhere. The companion
 * {@code spring-route-consumer} covers the {@code @MeshRoute} source.
 */
@MeshAgent(
    name = "spring-a2a-consumer",
    version = "1.0.0",
    description = "uc30 consumer proving #1088 constructor injection of a @MeshA2A-declared cap",
    port = 9202
)
@SpringBootApplication
public class SpringA2aConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(SpringA2aConsumerApplication.class);

    public static void main(String[] args) {
        log.info("Starting spring-a2a-consumer (uc30 #1088, @MeshA2A source)...");
        SpringApplication.run(SpringA2aConsumerApplication.class, args);
    }

    // ---- Typed response record for the provider capability ----

    /**
     * Typed shape returned by the Python {@code farewell_service} capability.
     *
     * <p>{@code @NotNull} on the component keeps the Java schema generator
     * (NULLABLE_FIELDS_BY_DEFAULT) from emitting a {@code "null"} branch, so the
     * SUBSET matcher matches the provider's non-nullable {@code message}. The
     * A2A path currently skips schema matching, so this is a no-op today, but it
     * keeps the fixture correct and robust if matching is later applied. Mirrors
     * {@code examples/schema/java/consumer/Employee}.
     */
    public record FarewellResponse(@NotNull String message) {}

    // ---- Declaration source: @MeshA2A declares farewell_service ----

    /**
     * The {@code @MeshA2A} method is the DECLARATION SOURCE for the
     * {@code farewell_service} capability. Carries the required A2A surface
     * metadata (path / skillId / skillName). Not invoked by the test.
     */
    @Component
    static class A2aDeclSurface {

        @MeshA2A(
            path = "/a2a-decl",
            skillId = "a2a-decl",
            skillName = "A2A Decl",
            description = "Declares the farewell_service dependency for #1088",
            dependencies = @MeshDependency(
                capability = "farewell_service",
                expectedType = FarewellResponse.class,
                schemaMode = SchemaMode.SUBSET))
        public Map<String, Object> a2aDecl(Map<String, Object> message) {
            return Map.of("ok", true);
        }
    }

    // ---- Consumer: CONSTRUCTOR injection of the @MeshA2A-declared cap ----

    /**
     * Issue #1088 core (A2A path): constructor injection of a capability
     * declared ONLY via {@code @MeshA2A}. If the early-phase registrar does not
     * register the {@code farewell_service} proxy bean, this constructor fails
     * to autowire with {@code NoSuchBeanDefinitionException} and the whole
     * context refresh fails — the agent never boots.
     */
    @Service
    static class A2aForwarder {

        private final McpMeshTool<FarewellResponse> farewell;

        A2aForwarder(@Qualifier("farewell_service") McpMeshTool<FarewellResponse> farewell) {
            this.farewell = farewell;
        }

        @MeshTool(
            capability = "forward_via_a2a",
            description = "Call the @MeshA2A-declared, constructor-injected farewell proxy",
            tags = {"forward"})
        public Map<String, Object> forwardViaA2a(
                @Param(value = "name", description = "Name to bid farewell") String name) {
            // Typed call proves the expectedType flowed through.
            FarewellResponse r = farewell.call(Map.of("name", name));
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("forwarded", r.message());
            return out;
        }
    }
}
