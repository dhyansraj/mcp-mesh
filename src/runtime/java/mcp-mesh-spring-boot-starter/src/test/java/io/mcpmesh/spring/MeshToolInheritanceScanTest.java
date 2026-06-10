package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1164 review follow-up (BLOCKER): the duplicate-capability boot error
 * must not fire for ONE logical tool seen through an inheritance hierarchy.
 *
 * <p>The previous scan ({@code ReflectionUtils.doWithMethods} with no
 * {@code MethodFilter}) visited an overridden/inherited {@code @MeshTool}
 * method once per declaring class (plus generic bridge methods), and each
 * visit re-registered the same capability — tripping the new fail-fast
 * {@code IllegalStateException} at boot for code that previously worked.
 * Both layers are covered here:
 *
 * <ul>
 *   <li>{@link MeshToolBeanPostProcessor} dedups to one registration per
 *       logical method (MethodIntrospector + BridgeMethodResolver);</li>
 *   <li>{@link MeshToolRegistry#registerTool} tolerates an override PAIR on
 *       the SAME bean instance (most-derived declaration wins) while still
 *       hard-failing for genuinely distinct methods claiming the same
 *       capability — including sibling beans of a base/derived pair.</li>
 * </ul>
 */
@DisplayName("@MeshTool inheritance — scan dedup + registry override tolerance (issue #1164 review)")
class MeshToolInheritanceScanTest {

    // ── Fixtures ────────────────────────────────────────────────────────────

    /** Fully-annotated abstract contract; bare subclass implementation. */
    public abstract static class AbstractGreeter {
        @MeshTool(capability = "greet", description = "greets someone")
        public abstract String greet(@Param("name") String name);
    }

    public static class GreeterImpl extends AbstractGreeter {
        @Override
        public String greet(String name) {
            return "hello " + name;
        }
    }

    /** Concrete base method overridden (and re-annotated) in the subclass. */
    public static class BaseCalc {
        @MeshTool(capability = "calc", description = "base calc")
        public String calc(@Param("x") String x) {
            return "base:" + x;
        }
    }

    public static class DerivedCalc extends BaseCalc {
        @Override
        @MeshTool(capability = "calc", description = "derived calc")
        public String calc(@Param("x") String x) {
            return "derived:" + x;
        }
    }

    /**
     * Override that re-declares {@code @MeshTool} but NOT {@code @Param}
     * (#1164 review follow-up) — the param metadata stays on the base.
     */
    public static class DerivedNoParamCalc extends BaseCalc {
        @Override
        @MeshTool(capability = "calc", description = "derived calc no param")
        public String calc(String x) {
            return "derivedNoParam:" + x;
        }
    }

    /** Fully-annotated interface contract (default method); bare impl class. */
    public interface PricerContract {
        @MeshTool(capability = "price", description = "prices a sku")
        default String price(@Param("sku") String sku) {
            return "default:" + sku;
        }
    }

    public static class PricerImpl implements PricerContract {
        @Override
        public String price(String sku) {
            return "impl:" + sku;
        }
    }

    /** Generic base whose specialization produces a compiler bridge method. */
    public abstract static class GenericEcho<T> {
        @MeshTool(capability = "echo", description = "echoes")
        public abstract String echo(@Param("v") T v);
    }

    public static class StringEcho extends GenericEcho<String> {
        @Override
        public String echo(@Param("v") String v) {
            return "echo:" + v;
        }
    }

    // ── Helpers ─────────────────────────────────────────────────────────────

    private static Method declaredMethod(Class<?> cls, String name) {
        for (Method m : cls.getDeclaredMethods()) {
            if (m.getName().equals(name) && !m.isBridge() && !m.isSynthetic()) {
                return m;
            }
        }
        throw new AssertionError("no method " + name + " on " + cls);
    }

    private static MeshToolBeanPostProcessor processor(MeshToolRegistry registry) {
        return new MeshToolBeanPostProcessor(
            registry,
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory()),
            JsonMapper.builder().build());
    }

    // ── Post-processor scan: one registration per logical tool ─────────────

    @Test
    @DisplayName("abstract @MeshTool contract implemented in subclass → boots, one tool, invokes the override")
    void abstractContractRegistersOnceAndInvokesOverride() throws Exception {
        MeshToolRegistry registry = new MeshToolRegistry();
        GreeterImpl bean = new GreeterImpl();

        assertDoesNotThrow(() -> processor(registry).postProcessAfterInitialization(bean, "greeter"),
            "inherited @MeshTool must not trip the duplicate-capability boot error");

        assertEquals(1, registry.getAllTools().size(), "exactly one logical tool");
        MeshToolRegistry.ToolMetadata meta = registry.getTool("greet");
        assertNotNull(meta);
        // Method.invoke dispatches virtually — the subclass override runs.
        assertEquals("hello mesh", meta.method().invoke(meta.bean(), "mesh"));
        // The abstract declaration carries the @Param annotations (parameter
        // annotations are NOT inherited) — they must survive into the schema.
        Map<String, Object> schema = meta.inputSchema();
        @SuppressWarnings("unchecked")
        Map<String, Object> props = (Map<String, Object>) schema.get("properties");
        assertTrue(props.containsKey("name"),
            "@Param metadata from the abstract declaration must be preserved. Got: " + props);
    }

    @Test
    @DisplayName("interface @MeshTool default-method contract implemented bare → boots, one tool, invokes the impl")
    void interfaceContractRegistersOnceAndInvokesImpl() throws Exception {
        MeshToolRegistry registry = new MeshToolRegistry();
        PricerImpl bean = new PricerImpl();

        assertDoesNotThrow(() -> processor(registry).postProcessAfterInitialization(bean, "pricer"),
            "interface-declared @MeshTool contract must register like the abstract-class form");

        assertEquals(1, registry.getAllTools().size(), "exactly one logical tool");
        MeshToolRegistry.ToolMetadata meta = registry.getTool("price");
        assertNotNull(meta);
        // Method.invoke dispatches virtually — the impl runs, not the default body.
        assertEquals("impl:abc", meta.method().invoke(meta.bean(), "abc"));
        // The interface declaration carries the @Param annotations (parameter
        // annotations are NOT inherited) — they must survive into the schema.
        Map<String, Object> schema = meta.inputSchema();
        @SuppressWarnings("unchecked")
        Map<String, Object> props = (Map<String, Object>) schema.get("properties");
        assertTrue(props.containsKey("sku"),
            "@Param metadata from the interface declaration must be preserved. Got: " + props);
    }

    @Test
    @DisplayName("concrete base overridden in subclass → boots, most-derived declaration wins")
    void concreteOverrideRegistersOnceMostDerivedWins() throws Exception {
        MeshToolRegistry registry = new MeshToolRegistry();
        DerivedCalc bean = new DerivedCalc();

        assertDoesNotThrow(() -> processor(registry).postProcessAfterInitialization(bean, "calc"),
            "an override pair is ONE logical tool, not a duplicate");

        assertEquals(1, registry.getAllTools().size());
        MeshToolRegistry.ToolMetadata meta = registry.getTool("calc");
        assertNotNull(meta);
        assertEquals("derived calc", meta.description(),
            "the most-derived @MeshTool declaration must win");
        assertEquals(DerivedCalc.class, meta.method().getDeclaringClass());
        assertEquals("derived:7", meta.method().invoke(meta.bean(), "7"));
    }

    @Test
    @DisplayName("override re-declares @MeshTool without @Param → boots, ancestor @Param schema kept, override values win")
    void redeclaredMeshToolWithoutParamKeepsAncestorSchema() throws Exception {
        // Previously the override's bare declaration was registered (it
        // declares @MeshTool), dropping the base @Param metadata — the
        // wrapper then boot-failed with "must have @Param annotation".
        MeshToolRegistry registry = new MeshToolRegistry();
        DerivedNoParamCalc bean = new DerivedNoParamCalc();

        assertDoesNotThrow(() -> processor(registry).postProcessAfterInitialization(bean, "calc"),
            "re-declared @MeshTool without @Param must fall back to the param-annotated ancestor");

        assertEquals(1, registry.getAllTools().size());
        MeshToolRegistry.ToolMetadata meta = registry.getTool("calc");
        assertNotNull(meta);
        // The override's @MeshTool values still apply (annotation resolved
        // from the most-derived declaration)...
        assertEquals("derived calc no param", meta.description(),
            "the override's @MeshTool values must win");
        // ...but the param-annotated ancestor is the schema source.
        assertEquals(BaseCalc.class, meta.method().getDeclaringClass(),
            "the param-annotated ancestor declaration must be the registration target");
        Map<String, Object> schema = meta.inputSchema();
        @SuppressWarnings("unchecked")
        Map<String, Object> props = (Map<String, Object>) schema.get("properties");
        assertTrue(props.containsKey("x"),
            "@Param metadata from the base declaration must be preserved. Got: " + props);
        // Method.invoke dispatches virtually — the override still runs.
        assertEquals("derivedNoParam:9", meta.method().invoke(meta.bean(), "9"));
    }

    @Test
    @DisplayName("generic base producing a bridge method → boots, one tool, specialized signature registered")
    void genericBridgeRegistersOnce() throws Exception {
        MeshToolRegistry registry = new MeshToolRegistry();
        StringEcho bean = new StringEcho();

        assertDoesNotThrow(() -> processor(registry).postProcessAfterInitialization(bean, "echo"),
            "bridge + generic super declaration must collapse onto one logical tool");

        assertEquals(1, registry.getAllTools().size());
        MeshToolRegistry.ToolMetadata meta = registry.getTool("echo");
        assertNotNull(meta);
        assertFalse(meta.method().isBridge(), "the bridge must never be the registered method");
        assertEquals(String.class, meta.method().getParameterTypes()[0],
            "the specialized override (not the erased generic declaration) must be registered");
        assertEquals("echo:hi", meta.method().invoke(meta.bean(), "hi"));
    }

    // ── Registry carve-out: override pairs tolerated, true duplicates fail ──

    @Test
    @DisplayName("registry tolerates base-then-derived registration; most-derived wins")
    void registryToleratesBaseThenDerived() {
        MeshToolRegistry registry = new MeshToolRegistry();
        Method base = declaredMethod(BaseCalc.class, "calc");
        Method derived = declaredMethod(DerivedCalc.class, "calc");
        DerivedCalc bean = new DerivedCalc();

        registry.registerTool(bean, base, base.getAnnotation(MeshTool.class));
        assertDoesNotThrow(() ->
            registry.registerTool(bean, derived, derived.getAnnotation(MeshTool.class)));

        assertEquals(derived, registry.getTool("calc").method(),
            "most-derived declaration must replace the base one");
    }

    @Test
    @DisplayName("registry tolerates derived-then-base registration; most-derived kept")
    void registryToleratesDerivedThenBase() {
        MeshToolRegistry registry = new MeshToolRegistry();
        Method base = declaredMethod(BaseCalc.class, "calc");
        Method derived = declaredMethod(DerivedCalc.class, "calc");
        DerivedCalc bean = new DerivedCalc();

        registry.registerTool(bean, derived, derived.getAnnotation(MeshTool.class));
        assertDoesNotThrow(() ->
            registry.registerTool(bean, base, base.getAnnotation(MeshTool.class)));

        assertEquals(derived, registry.getTool("calc").method(),
            "the already-registered most-derived declaration must be kept");
    }

    @Test
    @DisplayName("registry tolerates a generic-override pair (bridge-resolved)")
    void registryToleratesGenericOverridePair() {
        MeshToolRegistry registry = new MeshToolRegistry();
        Method base = declaredMethod(GenericEcho.class, "echo");
        Method derived = declaredMethod(StringEcho.class, "echo");
        StringEcho bean = new StringEcho();

        registry.registerTool(bean, base, base.getAnnotation(MeshTool.class));
        assertDoesNotThrow(() ->
            registry.registerTool(bean, derived, base.getAnnotation(MeshTool.class)),
            "generic specialization is the same logical method after bridge resolution");

        assertEquals(derived, registry.getTool("echo").method());
    }

    @Test
    @DisplayName("SIBLING beans — base bean + derived bean sharing a capability → boot error naming both")
    void siblingBeansFailFastInsteadOfMasking() {
        // The override-pair tolerance is scoped to ONE bean instance seen
        // through two declarations. TWO beans (a BaseCalc bean AND a
        // DerivedCalc bean) are two tools — previously the subclass bean
        // silently masked the base bean.
        MeshToolRegistry registry = new MeshToolRegistry();
        Method base = declaredMethod(BaseCalc.class, "calc");
        Method derived = declaredMethod(DerivedCalc.class, "calc");

        registry.registerTool(new BaseCalc(), base, base.getAnnotation(MeshTool.class));
        IllegalStateException ex = assertThrows(IllegalStateException.class, () ->
            registry.registerTool(new DerivedCalc(), derived, derived.getAnnotation(MeshTool.class)));

        assertTrue(ex.getMessage().contains("calc"),
            "error must name the colliding capability. Got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains(BaseCalc.class.getName())
                && ex.getMessage().contains(DerivedCalc.class.getName()),
            "error must name both declaration sites. Got: " + ex.getMessage());
    }

    @Test
    @DisplayName("SIBLING beans — derived-then-base ordering fails fast too")
    void siblingBeansFailFastDerivedFirst() {
        MeshToolRegistry registry = new MeshToolRegistry();
        Method base = declaredMethod(BaseCalc.class, "calc");
        Method derived = declaredMethod(DerivedCalc.class, "calc");

        registry.registerTool(new DerivedCalc(), derived, derived.getAnnotation(MeshTool.class));
        assertThrows(IllegalStateException.class, () ->
            registry.registerTool(new BaseCalc(), base, base.getAnnotation(MeshTool.class)),
            "the keep-existing-override branch must not hide a second bean either");
    }

    @Test
    @DisplayName("genuinely distinct methods claiming one capability still fail fast")
    void unrelatedDuplicateStillFails() {
        // Same-named capability from two UNRELATED classes — the override
        // carve-out must not soften the real conflict (existing contract,
        // see MeshToolRegistryDuplicateCapabilityTest for the full matrix).
        MeshToolRegistry registry = new MeshToolRegistry();
        Method one = declaredMethod(
            MeshToolRegistryDuplicateCapabilityTest.AgentOne.class, "lookupV1");
        Method two = declaredMethod(
            MeshToolRegistryDuplicateCapabilityTest.AgentTwo.class, "lookupV2");

        registry.registerTool(new MeshToolRegistryDuplicateCapabilityTest.AgentOne(),
            one, one.getAnnotation(MeshTool.class));
        assertThrows(IllegalStateException.class, () ->
            registry.registerTool(new MeshToolRegistryDuplicateCapabilityTest.AgentTwo(),
                two, two.getAnnotation(MeshTool.class)));
    }
}
