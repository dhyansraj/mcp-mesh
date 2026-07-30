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
 * Tests for {@link MeshLegacyBindingDetector} — the issue #1401 boot-time
 * guard for the positional dependency contract.
 *
 * <p><b>What changed.</b> The predecessor of this file pinned a warning-only
 * migration instrument that compared today's name binding with tomorrow's
 * positional binding. Positional binding has landed, so the class now enforces
 * rather than forecasts:
 *
 * <ul>
 *   <li>a {@code @MeshInject} value that contradicts the position is an
 *       <b>ERROR that fails the boot</b>, where it used to be a WARN;</li>
 *   <li>a parameter name that points elsewhere is a <b>WARN</b> — a migration
 *       signal, not a rule, because names carry no meaning now;</li>
 *   <li>the two shapes that used to be ERRORs because they bound to
 *       <i>nothing</i> — a name matching no declared capability, and a class
 *       compiled without {@code -parameters} — are <b>OK</b>. They were broken
 *       only because names were the binding key. Removing the key fixed them.
 *       That last one is the claim the whole migration rested on, so it is kept
 *       and inverted rather than deleted.</li>
 * </ul>
 *
 * <p>Both halves still matter: a false positive in a check that can stop a boot
 * is as damaging as a miss.
 */
@DisplayName("MeshLegacyBindingDetector: the positional binding guard (issue #1401)")
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

        String unrelatedParameterNames(McpMeshTool primary, McpMeshTool secondary) {
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

        /** Surplus parameters, no assertions — perfectly legal, injected null. */
        String moreSlotsThanDepsUnannotated(McpMeshTool a, McpMeshTool b) {
            return "";
        }

        String a2aInjectOnObject(Map<String, Object> message, @MeshInject("alpha") Object anything) {
            return "";
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // Shapes the guard must stay quiet about
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("@MeshInject values in declaration order: OK — the assertion holds")
    void agreeingInjectValuesAreOk() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("agreeing", deps("alpha", "beta"));

        assertEquals(MeshLegacyBindingDetector.Severity.OK, finding.severity());
        assertTrue(finding.message().contains("consistent"), finding.message());
    }

    @Test
    @DisplayName("Parameter names in declaration order: OK")
    void agreeingParameterNamesAreOk() {
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            analyzeRoute("parameterNames", deps("alpha", "beta")).severity());
    }

    @Test
    @DisplayName("NOW OK: parameter names matching no declared capability")
    void unrelatedParameterNamesAreOk() {
        // Under name binding these two parameters bound to nothing and were
        // injected null (an ERROR in the predecessor of this class). Under
        // positional binding they are ordinary slots — the name was never
        // meant to carry information.
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            analyzeRoute("unrelatedParameterNames", deps("alpha", "beta")).severity());
    }

    @Test
    @DisplayName("Kebab-case capability asserted by its camelCased spec name: OK")
    void camelCasedSpecNameIsAValidAssertion() {
        // @MeshDependency(name = ...) is an explicit second spelling of the same
        // edge, so asserting it is legal — it can never point at a DIFFERENT
        // dependency, which is the whole check.
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            MeshLegacyBindingDetector.analyze("@MeshRoute", methodOf("camelCased"),
                MeshInjectableSlots.routeSlots(methodOf("camelCased")),
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

    @Test
    @DisplayName("Unannotated surplus parameters are OK — they are simply injected null")
    void surplusUnannotatedSlotsAreOk() {
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            analyzeRoute("moreSlotsThanDepsUnannotated", deps("alpha")).severity());
    }

    // ─────────────────────────────────────────────────────────────────
    // The assertion: @MeshInject must agree with the position
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("Reversed @MeshInject values: ERROR printing both orderings and the reorder")
    void reversedInjectValuesAreAnError() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("disagreeing", deps("alpha", "beta"));

        assertEquals(MeshLegacyBindingDetector.Severity.ERROR, finding.severity());
        String m = finding.message();
        assertTrue(m.contains("@MeshInject value contradicts"), m);
        assertTrue(m.contains("ASSERTS the one positional pairing assigns"), m);
        // Both orderings, for both slots.
        assertTrue(m.contains("@MeshInject(\"beta\") asserts:"), m);
        assertTrue(m.contains("dependency[1] 'beta'"), m);
        assertTrue(m.contains("binds (by position):"), m);
        assertTrue(m.contains("dependency[0] 'alpha'"), m);
        // The prescription, in the order the assertions describe.
        assertTrue(m.contains("reorder dependencies = {...} to: [0] 'beta', [1] 'alpha'"), m);
        assertTrue(m.contains("correct the @MeshInject value"), m);
    }

    @Test
    @DisplayName("@MeshInject naming nothing declared: ERROR")
    void undeclaredInjectValueIsAnError() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("undeclared", deps("alpha"));

        assertEquals(MeshLegacyBindingDetector.Severity.ERROR, finding.severity());
        String m = finding.message();
        assertTrue(m.contains("@MeshInject(\"nope\") asserts:"), m);
        assertTrue(m.contains("NO MATCH among the declared dependencies"), m);
    }

    @Test
    @DisplayName("An assertion at a position with no declared dependency: ERROR, no reorder prescribed")
    void assertionBeyondTheDeclaredListIsAnError() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("moreSlotsThanDeps", deps("alpha"));

        assertEquals(MeshLegacyBindingDetector.Severity.ERROR, finding.severity());
        String m = finding.message();
        assertFalse(m.contains("reorder dependencies = {...} to:"),
            "no reordering can give two parameters the same dependency: " + m);
        assertTrue(m.contains("no dependency declared at index 1"), m);
    }

    @Test
    @DisplayName("An assertion failure is fatal with OR without MCP_MESH_STRICT_DI")
    void assertionFailureIsAlwaysFatal() {
        assertThrows(IllegalStateException.class, () ->
            MeshLegacyBindingDetector.report(
                analyzeRoute("disagreeing", deps("alpha", "beta")), false));
        assertThrows(IllegalStateException.class, () ->
            MeshLegacyBindingDetector.report(
                analyzeRoute("disagreeing", deps("alpha", "beta")), true));
    }

    // ─────────────────────────────────────────────────────────────────
    // The migration signal: parameter names that point elsewhere
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("Reversed parameter NAMES (no @MeshInject): WARN, with the pre-3.4 framing")
    void reversedParameterNamesWarn() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeRoute("parameterNamesSwapped", deps("alpha", "beta"));

        assertEquals(MeshLegacyBindingDetector.Severity.WARN, finding.severity());
        String m = finding.message();
        assertTrue(m.contains("parameter name 'beta' used to bind:"), m);
        assertTrue(m.contains("mcp-mesh 3.3 or earlier"), m);
        assertTrue(m.contains("add @MeshInject"), m);
        assertTrue(m.contains("MCP_MESH_STRICT_DI=true"), m);
    }

    @Test
    @DisplayName("A name crossover becomes a boot failure under MCP_MESH_STRICT_DI")
    void strictModePromotesTheWarning() {
        assertThrows(IllegalStateException.class, () ->
            MeshLegacyBindingDetector.report(
                analyzeRoute("parameterNamesSwapped", deps("alpha", "beta")), true));

        // ...but an agreeing handler still boots under strict.
        MeshLegacyBindingDetector.report(analyzeRoute("agreeing", deps("alpha", "beta")), true);
    }

    @Test
    @DisplayName("Default posture: a name crossover logs a WARN and nothing else is reported")
    void defaultPostureIsPermissiveForNames() {
        List<ILoggingEvent> events = capture(() -> {
            MeshLegacyBindingDetector.report(
                analyzeRoute("parameterNamesSwapped", deps("alpha", "beta")), false);
            MeshLegacyBindingDetector.report(
                analyzeRoute("agreeing", deps("alpha", "beta")), false);
            MeshLegacyBindingDetector.report(
                analyzeRoute("unrelatedParameterNames", deps("alpha", "beta")), false);
        });

        assertEquals(List.of(Level.WARN),
            events.stream().map(ILoggingEvent::getLevel).toList(),
            "only the crossover is reported above DEBUG");
    }

    // ─────────────────────────────────────────────────────────────────
    // The load-bearing blind spot, now closed: no @MeshInject, no -parameters
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("LOAD-BEARING, inverted: without -parameters a handler now binds correctly")
    void withoutParameterNamesBindingNowWorks() throws Exception {
        Method handler = compiledWithoutParameterNames();
        assumeTrue(handler != null, "system Java compiler unavailable");

        // The migration rested on this shape containing no WORKING code: with no
        // name to match, MeshInjectArgumentResolver logged an error and injected
        // null (Spring's MethodParameter.getParameterName() returns null — the
        // reflection name is the synthetic 'arg0', which the discoverer
        // refuses), and the A2A dispatcher matched 'arg0' against nothing. So
        // nobody could regress from working to misbinding. Positional binding
        // does not need a name at all, so the same shape is now correct — and
        // must be reported as OK, not as the ERROR it used to be.
        assertFalse(handler.getParameters()[0].isNamePresent(),
            "fixture precondition: compiled without -parameters");
        assertEquals("arg0", handler.getParameters()[0].getName());

        MeshLegacyBindingDetector.Finding finding = MeshLegacyBindingDetector.analyze(
            "@MeshRoute", handler, MeshInjectableSlots.routeSlots(handler),
            deps("alpha", "beta"));

        assertEquals(MeshLegacyBindingDetector.Severity.OK, finding.severity(), finding.message());
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

        // And the guard follows each path's own rule.
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            MeshLegacyBindingDetector.analyze("@MeshA2A", method,
                MeshInjectableSlots.a2aSlots(method), deps("alpha")).severity());
    }

    // ─────────────────────────────────────────────────────────────────
    // @MeshTool: the assertion applies, the name signal does not
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("@MeshTool: a contradicting @MeshInject is an ERROR there too")
    void toolAssertionIsChecked() {
        MeshLegacyBindingDetector.Finding finding =
            analyzeTool("disagreeing", "alpha", "beta");

        assertEquals(MeshLegacyBindingDetector.Severity.ERROR, finding.severity());
        assertTrue(finding.message().startsWith("@MeshTool "), finding.message());
    }

    @Test
    @DisplayName("@MeshTool: crossing parameter NAMES are NOT reported — it was never name-based")
    void toolNamesAreNotAMigrationSignal() {
        // The name-crossover warning exists to catch handlers written when
        // @MeshRoute / @MeshA2A bound by name. @MeshTool has always been
        // positional, so a name coincidence there says nothing.
        assertEquals(MeshLegacyBindingDetector.Severity.OK,
            analyzeTool("parameterNamesSwapped", "alpha", "beta").severity());
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

    private static MeshLegacyBindingDetector.Finding analyzeTool(
            String methodName, String... capabilities) {
        Method method = methodOf(methodName);
        List<MeshPositionalBinder.Slot> slots = MeshInjectableSlots.routeSlots(method);
        return MeshLegacyBindingDetector.analyzeTool(MeshPositionalBinder.bind(
            method, slots, List.of(capabilities), capabilities.length));
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
