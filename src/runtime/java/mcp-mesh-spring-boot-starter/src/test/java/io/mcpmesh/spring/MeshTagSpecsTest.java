package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshA2ABeanPostProcessor;
import io.mcpmesh.spring.web.MeshA2ARegistry;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshRouteBeanPostProcessor;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Issue #1572: the documented {@code "python|typescript"} tag-level OR was sent
 * to the registry verbatim — a single required tag no provider carries, so the
 * dependency never resolved. The SDK now expands it into the nested-array wire
 * form Python and TypeScript send ({@code ["addition", ["python", "typescript"]]}),
 * which the registry matcher reads as "addition AND (python OR typescript)".
 */
@DisplayName("#1572: a|b tag alternatives serialize to the nested-array wire form")
class MeshTagSpecsTest {

    private static final String WIRE = "[\"addition\",[\"python\",\"typescript\"]]";

    @BeforeEach
    void setUp() {
        MeshSettleState.resetForTests(0.0);
    }

    @AfterEach
    void tearDown() {
        MeshSettleState.resetForTests();
    }

    // ── expansion rules ────────────────────────────────────────────────

    @Test
    @DisplayName("plain tags pass through; a|b becomes an inner OR group")
    void expandsAlternatives() {
        assertEquals(List.of("api", "+fast", "-deprecated"),
            MeshTagSpecs.toWire(new String[]{"api", "+fast", "-deprecated"}));
        assertEquals(List.of("addition", List.of("python", "typescript")),
            MeshTagSpecs.toWire(new String[]{"addition", "python|typescript"}));
    }

    @Test
    @DisplayName("operators stay on each alternative; parentheses and whitespace are tolerated")
    void operatorsParensWhitespace() {
        assertEquals(List.of(List.of("+python", "typescript")),
            MeshTagSpecs.toWire(new String[]{"+python|typescript"}));
        assertEquals(List.of(List.of("python", "+typescript", "-legacy")),
            MeshTagSpecs.toWire(new String[]{"(python | +typescript | -legacy)"}));
        assertEquals(List.of(List.of("a", "b"), List.of("c", "d")),
            MeshTagSpecs.toWire(new String[]{"a|b", "c|d"}));
    }

    @Test
    @DisplayName("empty alternatives are dropped; one survivor degrades to a plain tag; none drops the group")
    void emptyAlternatives() {
        assertEquals(List.of("a"), MeshTagSpecs.toWire(new String[]{"a||"}));
        assertEquals(List.of("-a"), MeshTagSpecs.toWire(new String[]{"(-a|)"}));
        assertEquals(List.of("+a"), MeshTagSpecs.toWire(new String[]{"+a|"}),
            "a single surviving alternative is a plain tag, not a one-element group");
        assertEquals(List.of("x"), MeshTagSpecs.toWire(new String[]{"x", "|"}));
        assertEquals(List.of(), MeshTagSpecs.toWire((String[]) null));
    }

    @Test
    @DisplayName("an all-'-' group is still sent as written (and WARNed): it can never match")
    void allNegativeGroup() {
        assertEquals(List.of(List.of("-a", "-b")), MeshTagSpecs.toWire(new String[]{"-a|-b"}));
        assertEquals(List.of(List.of("python", "-legacy")), MeshTagSpecs.toWire(new String[]{"python|-legacy"}));
    }

    @Test
    @DisplayName("hasAlternatives")
    void hasAlternatives() {
        assertTrue(MeshTagSpecs.hasAlternatives(new String[]{"a", "b|c"}));
        assertFalse(MeshTagSpecs.hasAlternatives(new String[]{"a", "+b"}));
        assertFalse(MeshTagSpecs.hasAlternatives(null));
    }

    // ── every dependency serialization path ────────────────────────────

    static class ToolBean {
        @MeshTool(capability = "calc",
                  dependencies = @Selector(capability = "math", tags = {"addition", "python|typescript"}))
        public String calc(@Param("x") String x, McpMeshTool<String> math) {
            return x;
        }
    }

    @Test
    @DisplayName("@MeshTool dependency: tool spec and agent-level dependency spec")
    void meshToolDependency() throws Exception {
        MeshToolRegistry reg = new MeshToolRegistry();
        Method m = ToolBean.class.getMethod("calc", String.class, McpMeshTool.class);
        reg.registerTool(new ToolBean(), m, m.getAnnotation(MeshTool.class));

        AgentSpec.ToolSpec spec = reg.getToolSpecs().stream()
            .filter(s -> "calc".equals(s.getCapability())).findFirst().orElseThrow();
        assertEquals(WIRE, spec.getDependencies().get(0).getTags());
        assertEquals(WIRE, reg.getDependencySpecs().get(0).getTags());
    }

    @RestController
    public static class RouteBean {
        @GetMapping("/calc")
        @MeshRoute(dependencies = @MeshDependency(capability = "math", tags = {"addition", "python|typescript"}))
        public String calc(McpMeshTool<String> math) {
            return "";
        }
    }

    @Test
    @DisplayName("@MeshRoute dependency")
    void routeDependency() {
        MeshRouteRegistry reg = new MeshRouteRegistry();
        new MeshRouteBeanPostProcessor(reg).postProcessAfterInitialization(new RouteBean(), "route");
        assertEquals(WIRE, reg.getUniqueDependencySpecs().get(0).getTags());
    }

    public static class A2ABean {
        @MeshA2A(path = "/agents/calc", skillId = "calc", skillName = "Calc",
                 dependencies = @MeshDependency(capability = "math", tags = {"addition", "python|typescript"}))
        public Map<String, Object> calc(Map<String, Object> message, McpMeshTool<String> math) {
            return message;
        }
    }

    @Test
    @DisplayName("@MeshA2A dependency")
    void a2aDependency() {
        MeshA2ARegistry reg = new MeshA2ARegistry();
        new MeshA2ABeanPostProcessor(reg).postProcessAfterInitialization(new A2ABean(), "a2a");
        assertEquals(WIRE, reg.getUniqueDependencySpecs().get(0).getTags());
    }
}
