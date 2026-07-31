package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshRouteBeanPostProcessor;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.annotation.AliasFor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;

/**
 * The mapping scan must register exactly the routes the developer wrote —
 * issue #1443.
 *
 * <p>{@code getMappingInfo} checked the five HTTP-verb shortcuts and then
 * <b>unconditionally</b> also looked up {@code @RequestMapping}. Every shortcut
 * is meta-annotated {@code @RequestMapping}, so that last lookup matched for
 * every handler — and {@code AnnotationUtils.findAnnotation} does not apply
 * {@code @AliasFor}, so it surfaced the meta-annotation's own empty
 * {@code value()}/{@code path()} and no {@code method()}. The empty-path and
 * default-GET fallbacks then registered a phantom {@code GET <base path>} per
 * handler: three handlers produced four routes, and the phantom's {@code ""}
 * slot was overwritten once per handler, so {@code getByRoute("GET", "/")}
 * answered with an arbitrary winner that could change between JVM restarts of
 * the same artifact.
 *
 * <p>Placed in {@code io.mcpmesh.spring} alongside
 * {@link MeshRouteOverloadedHandlerTest} so {@code MeshSettleState}'s
 * package-private test reset is visible.
 */
@DisplayName("@MeshRoute: the mapping scan registers exactly the declared routes")
class MeshRouteMappingScanTest {

    private MeshRouteRegistry registry;

    @BeforeEach
    void setUp() {
        MeshSettleState.resetForTests(0.0);
        registry = new MeshRouteRegistry();
    }

    private void scan(Object controller) {
        new MeshRouteBeanPostProcessor(registry)
            .postProcessAfterInitialization(controller, controller.getClass().getSimpleName());
    }

    // ─────────────────────────────────────────────────────────────────
    // A1 — the phantom
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("@GetMapping(\"/x\") produces exactly ONE mapping")
    void verbShortcutProducesExactlyOneMapping() {
        scan(new SingleGetController());

        assertEquals(1, registry.getRouteCount(),
            "one @GetMapping handler is one route — the extra one is the phantom at the "
                + "controller base path from the unconditional @RequestMapping fall-through");
        assertNotNull(registry.getByRoute("GET", "/x"));
        assertNull(registry.getByRoute("GET", "/"),
            "nothing was mapped at the controller base path");
    }

    @Test
    @DisplayName("N distinctly-mapped handlers under a base path register exactly N routes")
    void basePathControllerRegistersOneRoutePerHandler() {
        // The measurement in issue #1443: three handlers produced four routes,
        // the fourth being GET /api with an arbitrary winner.
        scan(new BasePathController());

        assertEquals(3, registry.getRouteCount());
        assertNotNull(registry.getByRoute("GET", "/api/a"));
        assertNotNull(registry.getByRoute("GET", "/api/b"));
        assertNotNull(registry.getByRoute("GET", "/api/solo"));
        assertNull(registry.getByRoute("GET", "/api"),
            "no handler is mapped at the controller base path");
    }

    // ─────────────────────────────────────────────────────────────────
    // A2 — a DIRECT @RequestMapping still works, with @AliasFor applied
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("A direct @RequestMapping(path=..., method={GET, POST}) still yields BOTH")
    void directRequestMappingYieldsEveryDeclaredMethod() {
        scan(new DirectRequestMappingController());

        assertEquals(2, registry.getRouteCount());
        assertNotNull(registry.getByRoute("GET", "/y"));
        assertNotNull(registry.getByRoute("POST", "/y"));
        assertSame(registry.getByRoute("GET", "/y"), registry.getByRoute("POST", "/y"),
            "one handler, one metadata instance on both mappings");
        assertNull(registry.getByRoute("GET", "/"));
    }

    @Test
    @DisplayName("A composed mapping annotation's @AliasFor override reaches the real path")
    void composedMappingAnnotationAliasIsHonoured() {
        // The @AliasFor case the old lookup could not see at all: a user-defined
        // annotation meta-annotated @RequestMapping, overriding `path` via
        // @AliasFor. AnnotationUtils.findAnnotation returns the meta-annotation
        // with its OWN empty defaults, so the handler landed at the base path.
        scan(new ComposedMappingController());

        assertEquals(1, registry.getRouteCount());
        assertNotNull(registry.getByRoute("GET", "/z"),
            "@AliasFor(annotation = RequestMapping.class, attribute = \"path\") must resolve "
                + "to /z, not degrade to the controller base path");
        assertNull(registry.getByRoute("GET", "/"));
    }

    @Test
    @DisplayName("@RequestMapping's own value/path @AliasFor is honoured (value= reaches the path)")
    void directRequestMappingValueAliasIsHonoured() {
        scan(new ValueAliasRequestMappingController());

        assertEquals(1, registry.getRouteCount());
        assertNotNull(registry.getByRoute("GET", "/zz"),
            "value= is an @AliasFor path= — it must not degrade to the base path");
    }

    @Test
    @DisplayName("A genuinely path-less @RequestMapping still maps at the controller base path")
    void pathlessRequestMappingMapsAtBasePath() {
        // The empty-path fallback is retained on purpose: now that it is only
        // reachable from a DIRECT @RequestMapping, an empty path means the
        // developer really did write @RequestMapping with no path, which Spring
        // MVC maps at the class-level base path.
        scan(new PathlessRequestMappingController());

        assertEquals(1, registry.getRouteCount());
        assertNotNull(registry.getByRoute("GET", "/root"));
    }

    // ─────────────────────────────────────────────────────────────────
    // A3 — two verb shortcuts on ONE method must still yield two mappings
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("@GetMapping + @PostMapping on one method yields TWO mappings, not one and not three")
    void twoVerbShortcutsOnOneMethodYieldTwoMappings() {
        // Load-bearing: this is why the five shortcut branches cannot collapse
        // into a single findMergedAnnotation(method, RequestMapping.class) —
        // that returns ONE merged annotation and would drop a mapping. It is
        // also the one-metadata-registered-twice path the registry's handler
        // guard has to tolerate.
        scan(new MultiVerbController());

        assertEquals(2, registry.getRouteCount(),
            "GET /multi and POST /multi — no phantom, and neither verb dropped");
        assertSame(registry.getByRoute("GET", "/multi"), registry.getByRoute("POST", "/multi"));
        assertNull(registry.getByRoute("GET", "/"));
    }

    @Test
    @DisplayName("A verb shortcut AND a direct @RequestMapping on one method both count")
    void shortcutAndDirectRequestMappingBothContribute() {
        // Both annotations compile on one method, and the developer wrote both.
        // Suppressing the direct @RequestMapping whenever a shortcut matched
        // would drop POST /y — the same class of silent loss as collapsing the
        // five shortcut branches.
        scan(new ShortcutPlusDirectController());

        assertEquals(2, registry.getRouteCount());
        assertNotNull(registry.getByRoute("GET", "/x"), "the @GetMapping mapping");
        assertNotNull(registry.getByRoute("POST", "/y"), "the direct @RequestMapping mapping");
        assertNull(registry.getByRoute("GET", "/"),
            "and still no phantom at the controller base path");
    }

    // ─────────────────────────────────────────────────────────────────
    // The class-level base path has the same @AliasFor defect
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("A composed CLASS-level mapping annotation still yields the base path")
    void composedClassLevelAnnotationYieldsTheBasePath() {
        // One level up from the phantom: AnnotationUtils.findAnnotation on the
        // CLASS does not apply @AliasFor either, so a composed controller
        // annotation degraded the base path to "" and misplaced every route on
        // that controller — /api/a became /a.
        scan(new ComposedBasePathController());

        assertEquals(1, registry.getRouteCount());
        assertNotNull(registry.getByRoute("GET", "/api/a"),
            "the class-level @AliasFor override must resolve to /api");
        assertNull(registry.getByRoute("GET", "/a"),
            "the route must not be misplaced at the root");
    }

    // ─────────────────────────────────────────────────────────────────
    // Fixtures
    // ─────────────────────────────────────────────────────────────────

    @RestController
    @SuppressWarnings("unused")
    public static class SingleGetController {
        @GetMapping("/x")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String x(McpMeshTool one) {
            return "x";
        }
    }

    @RestController
    @RequestMapping("/api")
    @SuppressWarnings("unused")
    public static class BasePathController {
        @GetMapping("/a")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String a(McpMeshTool one) {
            return "a";
        }

        @GetMapping("/b")
        @MeshRoute(dependencies = @MeshDependency(capability = "beta"))
        public String b(McpMeshTool one) {
            return "b";
        }

        @GetMapping("/solo")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String solo(McpMeshTool one) {
            return "solo";
        }
    }

    @RestController
    @SuppressWarnings("unused")
    public static class DirectRequestMappingController {
        @RequestMapping(path = "/y", method = {RequestMethod.GET, RequestMethod.POST})
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String y(McpMeshTool one) {
            return "y";
        }
    }

    @RestController
    @SuppressWarnings("unused")
    public static class ValueAliasRequestMappingController {
        @RequestMapping(value = "/zz", method = RequestMethod.GET)
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String zz(McpMeshTool one) {
            return "zz";
        }
    }

    /** A user-defined composed mapping annotation with an @AliasFor override. */
    @Target(ElementType.METHOD)
    @Retention(RetentionPolicy.RUNTIME)
    @RequestMapping(method = RequestMethod.GET)
    public @interface AuditedGet {
        @AliasFor(annotation = RequestMapping.class, attribute = "path")
        String[] value() default {};
    }

    @RestController
    @SuppressWarnings("unused")
    public static class ComposedMappingController {
        @AuditedGet("/z")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String z(McpMeshTool one) {
            return "z";
        }
    }

    @RestController
    @RequestMapping("/root")
    @SuppressWarnings("unused")
    public static class PathlessRequestMappingController {
        @RequestMapping
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String root(McpMeshTool one) {
            return "root";
        }
    }

    @RestController
    @SuppressWarnings("unused")
    public static class ShortcutPlusDirectController {
        @GetMapping("/x")
        @RequestMapping(path = "/y", method = RequestMethod.POST)
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String both(McpMeshTool one) {
            return "both";
        }
    }

    /** A user-defined composed CONTROLLER annotation with an @AliasFor override. */
    @Target(ElementType.TYPE)
    @Retention(RetentionPolicy.RUNTIME)
    @RestController
    @RequestMapping
    public @interface ApiController {
        @AliasFor(annotation = RequestMapping.class, attribute = "path")
        String[] value() default {};
    }

    @ApiController("/api")
    @SuppressWarnings("unused")
    public static class ComposedBasePathController {
        @GetMapping("/a")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String a(McpMeshTool one) {
            return "a";
        }
    }

    @RestController
    @SuppressWarnings("unused")
    public static class MultiVerbController {
        @GetMapping("/multi")
        @PostMapping("/multi")
        @MeshRoute(dependencies = @MeshDependency(capability = "alpha"))
        public String both(McpMeshTool one) {
            return "multi";
        }
    }
}
