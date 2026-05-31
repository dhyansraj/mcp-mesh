package com.example.a2astrict;

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
 * uc31 fixture — PAYOFF for issue #1089 (@MeshA2A source).
 *
 * <p>Declares the {@code parity_cap} dependency via {@code @MeshA2A} with
 * {@code expectedType=StrictResponse.class} (a record with a required
 * {@code value: String}) and {@code schemaMode=SchemaMode.SUBSET} — IDENTICAL
 * to the {@code @MeshRoute} control in {@code route-strict-consumer}.
 *
 * <p>BEFORE #1089: {@code MeshA2ARegistry.getUniqueDependencySpecs()} did NOT
 * stamp the schema-matching fields ({@code expectedSchemaCanonical},
 * {@code expectedSchemaHash}, {@code matchMode}) onto the A2A dependency, so the
 * registry's schema-compatibility stage SKIPPED it: the incompatible
 * {@code parity-provider} resolved anyway (DEPS 1/1) and a call would later hit
 * a runtime deserialization error (no {@code value} field).
 *
 * <p>AFTER #1089: {@code getUniqueDependencySpecs()} calls
 * {@code MeshRouteRegistry.applySchemaMatching(...)}, so the A2A dependency
 * ships {@code matchMode=subset} exactly like the route source. The registry's
 * schema stage now computes {@code missing_field} and EVICTS the incompatible
 * provider — DEPS 0/1 — and {@code forward_a2a_strict} returns "unavailable".
 * This is the parity the suite proves.
 *
 * <p>GRANULAR: this agent has NO {@code @MeshRoute} anywhere.
 */
@MeshAgent(
    name = "a2a-strict-consumer",
    version = "1.0.0",
    description = "uc31 PAYOFF: @MeshA2A consumer whose incompatible provider is evicted after #1089",
    port = 9202
)
@SpringBootApplication
public class A2aStrictConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(A2aStrictConsumerApplication.class);

    public static void main(String[] args) {
        log.info("Starting a2a-strict-consumer (uc31 #1089, @MeshA2A source, PAYOFF)...");
        SpringApplication.run(A2aStrictConsumerApplication.class, args);
    }

    // ---- Strict expected type: requires a `value` the provider does NOT publish ----

    /**
     * Strict shape the consumer EXPECTS from {@code parity_cap} — IDENTICAL to
     * the route control's {@code StrictResponse}.
     *
     * <p>{@code @NotNull} keeps the Java schema generator from emitting a
     * {@code "null"} branch, so the SUBSET constraint requires a non-nullable
     * {@code value: string}. The uc31 provider publishes {@code other} only and
     * NO {@code value}; after #1089 the A2A dependency carries the same
     * {@code matchMode=subset} the route source does, so SUBSET matching yields
     * {@code missing_field} and the registry evicts the provider. Mirrors
     * {@code examples/schema/java/consumer/Employee}.
     */
    public record StrictResponse(@NotNull String value) {}

    // ---- Declaration source: @MeshA2A declares parity_cap ----

    /**
     * The {@code @MeshA2A} method is the DECLARATION SOURCE for the
     * {@code parity_cap} dependency. Carries the required A2A surface metadata
     * (path / skillId / skillName). Not invoked by the test.
     */
    @Component
    static class A2aStrictSurface {

        @MeshA2A(
            path = "/a2a-strict",
            skillId = "a2a-strict",
            skillName = "A2A Strict",
            description = "Declares the parity_cap dependency for uc31 #1089",
            dependencies = @MeshDependency(
                capability = "parity_cap",
                expectedType = StrictResponse.class,
                schemaMode = SchemaMode.SUBSET))
        public Map<String, Object> a2aStrict(Map<String, Object> message) {
            return Map.of("ok", true);
        }
    }

    // ---- Consumer: CONSTRUCTOR injection of the @MeshA2A-declared cap ----

    /**
     * Constructor-injects the qualified {@code parity_cap} proxy declared via
     * {@code @MeshA2A}. The proxy bean exists (#1088), but after #1089 the
     * dependency never resolves because the only provider is schema-incompatible
     * — so {@code parity.call(...)} surfaces an "unavailable" error rather than a
     * value, mirroring the {@code @MeshRoute} control.
     */
    @Service
    static class A2aStrictForwarder {

        private final McpMeshTool<StrictResponse> parity;

        A2aStrictForwarder(@Qualifier("parity_cap") McpMeshTool<StrictResponse> parity) {
            this.parity = parity;
        }

        @MeshTool(
            capability = "forward_a2a_strict",
            description = "Call the @MeshA2A-declared parity_cap proxy (expected: unavailable, provider evicted after #1089)",
            tags = {"forward"})
        public Map<String, Object> forwardA2aStrict(
                @Param(value = "name", description = "Name to pass to parity_cap") String name) {
            StrictResponse r = parity.call(Map.of("name", name));
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("forwarded", r.value());
            return out;
        }
    }
}
