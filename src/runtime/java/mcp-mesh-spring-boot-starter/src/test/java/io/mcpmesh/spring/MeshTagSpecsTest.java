package io.mcpmesh.spring;

import io.mcpmesh.MeshService;
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
import tools.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
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
    @DisplayName("well-formed groups: plain, preferred, parenthesized, padded")
    void wellFormedGroups() {
        assertEquals(List.of(List.of("a", "b")), MeshTagSpecs.toWire(new String[]{"a|b"}));
        assertEquals(List.of(List.of("+a", "b")), MeshTagSpecs.toWire(new String[]{"+a|b"}));
        assertEquals(List.of(List.of("a", "b")), MeshTagSpecs.toWire(new String[]{"(a|b)"}));
        assertEquals(List.of(List.of("a", "b")), MeshTagSpecs.toWire(new String[]{" a | b "}));
        assertEquals(List.of(), MeshTagSpecs.toWire((String[]) null));
        assertDoesNotThrow(() -> MeshTagSpecs.validate(
            new String[]{"a|b", "+a|b", "(a|b)", " a | b ", "plain", "-x"}, "x"));
        assertDoesNotThrow(() -> MeshTagSpecs.validate(null, "x"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"|", "a|", "|a", "a||b", "( | )", "+a|", "-a|", "(-a|)", "a||"})
    @DisplayName("an empty alternative is rejected, never dropped or collapsed")
    void emptyAlternativeRejected(String tag) {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
            () -> MeshTagSpecs.toWire(new String[]{"x", tag}));
        assertTrue(ex.getMessage().contains("'" + tag + "'"), ex.getMessage());
        assertTrue(ex.getMessage().contains("each '|' must separate two non-empty alternatives"),
            ex.getMessage());

        IllegalArgumentException named = assertThrows(IllegalArgumentException.class,
            () -> MeshTagSpecs.validate(new String[]{tag}, "@Where 'Here#there'"));
        assertTrue(named.getMessage().contains("@Where 'Here#there'"), named.getMessage());
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

    // ── a malformed group fails in the annotation scanner (context refresh) ──

    private static void assertNamesElement(IllegalArgumentException ex, String... parts) {
        for (String part : parts) {
            assertTrue(ex.getMessage().contains(part), "missing '" + part + "' in: " + ex.getMessage());
        }
    }

    static class BadToolBean {
        @MeshTool(capability = "calc", dependencies = @Selector(capability = "math", tags = {"python|"}))
        public String calc(@Param("x") String x, McpMeshTool<String> math) {
            return x;
        }
    }

    @Test
    @DisplayName("@MeshTool: rejected in the bean post-processor")
    void meshToolRejectedAtScan() {
        MeshToolRegistry reg = new MeshToolRegistry();
        MeshToolBeanPostProcessor bpp = new MeshToolBeanPostProcessor(reg,
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory()), JsonMapper.builder().build());
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
            () -> bpp.postProcessAfterInitialization(new BadToolBean(), "bad"));
        assertNamesElement(ex, "@MeshTool", BadToolBean.class.getName() + "#calc", "math", "'python|'");
        assertTrue(reg.getToolSpecs().isEmpty(), "nothing must be registered");
    }

    @RestController
    public static class BadRouteBean {
        @GetMapping("/calc")
        @MeshRoute(dependencies = @MeshDependency(capability = "math", tags = {"|python"}))
        public String calc(McpMeshTool<String> math) {
            return "";
        }
    }

    @Test
    @DisplayName("@MeshRoute: rejected in the bean post-processor")
    void routeRejectedAtScan() {
        MeshRouteRegistry reg = new MeshRouteRegistry();
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
            () -> new MeshRouteBeanPostProcessor(reg).postProcessAfterInitialization(new BadRouteBean(), "r"));
        assertNamesElement(ex, "@MeshRoute", BadRouteBean.class.getName() + "#calc", "math");
    }

    public static class BadA2ABean {
        @MeshA2A(path = "/agents/calc", skillId = "calc", skillName = "Calc",
                 dependencies = @MeshDependency(capability = "math", tags = {"a||b"}))
        public Map<String, Object> calc(Map<String, Object> message, McpMeshTool<String> math) {
            return message;
        }
    }

    @Test
    @DisplayName("@MeshA2A: rejected in the bean post-processor")
    void a2aRejectedAtScan() {
        MeshA2ARegistry reg = new MeshA2ARegistry();
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
            () -> new MeshA2ABeanPostProcessor(reg).postProcessAfterInitialization(new BadA2ABean(), "a"));
        assertNamesElement(ex, "@MeshA2A", BadA2ABean.class.getName() + "#calc", "math");
    }

    @MeshService
    public interface BadView {
        @Selector(capability = "media.caption", tags = {"( | )"})
        String caption(@Param("id") String id);
    }

    @Test
    @DisplayName("@MeshService: rejected while analyzing the view")
    void meshServiceRejectedAtScan() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
            () -> MeshServiceRegistrar.analyze(BadView.class));
        assertNamesElement(ex, "@MeshService", BadView.class.getName(), "caption");
    }
}
