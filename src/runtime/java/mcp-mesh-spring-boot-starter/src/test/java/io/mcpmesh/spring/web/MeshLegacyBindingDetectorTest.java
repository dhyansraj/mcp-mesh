package io.mcpmesh.spring.web;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import io.mcpmesh.spring.MeshPositionalBinder;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.tools.JavaCompiler;
import javax.tools.ToolProvider;
import java.io.File;
import java.lang.reflect.Method;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Tests for {@link MeshLegacyBindingDetector} — the issue #1401 migration
 * instrument.
 *
 * <p>The detector must fire on exactly the handler shapes whose meaning changes
 * when {@code @MeshRoute} / {@code @MeshA2A} move to positional binding, and on
 * nothing else. Both halves matter: a false positive in the instrument that is
 * meant to make the migration trustworthy is as damaging as a miss.
 */
@DisplayName("MeshLegacyBindingDetector: legacy-shape detection (issue #1401)")
class MeshLegacyBindingDetectorTest {

    @SuppressWarnings("unused")
    static class Routes {

        String agreeing(
                String body,
                @MeshInject("alpha") McpMeshTool a,
                @MeshInject("beta") McpMeshTool b) {
            return "";
        }

        String disagreeing(
                String body,
                @MeshInject("beta") McpMeshTool first,
                @MeshInject("alpha") McpMeshTool second) {
            return "";
        }

        String undeclared(@MeshInject("nope") McpMeshTool ghost) {
            return "";
        }

        String parameterNames(McpMeshTool alpha, McpMeshTool beta) {
            return "";
        }

        String parameterNamesSwapped(McpMeshTool beta, McpMeshTool alpha) {
            return "";
        }

        String camelCased(McpMeshTool baseCap) {
            return "";
        }

        /** Declares dependencies but injects none — reads them off the request. */
        String mapAccessOnly(String body) {
            return "";
        }

        /** One more parameter than there are dependencies to pair with. */
        String moreSlotsThanDeps(
                @MeshInject("alpha") McpMeshTool a,
                @MeshInject("alpha") McpMeshTool alsoAlpha) {
            return "";
        }

        String a2aInjectOnObject(Map<String, Object> message, @MeshInject("alpha") Object anything) {
            return "";
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // Shapes that do NOT change meaning — the detector must stay quiet
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("@MeshInject values in declaration order: OK, nothing changes")
    void agreeingInjectValuesAreOk() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("agreeing", deps("alpha", "beta"));

        assertEquals(MeshLegacyBindingDetector.Severity.OK, finding.severity());
        assertTrue(finding.message().contains("agree"), finding.message());
    }

    @Test
    @DisplayName("Parameter names in declaration order: OK")
    void agreeingParameterNamesAreOk() {
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            analyzeRoute("parameterNames", deps("alpha", "beta")).severity());
    }

    @Test
    @DisplayName("Kebab-case capability matched by its camelCased spec name: OK")
    void camelCasedSpecNameIsOk() {
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            analyzeRoute("camelCased",
                List.of(new MeshRouteRegistry.DependencySpec(
                    "base-cap", new String[0], "", "baseCap"))).severity());
    }

    @Test
    @DisplayName("NO FALSE POSITIVE: dependencies declared with zero injectable parameters is OK")
    void mapAccessStyleIsNotAnArityError() {
        // MeshRouteUtils.getDependencies(request) is a documented access style,
        // and a zero-parameter declaring route is the canonical way to publish a
        // capability edge for a constructor-injected @Qualifier bean. Arity is
        // deliberately not checked on this path.
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            analyzeRoute("mapAccessOnly", deps("alpha", "beta")).severity());
    }

    @Test
    @DisplayName("A handler with no dependencies and no slots is OK")
    void emptyHandlerIsOk() {
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            analyzeRoute("mapAccessOnly", List.of()).severity());
    }

    // ─────────────────────────────────────────────────────────────────
    // Shapes that DO change meaning
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("Reversed @MeshInject values: WARN printing both orderings and the reorder")
    void reversedInjectValuesWarn() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("disagreeing", deps("alpha", "beta"));

        assertEquals(MeshLegacyBindingDetector.Severity.WARN, finding.severity());
        String m = finding.message();
        assertTrue(m.contains("bindings WILL CHANGE"), m);
        // Both orderings, for both slots.
        assertTrue(m.contains("today (by name, @MeshInject(\"beta\")):"), m);
        assertTrue(m.contains("dependency[1] 'beta'"), m);
        assertTrue(m.contains("after alignment (by position):"), m);
        assertTrue(m.contains("dependency[0] 'alpha'"), m);
        // The prescription, in the order that preserves today's bindings.
        assertTrue(m.contains("Reorder dependencies = {...} to: [0] 'beta', [1] 'alpha'"), m);
        assertTrue(m.contains("MCP_MESH_STRICT_DI=true"), m);
    }

    @Test
    @DisplayName("Reversed parameter NAMES (no @MeshInject) warn identically")
    void reversedParameterNamesWarn() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("parameterNamesSwapped", deps("alpha", "beta"));

        assertEquals(MeshLegacyBindingDetector.Severity.WARN, finding.severity());
        assertTrue(finding.message().contains("by name, parameter name 'beta'"),
            finding.message());
    }

    @Test
    @DisplayName("@MeshInject naming nothing declared: ERROR — already broken today")
    void undeclaredInjectValueIsAnError() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("undeclared", deps("alpha"));

        assertEquals(MeshLegacyBindingDetector.Severity.ERROR, finding.severity());
        String m = finding.message();
        assertTrue(m.contains("resolves to NO declared dependency"), m);
        assertTrue(m.contains("already broken today"), m);
        assertTrue(m.contains("Fix the unbound parameter(s) first"), m);
    }

    @Test
    @DisplayName("Two parameters naming one dependency: WARN, and no reorder is prescribed")
    void nonInjectiveNamingCannotBeFixedByReordering() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("moreSlotsThanDeps", deps("alpha"));

        assertEquals(MeshLegacyBindingDetector.Severity.WARN, finding.severity());
        String m = finding.message();
        assertFalse(m.contains("Reorder dependencies = {...} to:"),
            "no reordering can give two parameters the same dependency: " + m);
        assertTrue(m.contains("no dependency declared at index 1"), m);
    }

    // ─────────────────────────────────────────────────────────────────
    // The load-bearing blind spot: no @MeshInject, no -parameters
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("LOAD-BEARING: without -parameters there is no name signal, so no working code exists")
    void withoutParameterNamesThereIsNoBinding() throws Exception {
        Method handler = compiledWithoutParameterNames();
        assumeTrue(handler != null, "system Java compiler unavailable");

        // The whole migration rests on this: a handler in this shape cannot be
        // working today, so it cannot regress from working to misbinding.
        // MeshInjectArgumentResolver logs an error and injects null (Spring's
        // MethodParameter.getParameterName() returns null — the reflection name
        // is the synthetic 'arg0', which the discoverer refuses); the A2A
        // dispatcher matches 'arg0' against nothing.
        assertFalse(handler.getParameters()[0].isNamePresent(),
            "fixture precondition: compiled without -parameters");
        assertEquals("arg0", handler.getParameters()[0].getName());

        MeshLegacyBindingDetector.Finding finding = MeshLegacyBindingDetector.analyze(
            "@MeshRoute", handler, MeshInjectableSlots.routeSlots(handler),
            deps("alpha", "beta"));

        assertEquals(MeshLegacyBindingDetector.Severity.ERROR, finding.severity());
        assertTrue(finding.message().contains("compiled without -parameters"),
            finding.message());
        assertTrue(finding.message().contains("already broken today"), finding.message());
    }

    // ─────────────────────────────────────────────────────────────────
    // Reporting policy
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("Default posture: a changed binding is a WARN, a broken one an ERROR — never fatal")
    void defaultPostureIsPermissive() {
        List<ILoggingEvent> events = capture(() -> {
            MeshLegacyBindingDetector.report(
                analyzeRoute("disagreeing", deps("alpha", "beta")), false);
            MeshLegacyBindingDetector.report(
                analyzeRoute("undeclared", deps("alpha")), false);
            MeshLegacyBindingDetector.report(
                analyzeRoute("agreeing", deps("alpha", "beta")), false);
        });

        assertEquals(List.of(Level.WARN, Level.ERROR),
            events.stream().map(ILoggingEvent::getLevel).toList(),
            "an agreeing handler must not be reported at all above DEBUG");
    }

    @Test
    @DisplayName("MCP_MESH_STRICT_DI: a changed binding becomes a boot failure")
    void strictModeFailsBoot() {
        assertThrows(IllegalStateException.class, () ->
            MeshLegacyBindingDetector.report(
                analyzeRoute("disagreeing", deps("alpha", "beta")), true));
        assertThrows(IllegalStateException.class, () ->
            MeshLegacyBindingDetector.report(analyzeRoute("undeclared", deps("alpha")), true));

        // ...but an agreeing handler still boots under strict.
        MeshLegacyBindingDetector.report(analyzeRoute("agreeing", deps("alpha", "beta")), true);
    }

    private static List<ILoggingEvent> capture(Runnable body) {
        ch.qos.logback.classic.Logger logger = (ch.qos.logback.classic.Logger)
            org.slf4j.LoggerFactory.getLogger(MeshLegacyBindingDetector.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            body.run();
        } finally {
            logger.detachAppender(appender);
        }
        return appender.list;
    }

    // ─────────────────────────────────────────────────────────────────
    // Slot classification, per path
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("Route slots are McpMeshTool parameters only; A2A slots also include @MeshInject")
    void slotClassificationDiffersPerPathAsTheResolversDo() {
        Method method = methodOf("a2aInjectOnObject");

        assertTrue(MeshInjectableSlots.routeSlots(method).isEmpty(),
            "Spring MVC must not claim a non-McpMeshTool parameter");
        assertEquals(List.of(1),
            MeshInjectableSlots.a2aSlots(method).stream()
                .map(MeshPositionalBinder.Slot::parameterPosition).toList(),
            "the dispatcher owns the whole argument array, so @MeshInject claims any type");

        // And the detector follows each path's own rule.
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            MeshLegacyBindingDetector.analyze("@MeshA2A", method,
                MeshInjectableSlots.a2aSlots(method), deps("alpha")).severity());
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    private static MeshLegacyBindingDetector.Finding analyzeRoute(
            String methodName, List<MeshRouteRegistry.DependencySpec> deps) {
        Method method = methodOf(methodName);
        return MeshLegacyBindingDetector.analyze(
            "@MeshRoute", method, MeshInjectableSlots.routeSlots(method), deps);
    }

    private static Method methodOf(String name) {
        for (Method m : Routes.class.getDeclaredMethods()) {
            if (m.getName().equals(name)) {
                return m;
            }
        }
        throw new AssertionError("No such route shape: " + name);
    }

    private static List<MeshRouteRegistry.DependencySpec> deps(String... capabilities) {
        return java.util.Arrays.stream(capabilities)
            .map(c -> new MeshRouteRegistry.DependencySpec(c, new String[0], "", c))
            .toList();
    }

    /**
     * Compile a handler <b>without</b> {@code -parameters} at test time — the
     * one shape this module cannot express in its own sources, since the build
     * passes {@code -parameters} to javac.
     *
     * @return the compiled handler method, or null when no system compiler is
     *         available (a JRE-only run)
     */
    private static Method compiledWithoutParameterNames() throws Exception {
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            return null;
        }
        Path dir = Files.createTempDirectory("mesh1401-noparams");
        dir.toFile().deleteOnExit();
        Path source = dir.resolve("NoParameterNames.java");
        Files.writeString(source, """
            import io.mcpmesh.types.McpMeshTool;

            public class NoParameterNames {
                public String handler(McpMeshTool first, McpMeshTool second) {
                    return "";
                }
            }
            """);

        String classpath = new File(McpMeshTool.class.getProtectionDomain()
            .getCodeSource().getLocation().toURI()).getAbsolutePath();
        int rc = compiler.run(null, null, null,
            "-classpath", classpath,
            "-d", dir.toString(),
            source.toString());
        if (rc != 0) {
            return null;
        }

        try (URLClassLoader loader = new URLClassLoader(
                new URL[]{dir.toUri().toURL()},
                MeshLegacyBindingDetectorTest.class.getClassLoader())) {
            Class<?> compiled = loader.loadClass("NoParameterNames");
            return compiled.getDeclaredMethod("handler", McpMeshTool.class, McpMeshTool.class);
        }
    }
}
