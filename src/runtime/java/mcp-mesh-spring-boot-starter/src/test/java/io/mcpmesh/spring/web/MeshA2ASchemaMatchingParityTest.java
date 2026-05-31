package io.mcpmesh.spring.web;

import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshCoreBridge;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Issue #1089: {@code @MeshA2A}-declared mesh dependencies previously bypassed
 * the {@code expectedType}/{@code schemaMode} schema-matching that
 * {@code @MeshRoute} and {@code @MeshDependsOn} apply, so they shipped with an
 * empty {@code matchMode} and the registry's schema-compatibility stage (gated
 * on {@code matchMode != ""}) was skipped for them.
 *
 * <p>These tests pin {@link MeshA2ARegistry#getUniqueDependencySpecs()} to the
 * same schema-stamping behaviour as {@link MeshRouteRegistry#getUniqueDependencySpecs()}
 * — including a cross-source PARITY assertion that the two paths produce byte
 * identical {@code matchMode}/{@code expectedSchemaCanonical}/{@code expectedSchemaHash}
 * for an identical capability + expectedType + schemaMode.
 *
 * <p>No Spring context or running registry is required: the registries are
 * driven directly with hand-built metadata. The canonical-schema assertions
 * depend on the Rust core native normalizer; when it isn't available the schema
 * generation returns null and {@code matchMode} stays empty, so those tests
 * skip cleanly via {@link Assumptions} (same guard pattern as
 * {@code MeshSchemaSupportTest}).
 */
@DisplayName("Issue #1089 — @MeshA2A dependency schema-matching parity with @MeshRoute")
class MeshA2ASchemaMatchingParityTest {

    /** Typed payload with at least one field — drives expectedType schema generation. */
    public record SchemaPayload(String id, int weight) {}

    /**
     * Annotation-bearing fixture. We read the {@link MeshDependency} declarations
     * off these {@code @MeshA2A} surfaces via reflection and turn them into
     * {@link MeshRouteRegistry.DependencySpec} the same way the bean
     * post-processor does ({@link MeshRouteRegistry.DependencySpec#fromAnnotation}).
     */
    static class Fixtures {

        @MeshA2A(
            path = "/agents/typed",
            skillId = "typed-skill",
            skillName = "Typed Skill",
            dependencies = @MeshDependency(
                capability = "schema_cap",
                expectedType = SchemaPayload.class,
                schemaMode = io.mcpmesh.SchemaMode.SUBSET))
        public Object typedSurface(java.util.Map<String, Object> message) {
            return "ok";
        }

        @MeshA2A(
            path = "/agents/plain",
            skillId = "plain-skill",
            skillName = "Plain Skill",
            dependencies = @MeshDependency(capability = "plain_cap"))
        public Object plainSurface(java.util.Map<String, Object> message) {
            return "ok";
        }
    }

    private static boolean nativeNormalizerAvailable() {
        try {
            MeshCoreBridge.normalizeSchema(
                "{\"type\":\"object\",\"properties\":{\"id\":{\"type\":\"string\"}}}", "java");
            return true;
        } catch (UnsatisfiedLinkError e) {
            return false;
        }
    }

    /** Read the @MeshDependency declarations off a fixture method's @MeshA2A. */
    private static List<MeshRouteRegistry.DependencySpec> depsOf(String fixtureMethod) {
        try {
            Method m = Fixtures.class.getDeclaredMethod(fixtureMethod, java.util.Map.class);
            MeshA2A a2a = m.getAnnotation(MeshA2A.class);
            List<MeshRouteRegistry.DependencySpec> specs = new java.util.ArrayList<>();
            for (MeshDependency dep : a2a.dependencies()) {
                specs.add(MeshRouteRegistry.DependencySpec.fromAnnotation(dep));
            }
            return specs;
        } catch (NoSuchMethodException e) {
            throw new AssertionError("Fixture method not found: " + fixtureMethod, e);
        }
    }

    private static MeshA2ARegistry.SurfaceMetadata surfaceWithDeps(
            String path, String skillId, String fixtureMethod,
            List<MeshRouteRegistry.DependencySpec> deps) {
        Fixtures bean = new Fixtures();
        Method method;
        try {
            method = Fixtures.class.getDeclaredMethod(fixtureMethod, java.util.Map.class);
        } catch (NoSuchMethodException e) {
            throw new AssertionError("Fixture method not found: " + fixtureMethod, e);
        }
        return new MeshA2ARegistry.SurfaceMetadata(
            path, skillId, skillId, "", List.of(), deps, "",
            "Fixtures." + fixtureMethod, bean, method);
    }

    @Test
    @DisplayName("expectedType + schemaMode=SUBSET stamps matchMode + canonical schema + hash")
    void typedDependencyGetsSchemaMatchingFields() {
        Assumptions.assumeTrue(nativeNormalizerAvailable(),
            "Rust core native library not available — schema normalization is required for this assertion");

        MeshA2ARegistry registry = new MeshA2ARegistry();
        registry.register(surfaceWithDeps("/agents/typed", "typed-skill", "typedSurface", depsOf("typedSurface")));

        List<AgentSpec.DependencySpec> specs = registry.getUniqueDependencySpecs();
        assertThat(specs).hasSize(1);
        AgentSpec.DependencySpec dep = specs.get(0);

        assertThat(dep.getCapability()).isEqualTo("schema_cap");
        assertThat(dep.getMatchMode())
            .as("@MeshA2A dependency with expectedType+SUBSET must stamp matchMode")
            .isEqualTo("subset");
        assertThat(dep.getExpectedSchemaCanonical())
            .as("expectedSchemaCanonical must be populated")
            .isNotNull()
            .isNotEmpty();
        assertThat(dep.getExpectedSchemaHash())
            .as("expectedSchemaHash must be populated")
            .isNotNull()
            .isNotEmpty();
    }

    @Test
    @DisplayName("No expectedType + no schemaMode → backward-compatible no-op (empty matchMode)")
    void plainDependencyStaysBackwardCompatible() {
        MeshA2ARegistry registry = new MeshA2ARegistry();
        registry.register(surfaceWithDeps("/agents/plain", "plain-skill", "plainSurface", depsOf("plainSurface")));

        List<AgentSpec.DependencySpec> specs = registry.getUniqueDependencySpecs();
        assertThat(specs).hasSize(1);
        AgentSpec.DependencySpec dep = specs.get(0);

        assertThat(dep.getCapability()).isEqualTo("plain_cap");
        assertThat(dep.getMatchMode())
            .as("dependency without expectedType/schemaMode must leave matchMode empty/null")
            .satisfiesAnyOf(
                m -> assertThat(m).isNull(),
                m -> assertThat(m).isEmpty());
        assertThat(dep.getExpectedSchemaCanonical())
            .as("no expected schema when no expectedType is declared")
            .isNull();
        assertThat(dep.getExpectedSchemaHash())
            .as("no expected schema hash when no expectedType is declared")
            .isNull();
    }

    @Test
    @DisplayName("PARITY: @MeshA2A and @MeshRoute produce identical schema-matching fields")
    void a2aMatchesRouteForIdenticalDependency() {
        Assumptions.assumeTrue(nativeNormalizerAvailable(),
            "Rust core native library not available — schema normalization is required for this assertion");

        // A2A side: same capability + expectedType + schemaMode as the route below.
        MeshA2ARegistry a2aRegistry = new MeshA2ARegistry();
        a2aRegistry.register(surfaceWithDeps("/agents/typed", "typed-skill", "typedSurface", depsOf("typedSurface")));
        AgentSpec.DependencySpec a2aDep = a2aRegistry.getUniqueDependencySpecs().get(0);

        // Route side: build a RouteMetadata carrying the IDENTICAL dependency spec.
        MeshRouteRegistry routeRegistry = new MeshRouteRegistry();
        MeshRouteRegistry.RouteMetadata route = new MeshRouteRegistry.RouteMetadata(
            "Fixtures.typedSurface", depsOf("typedSurface"), "", true);
        routeRegistry.register("POST", "/route-typed", route);
        AgentSpec.DependencySpec routeDep = routeRegistry.getUniqueDependencySpecs().get(0);

        assertThat(a2aDep.getMatchMode())
            .as("matchMode must match the @MeshRoute path exactly")
            .isEqualTo(routeDep.getMatchMode());
        assertThat(a2aDep.getExpectedSchemaCanonical())
            .as("expectedSchemaCanonical must match the @MeshRoute path exactly")
            .isEqualTo(routeDep.getExpectedSchemaCanonical());
        assertThat(a2aDep.getExpectedSchemaHash())
            .as("expectedSchemaHash must match the @MeshRoute path exactly")
            .isEqualTo(routeDep.getExpectedSchemaHash());
    }
}
