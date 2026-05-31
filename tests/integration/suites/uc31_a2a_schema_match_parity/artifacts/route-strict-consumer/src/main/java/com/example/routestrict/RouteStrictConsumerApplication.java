package com.example.routestrict;

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
 * uc31 fixture — CONTROL for issue #1089 (@MeshRoute source).
 *
 * <p>Declares the {@code parity_cap} dependency via {@code @MeshRoute} with
 * {@code expectedType=StrictResponse.class} (a record with a required
 * {@code value: String}) and {@code schemaMode=SchemaMode.SUBSET}. The
 * uc31 {@code parity-provider} deliberately publishes an INCOMPATIBLE output
 * schema (a field {@code other}, no {@code value}), so the registry's SUBSET
 * schema stage computes a {@code missing_field} and EVICTS the provider — this
 * is the long-standing {@code @MeshRoute} behavior the #1089 fix brings to
 * {@code @MeshA2A}.
 *
 * <p>Because of #1088, the early-phase registrar still registers the qualified
 * {@code McpMeshTool} proxy bean from the {@code @MeshRoute} declaration, so the
 * Spring context refreshes and the agent boots healthy (no
 * {@code NoSuchBeanDefinitionException}). The dependency simply never resolves
 * (DEPS 0/1) because the only candidate provider is schema-incompatible, and a
 * call to {@code forward_route_strict} therefore returns "unavailable".
 *
 * <p>GRANULAR: this agent has NO {@code @MeshA2A} anywhere. The companion
 * {@code a2a-strict-consumer} covers the {@code @MeshA2A} source (the payoff).
 */
@MeshAgent(
    name = "route-strict-consumer",
    version = "1.0.0",
    description = "uc31 CONTROL: @MeshRoute consumer whose incompatible provider is evicted (#1089)",
    port = 9201
)
@SpringBootApplication
public class RouteStrictConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(RouteStrictConsumerApplication.class);

    public static void main(String[] args) {
        log.info("Starting route-strict-consumer (uc31 #1089, @MeshRoute source, CONTROL)...");
        SpringApplication.run(RouteStrictConsumerApplication.class, args);
    }

    // ---- Strict expected type: requires a `value` the provider does NOT publish ----

    /**
     * Strict shape the consumer EXPECTS from {@code parity_cap}.
     *
     * <p>{@code @NotNull} keeps the Java schema generator from emitting a
     * {@code "null"} branch, so the SUBSET constraint requires a non-nullable
     * {@code value: string}. The uc31 provider publishes {@code other} only and
     * NO {@code value}, so SUBSET matching yields {@code missing_field} and the
     * registry evicts the provider. Mirrors
     * {@code examples/schema/java/consumer/Employee}.
     */
    public record StrictResponse(@NotNull String value) {}

    // ---- Declaration source: @MeshRoute declares parity_cap ----

    /**
     * The {@code @MeshRoute} method is the DECLARATION SOURCE for the
     * {@code parity_cap} dependency. Not invoked by the test — its only job is
     * to declare the dependency with the strict expectedType so the registry's
     * schema stage evicts the incompatible provider.
     */
    @RestController
    static class RouteStrictController {

        @PostMapping("/route-strict")
        @MeshRoute(dependencies = @MeshDependency(
            capability = "parity_cap",
            expectedType = StrictResponse.class,
            schemaMode = SchemaMode.SUBSET))
        public String routeStrict() {
            return "ok";
        }
    }

    // ---- Consumer: CONSTRUCTOR injection of the @MeshRoute-declared cap ----

    /**
     * Constructor-injects the qualified {@code parity_cap} proxy. The proxy
     * bean exists (#1088), but the dependency never resolves because the only
     * provider is schema-incompatible — so {@code parity.call(...)} surfaces an
     * "unavailable" error rather than a value.
     */
    @Service
    static class RouteStrictForwarder {

        private final McpMeshTool<StrictResponse> parity;

        RouteStrictForwarder(@Qualifier("parity_cap") McpMeshTool<StrictResponse> parity) {
            this.parity = parity;
        }

        @MeshTool(
            capability = "forward_route_strict",
            description = "Call the @MeshRoute-declared parity_cap proxy (expected: unavailable, provider evicted)",
            tags = {"forward"})
        public Map<String, Object> forwardRouteStrict(
                @Param(value = "name", description = "Name to pass to parity_cap") String name) {
            StrictResponse r = parity.call(Map.of("name", name));
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("forwarded", r.value());
            return out;
        }
    }
}
