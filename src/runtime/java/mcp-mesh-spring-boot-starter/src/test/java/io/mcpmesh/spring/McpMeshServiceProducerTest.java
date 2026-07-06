package io.mcpmesh.spring;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * RFC #1280 phase 3: producer sugar — a class annotated {@code @McpMeshService("prefix")}
 * publishes each eligible method as an ordinary mesh tool with capability
 * {@code "prefix.<methodName>"}. Drives {@link MeshToolBeanPostProcessor} directly
 * (mirrors {@link MeshToolInheritanceScanTest}).
 */
class McpMeshServiceProducerTest {

    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    private static MeshToolBeanPostProcessor processor(MeshToolRegistry registry) {
        return new MeshToolBeanPostProcessor(
            registry,
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory()),
            JsonMapper.builder().build());
    }

    private static List<String> capabilities(MeshToolRegistry registry) {
        return registry.getToolSpecs().stream()
            .map(AgentSpec.ToolSpec::getCapability).sorted().toList();
    }

    // ---- Publication --------------------------------------------------------

    @McpMeshService("media")
    public static class MediaTools {
        public String caption(@Param("text") String text) {
            return "cap:" + text;
        }

        public String thumbnail(@Param("assetId") String assetId) {
            return "thumb:" + assetId;
        }
    }

    @Test
    void publishesEachMethodWithPrefixedCapability() {
        MeshToolRegistry registry = new MeshToolRegistry();
        processor(registry).postProcessAfterInitialization(new MediaTools(), "media");

        assertEquals(List.of("media.caption", "media.thumbnail"), capabilities(registry));
        // Schemas come from the existing @MeshTool machinery — each method's
        // @Param drives the input schema.
        assertTrue(registry.getTool("media.caption").inputSchema().toString().contains("text"));
        assertTrue(registry.getTool("media.thumbnail").inputSchema().toString().contains("assetId"));
    }

    @Test
    void dottedCapabilityRoundTripsInSpec() throws Exception {
        MeshToolRegistry registry = new MeshToolRegistry();
        processor(registry).postProcessAfterInitialization(new MediaTools(), "media");

        AgentSpec.ToolSpec spec = registry.getToolSpecs().stream()
            .filter(t -> "media.caption".equals(t.getCapability())).findFirst().orElseThrow();
        // The dotted capability name survives serialization intact.
        assertTrue(MAPPER.writeValueAsString(spec).contains("\"capability\":\"media.caption\""));
    }

    // ---- Blank prefix boot-fail ---------------------------------------------

    @McpMeshService
    public static class BlankPrefixTools {
        public String greet(@Param("name") String name) {
            return name;
        }
    }

    @Test
    void blankPrefixBootFails() {
        MeshToolRegistry registry = new MeshToolRegistry();
        IllegalStateException ex = assertThrows(IllegalStateException.class,
            () -> processor(registry).postProcessAfterInitialization(new BlankPrefixTools(), "b"));
        assertTrue(ex.getMessage().contains("needs a name prefix"), ex.getMessage());
    }

    // ---- minAvailable on a producer class → WARN + ignore -------------------

    @McpMeshService(value = "svc", minAvailable = 2)
    public static class MinAvailableTools {
        public String a(@Param("x") String x) {
            return x;
        }
    }

    @Test
    void minAvailableOnClassWarnsAndIsIgnored() {
        LogCapture capture = LogCapture.attach(MeshToolBeanPostProcessor.class);
        try {
            MeshToolRegistry registry = new MeshToolRegistry();
            processor(registry).postProcessAfterInitialization(new MinAvailableTools(), "m");
            // Still publishes (soft-fail philosophy).
            assertEquals(List.of("svc.a"), capabilities(registry));
            assertTrue(capture.events.stream().anyMatch(e -> "WARN".equals(e.level)
                    && e.message.contains("minAvailable")
                    && e.message.contains(MinAvailableTools.class.getName())),
                "minAvailable on a producer class must WARN");
        } finally {
            capture.detach();
        }
    }

    // ---- Explicit @MeshTool wins (no double publish) ------------------------

    @McpMeshService("shop")
    public static class MixedTools {
        @MeshTool(capability = "custom_cart")
        public String cart(@Param("id") String id) {
            return id;
        }

        public String browse(@Param("q") String q) {
            return q;
        }
    }

    @Test
    void explicitMeshToolWins_noDoublePublish() {
        MeshToolRegistry registry = new MeshToolRegistry();
        processor(registry).postProcessAfterInitialization(new MixedTools(), "mixed");
        // cart publishes under its OWN @MeshTool capability (NOT "shop.cart");
        // browse gets the sugar name.
        assertEquals(List.of("custom_cart", "shop.browse"), capabilities(registry));
    }

    // ---- Non-public methods ignored -----------------------------------------

    @McpMeshService("vis")
    public static class VisibilityTools {
        public String pub(@Param("x") String x) {
            return x;
        }

        protected String prot(@Param("x") String x) {
            return x;
        }

        String pkg(@Param("x") String x) {
            return x;
        }

        private String priv(@Param("x") String x) {
            return x;
        }

        public static String stat(@Param("x") String x) {
            return x;
        }
    }

    @Test
    void nonPublicAndStaticMethodsIgnored() {
        MeshToolRegistry registry = new MeshToolRegistry();
        processor(registry).postProcessAfterInitialization(new VisibilityTools(), "v");
        assertEquals(List.of("vis.pub"), capabilities(registry));
    }

    // ---- Object overrides ignored (footgun guard) ---------------------------

    @McpMeshService("obj")
    public static class ObjectOverrideTools {
        public String work(@Param("x") String x) {
            return x;
        }

        @Override
        public String toString() {
            return "ObjectOverrideTools";
        }

        @Override
        public boolean equals(Object o) {
            return this == o;
        }

        @Override
        public int hashCode() {
            return 1;
        }
    }

    @Test
    void objectOverridesIgnored() {
        MeshToolRegistry registry = new MeshToolRegistry();
        processor(registry).postProcessAfterInitialization(new ObjectOverrideTools(), "o");
        assertEquals(List.of("obj.work"), capabilities(registry));
    }

    // ---- Duplicate capability boot-fail through the sugar path --------------

    @McpMeshService("dup")
    public static class DupSugarTools {
        public String same(@Param("x") String x) {
            return x;
        }
    }

    public static class DupExplicitTools {
        @MeshTool(capability = "dup.same")
        public String other(@Param("x") String x) {
            return x;
        }
    }

    @Test
    void duplicateCapabilityThroughSugarBootFails() {
        MeshToolRegistry registry = new MeshToolRegistry();
        MeshToolBeanPostProcessor bpp = processor(registry);
        // Explicit tool claims "dup.same" first.
        bpp.postProcessAfterInitialization(new DupExplicitTools(), "explicit");
        // The sugar path generates the SAME capability → the existing #1164
        // duplicate-capability boot error fires unchanged.
        assertThrows(IllegalStateException.class,
            () -> bpp.postProcessAfterInitialization(new DupSugarTools(), "sugar"));
    }

    // ---- Injectable slot types fall out naturally (rule 3) ------------------

    @McpMeshService("inj")
    public static class InjectableTools {
        // A producer method may take an injectable McpMeshTool slot; it goes
        // through the same wrapper machinery. Without an explicit @MeshTool it
        // has no declared dependency, so the slot stays null (graceful
        // degradation) — no boot-fail.
        public String enrich(@Param("x") String x, McpMeshTool<String> helper) {
            return x;
        }
    }

    @Test
    void injectableSlotParamsPublishWithoutError() {
        MeshToolRegistry registry = new MeshToolRegistry();
        assertDoesNotThrow(() ->
            processor(registry).postProcessAfterInitialization(new InjectableTools(), "i"));
        assertEquals(List.of("inj.enrich"), capabilities(registry));
        // No @MeshTool(dependencies=), so the tool declares zero deps.
        assertTrue(registry.getTool("inj.enrich").dependencies().isEmpty());
    }

    // ---- item 7b: registry consumes PASSED view params (no re-derivation) ---

    @McpMeshService
    public interface EdgeView {
        @Selector(capability = "edge.x")
        String x(@Param("id") String id);
    }

    public static class ViewParamBean {
        @MeshTool(capability = "vp_tool")
        public String run(@Param("x") String x, EdgeView view) {
            return x;
        }
    }

    @Test
    void registryUsesPassedViewParams_notReDerived() throws Exception {
        // Passing an EMPTY viewParams list to the overload yields a tool with NO
        // view edges even though the method HAS a view param — proving the
        // registry consumes the caller's single analysis instead of re-deriving.
        MeshToolRegistry registry = new MeshToolRegistry();
        var m = ViewParamBean.class.getMethod("run", String.class, EdgeView.class);
        registry.registerTool(new ViewParamBean(), m, m.getAnnotation(MeshTool.class), List.of());

        AgentSpec.ToolSpec spec = registry.getToolSpecs().stream()
            .filter(t -> "vp_tool".equals(t.getCapability())).findFirst().orElseThrow();
        assertTrue(spec.getDependencies() == null || spec.getDependencies().isEmpty(),
            "empty passed viewParams → no view edges (registry did not re-derive)");
    }

    // ---- MED-4: prefix validated segment-wise at boot -----------------------

    @McpMeshService("bad prefix")
    public static class SpacePrefixTools {
        public String a(@Param("x") String x) { return x; }
    }

    @McpMeshService("a..b")
    public static class DoubleDotPrefixTools {
        public String a(@Param("x") String x) { return x; }
    }

    @McpMeshService("1media")
    public static class DigitStartPrefixTools {
        public String a(@Param("x") String x) { return x; }
    }

    @McpMeshService("media.v2")
    public static class DottedPrefixTools {
        public String go(@Param("x") String x) { return x; }
    }

    @Test
    void invalidPrefixBootFails() {
        for (Object bad : List.of(new SpacePrefixTools(), new DoubleDotPrefixTools(),
                new DigitStartPrefixTools())) {
            MeshToolRegistry registry = new MeshToolRegistry();
            IllegalStateException ex = assertThrows(IllegalStateException.class,
                () -> processor(registry).postProcessAfterInitialization(bad, "b"),
                () -> "expected boot-fail for " + bad.getClass().getSimpleName());
            assertTrue(ex.getMessage().contains("prefix") && ex.getMessage().contains("invalid"),
                ex.getMessage());
        }
    }

    @Test
    void multiSegmentPrefixIsValid() {
        MeshToolRegistry registry = new MeshToolRegistry();
        processor(registry).postProcessAfterInitialization(new DottedPrefixTools(), "d");
        assertEquals(List.of("media.v2.go"), capabilities(registry));
    }

    @Test
    void isValidCapabilityName_rejectsDollarAndUnicodeSegments() {
        // A derived capability is validated in FULL (prefix + "." + methodName);
        // Java method names may contain '$' or Unicode letters that the grammar
        // rejects (unit-testable without a real Method).
        assertTrue(MeshToolBeanPostProcessor.isValidCapabilityName("media"));
        assertTrue(MeshToolBeanPostProcessor.isValidCapabilityName("media.caption"));
        assertTrue(MeshToolBeanPostProcessor.isValidCapabilityName("media.v2"));
        assertFalse(MeshToolBeanPostProcessor.isValidCapabilityName("media.go$1"),
            "'$' is legal in a Java identifier but not a capability segment");
        assertFalse(MeshToolBeanPostProcessor.isValidCapabilityName("media.café"),
            "Unicode letters are legal in Java identifiers but not capability segments");
        assertFalse(MeshToolBeanPostProcessor.isValidCapabilityName("media."));
        assertFalse(MeshToolBeanPostProcessor.isValidCapabilityName(null));
    }

    // ---- MED-5: deterministic publication order -----------------------------

    @McpMeshService("ord")
    public static class UnorderedTools {
        public String zulu(@Param("x") String x) { return x; }
        public String alpha(@Param("x") String x) { return x; }
        public String mike(@Param("x") String x) { return x; }
    }

    @Test
    void publicationOrderIsMethodNameSorted() {
        LogCapture capture = LogCapture.attachDebug(MeshToolBeanPostProcessor.class);
        try {
            MeshToolRegistry registry = new MeshToolRegistry();
            processor(registry).postProcessAfterInitialization(new UnorderedTools(), "u");
            List<String> publishedOrder = capture.events.stream()
                .filter(e -> e.message.contains("published") && e.message.contains("ord."))
                .map(e -> e.message.replaceAll(".*published UnorderedTools\\.(\\w+).*", "$1"))
                .toList();
            assertEquals(List.of("alpha", "mike", "zulu"), publishedOrder,
                "producer methods must publish in method-name order");
        } finally {
            capture.detach();
        }
    }

    // ---- MED-6: overloaded public methods collide on prefix.name ------------

    @McpMeshService("ov")
    public static class OverloadTools {
        public String go(@Param("x") String x) { return x; }
        public String go(@Param("x") String x, @Param("y") String y) { return x + y; }
    }

    @Test
    void overloadedMethodsBootFailExplicitly() {
        MeshToolRegistry registry = new MeshToolRegistry();
        IllegalStateException ex = assertThrows(IllegalStateException.class,
            () -> processor(registry).postProcessAfterInitialization(new OverloadTools(), "o"));
        assertTrue(ex.getMessage().contains("overloaded"), ex.getMessage());
        assertTrue(ex.getMessage().contains("ov.go"), ex.getMessage());
    }

    // ---- MED-2: CGLIB-enhanced producer detected via getUserClass -----------

    @Test
    void cglibEnhancedProducerIsDetected() {
        org.springframework.cglib.proxy.Enhancer enhancer =
            new org.springframework.cglib.proxy.Enhancer();
        enhancer.setSuperclass(MediaTools.class);
        enhancer.setCallback(org.springframework.cglib.proxy.NoOp.INSTANCE);
        MediaTools enhanced = (MediaTools) enhancer.create();
        assertTrue(enhanced.getClass().getName().contains("$$"),
            "sanity: the instance is a CGLIB subclass");

        MeshToolRegistry registry = new MeshToolRegistry();
        processor(registry).postProcessAfterInitialization(enhanced, "media");
        // getUserClass strips the $$ subclass → the real @McpMeshService class.
        assertEquals(List.of("media.caption", "media.thumbnail"), capabilities(registry));
    }

    // ---- item 9: superclass-inherited public methods NOT published ----------

    public static class BaseProducer {
        public String base(@Param("x") String x) { return x; }
    }

    @McpMeshService("sub")
    public static class SubProducer extends BaseProducer {
        public String own(@Param("x") String x) { return x; }
    }

    @Test
    void superclassInheritedMethodsNotPublished() {
        MeshToolRegistry registry = new MeshToolRegistry();
        processor(registry).postProcessAfterInitialization(new SubProducer(), "sub");
        // Only the DECLARED method — inherited "base" is not published.
        assertEquals(List.of("sub.own"), capabilities(registry));
    }

    /** Minimal Logback appender recording level + message for a target logger. */
    static final class LogCapture {
        final java.util.List<LogEvent> events = new java.util.concurrent.CopyOnWriteArrayList<>();
        private final ch.qos.logback.classic.Logger target;
        private final ch.qos.logback.core.AppenderBase<ch.qos.logback.classic.spi.ILoggingEvent> appender;

        private LogCapture(ch.qos.logback.classic.Logger target) {
            this.target = target;
            this.appender = new ch.qos.logback.core.AppenderBase<>() {
                @Override
                protected void append(ch.qos.logback.classic.spi.ILoggingEvent event) {
                    events.add(new LogEvent(event.getLevel().toString(), event.getFormattedMessage()));
                }
            };
        }

        static LogCapture attach(Class<?> loggerClass) {
            ch.qos.logback.classic.Logger logger =
                (ch.qos.logback.classic.Logger) org.slf4j.LoggerFactory.getLogger(loggerClass);
            LogCapture capture = new LogCapture(logger);
            // Store the prior level UNCONDITIONALLY so detach() restores it
            // verbatim — never clobbering an explicitly-configured level.
            capture.priorLevel = logger.getLevel();
            capture.appender.setContext(logger.getLoggerContext());
            capture.appender.start();
            logger.addAppender(capture.appender);
            return capture;
        }

        /** Attach and force DEBUG so debug-level lines are captured. */
        static LogCapture attachDebug(Class<?> loggerClass) {
            LogCapture capture = attach(loggerClass);
            capture.target.setLevel(ch.qos.logback.classic.Level.DEBUG);
            return capture;
        }

        private ch.qos.logback.classic.Level priorLevel;

        void detach() {
            target.setLevel(priorLevel); // restore verbatim (may be null = inherit)
            target.detachAppender(appender);
            appender.stop();
        }

        record LogEvent(String level, String message) {}
    }
}
