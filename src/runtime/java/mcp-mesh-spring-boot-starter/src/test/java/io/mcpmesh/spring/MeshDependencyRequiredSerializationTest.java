package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.SchemaMode;
import io.mcpmesh.spring.web.MeshA2ARegistry;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Method;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1249: verifies the per-dependency {@code required} flag flows from the
 * declaration annotations ({@link Selector} on {@code @MeshTool},
 * {@link MeshDependency} on {@code @MeshRoute}) into the registry metadata AND
 * into the {@link AgentSpec.DependencySpec} spec JSON handed to the Rust core.
 *
 * <p>Mirrors Python's serialization contract: {@code "required": true} is
 * present in the dependency entry when opted in, and OMITTED entirely (not
 * {@code false}) when default — byte-identical to pre-#1249 payloads so
 * existing agents are unaffected. The Rust core's
 * {@code #[serde(default, skip_serializing_if = ...)]} on {@code required}
 * accepts both shapes.
 */
class MeshDependencyRequiredSerializationTest {

    // The same mapper MeshHandle uses to serialize the AgentSpec for the FFI.
    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    // ---- @MeshTool / @Selector producer path ----------------------------------

    static class ToolBean {
        @MeshTool(capability = "needs_deps", dependencies = {
            @Selector(capability = "req_cap", required = true),
            @Selector(capability = "opt_cap")
        })
        public String withDeps(
            @Param("x") String x,
            io.mcpmesh.types.McpMeshTool reqCap,
            io.mcpmesh.types.McpMeshTool optCap) {
            return x;
        }
    }

    private static Method method(Class<?> c, String name) {
        for (Method m : c.getDeclaredMethods()) {
            if (m.getName().equals(name)) return m;
        }
        throw new AssertionError(name);
    }

    @Test
    void tool_requiredFlagFlowsIntoDependencyInfo() {
        MeshToolRegistry reg = new MeshToolRegistry();
        Method m = method(ToolBean.class, "withDeps");
        reg.registerTool(new ToolBean(), m, m.getAnnotation(MeshTool.class));

        MeshToolRegistry.ToolMetadata meta = reg.getTool("needs_deps");
        assertNotNull(meta);
        MeshToolRegistry.DependencyInfo req = meta.dependencies().stream()
            .filter(d -> d.capability().equals("req_cap")).findFirst().orElseThrow();
        MeshToolRegistry.DependencyInfo opt = meta.dependencies().stream()
            .filter(d -> d.capability().equals("opt_cap")).findFirst().orElseThrow();
        assertTrue(req.required(), "req_cap must carry required=true from @Selector");
        assertFalse(opt.required(), "opt_cap defaults to required=false");
    }

    @Test
    void tool_specJson_emitsRequiredTrueOnlyForRequiredDep() throws Exception {
        MeshToolRegistry reg = new MeshToolRegistry();
        Method m = method(ToolBean.class, "withDeps");
        reg.registerTool(new ToolBean(), m, m.getAnnotation(MeshTool.class));

        AgentSpec.ToolSpec toolSpec = reg.getToolSpecs().stream()
            .filter(s -> "needs_deps".equals(s.getCapability())).findFirst().orElseThrow();

        AgentSpec.DependencySpec reqDep = toolSpec.getDependencies().stream()
            .filter(d -> "req_cap".equals(d.getCapability())).findFirst().orElseThrow();
        AgentSpec.DependencySpec optDep = toolSpec.getDependencies().stream()
            .filter(d -> "opt_cap".equals(d.getCapability())).findFirst().orElseThrow();

        assertTrue(reqDep.isRequired());
        assertFalse(optDep.isRequired());

        // Serialize each dependency entry through the FFI mapper.
        String reqJson = MAPPER.writeValueAsString(reqDep);
        String optJson = MAPPER.writeValueAsString(optDep);

        assertTrue(reqJson.contains("\"required\":true"),
            "required dep JSON must contain \"required\":true, got: " + reqJson);
        assertFalse(optJson.contains("required"),
            "optional dep JSON must OMIT the required field entirely, got: " + optJson);
    }

    // ---- @MeshRoute / @MeshDependency perimeter path --------------------------

    static class RouteBean {
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "route_req", required = true),
            @MeshDependency(capability = "route_opt")
        })
        public String handler() {
            return "ok";
        }
    }

    @Test
    void route_requiredFlagFlowsIntoDependencySpec() {
        Method m = method(RouteBean.class, "handler");
        List<MeshRouteRegistry.DependencySpec> specs =
            MeshRouteRegistry.DependencySpec.fromAnnotation(m.getAnnotation(MeshRoute.class));

        MeshRouteRegistry.DependencySpec req = specs.stream()
            .filter(d -> d.getCapability().equals("route_req")).findFirst().orElseThrow();
        MeshRouteRegistry.DependencySpec opt = specs.stream()
            .filter(d -> d.getCapability().equals("route_opt")).findFirst().orElseThrow();
        assertTrue(req.isRequired(), "route_req must carry required=true from @MeshDependency");
        assertFalse(opt.isRequired(), "route_opt defaults to required=false");
    }

    @Test
    void route_uniqueSpecJson_emitsRequiredTrueOnlyForRequiredDep() throws Exception {
        Method m = method(RouteBean.class, "handler");
        MeshRouteRegistry registry = new MeshRouteRegistry();
        MeshRouteRegistry.RouteMetadata metadata = new MeshRouteRegistry.RouteMetadata(
            RouteBean.class.getName() + ".handler",
            MeshRouteRegistry.DependencySpec.fromAnnotation(m.getAnnotation(MeshRoute.class)),
            "test route",
            true);
        registry.register("POST", "/test", metadata);

        List<AgentSpec.DependencySpec> specs = registry.getUniqueDependencySpecs();
        AgentSpec.DependencySpec reqDep = specs.stream()
            .filter(d -> "route_req".equals(d.getCapability())).findFirst().orElseThrow();
        AgentSpec.DependencySpec optDep = specs.stream()
            .filter(d -> "route_opt".equals(d.getCapability())).findFirst().orElseThrow();

        assertTrue(reqDep.isRequired());
        assertFalse(optDep.isRequired());

        assertTrue(MAPPER.writeValueAsString(reqDep).contains("\"required\":true"),
            "required route dep JSON must contain \"required\":true");
        assertFalse(MAPPER.writeValueAsString(optDep).contains("required"),
            "optional route dep JSON must OMIT the required field entirely");
    }

    // ---- required-wins on dedupe merge (route + A2A registries) ---------------

    private static MeshRouteRegistry.DependencySpec routeDep(String cap, boolean required) {
        return new MeshRouteRegistry.DependencySpec(
            cap, new String[0], "", cap, null, SchemaMode.NONE, required);
    }

    private void assertRouteMergeYieldsRequired(
            List<MeshRouteRegistry.DependencySpec> deps) {
        MeshRouteRegistry registry = new MeshRouteRegistry();
        registry.register("POST", "/merge",
            new MeshRouteRegistry.RouteMetadata(
                RouteBean.class.getName() + ".handler", deps, "merge", true));

        List<AgentSpec.DependencySpec> specs = registry.getUniqueDependencySpecs();
        List<AgentSpec.DependencySpec> shared = specs.stream()
            .filter(d -> "shared_cap".equals(d.getCapability())).toList();
        assertEquals(1, shared.size(), "capability must be deduped to a single spec");
        assertTrue(shared.get(0).isRequired(),
            "required must WIN on merge regardless of declaration order");
    }

    @Test
    void route_requiredWinsMerge_requiredDeclaredFirst() {
        // Deterministic order via a single route's ordered dependency list.
        assertRouteMergeYieldsRequired(List.of(
            routeDep("shared_cap", true), routeDep("shared_cap", false)));
    }

    @Test
    void route_requiredWinsMerge_optionalDeclaredFirst() {
        assertRouteMergeYieldsRequired(List.of(
            routeDep("shared_cap", false), routeDep("shared_cap", true)));
    }

    private void assertA2aMergeYieldsRequired(
            List<MeshRouteRegistry.DependencySpec> deps) {
        MeshA2ARegistry registry = new MeshA2ARegistry();
        registry.register(new MeshA2ARegistry.SurfaceMetadata(
            "/a2a", "skill", "Skill", "", List.of(), deps, "", "Bean.m", new Object(), null));

        List<AgentSpec.DependencySpec> specs = registry.getUniqueDependencySpecs();
        List<AgentSpec.DependencySpec> shared = specs.stream()
            .filter(d -> "shared_cap".equals(d.getCapability())).toList();
        assertEquals(1, shared.size(), "capability must be deduped to a single spec");
        assertTrue(shared.get(0).isRequired(),
            "required must WIN on merge regardless of declaration order");
    }

    @Test
    void a2a_requiredFlowsAndWinsMerge_requiredFirst() {
        assertA2aMergeYieldsRequired(List.of(
            routeDep("shared_cap", true), routeDep("shared_cap", false)));
    }

    @Test
    void a2a_requiredFlowsAndWinsMerge_optionalFirst() {
        assertA2aMergeYieldsRequired(List.of(
            routeDep("shared_cap", false), routeDep("shared_cap", true)));
    }

    @Test
    void a2a_singleRequiredDep_emitsRequiredTrueInJson() throws Exception {
        MeshA2ARegistry registry = new MeshA2ARegistry();
        registry.register(new MeshA2ARegistry.SurfaceMetadata(
            "/a2a", "skill", "Skill", "", List.of(),
            List.of(routeDep("a2a_req", true), routeDep("a2a_opt", false)),
            "", "Bean.m", new Object(), null));

        List<AgentSpec.DependencySpec> specs = registry.getUniqueDependencySpecs();
        AgentSpec.DependencySpec req = specs.stream()
            .filter(d -> "a2a_req".equals(d.getCapability())).findFirst().orElseThrow();
        AgentSpec.DependencySpec opt = specs.stream()
            .filter(d -> "a2a_opt".equals(d.getCapability())).findFirst().orElseThrow();
        assertTrue(MAPPER.writeValueAsString(req).contains("\"required\":true"));
        assertFalse(MAPPER.writeValueAsString(opt).contains("required"));
    }

    @Test
    void dependencySpec_defaultsToRequiredFalse_andOmitsFromJson() throws Exception {
        // Guards the byte-identical-payload invariant for all existing callers
        // that never touch `required`.
        AgentSpec.DependencySpec dep = new AgentSpec.DependencySpec("plain_cap");
        assertFalse(dep.isRequired());
        assertFalse(MAPPER.writeValueAsString(dep).contains("required"),
            "a default DependencySpec must serialize without the required field");
    }
}
