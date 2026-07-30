package io.mcpmesh.spring;

import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Tests for {@link MeshDiValidator} — Java's dependency-count / slot-count
 * check, at parity with Python's {@code validate_mesh_dependencies}
 * (issue #1401).
 *
 * <p>Strictness is passed explicitly rather than read from the environment:
 * {@code MCP_MESH_STRICT_DI} cannot be set in-process, and the ambient overload
 * is a one-line delegation to the explicit one.
 */
@DisplayName("MeshDiValidator: @MeshTool arity validation (issue #1401)")
class MeshDiValidatorTest {

    @SuppressWarnings("unused")
    static class Shapes {
        void matched(@io.mcpmesh.Param("x") String x, McpMeshTool a, McpMeshTool b) {}

        void tooFewParams(@io.mcpmesh.Param("x") String x, McpMeshTool only) {}

        void tooManyParams(McpMeshTool a, McpMeshTool b, McpMeshTool c) {}

        void withJob(McpMeshTool a, MeshJob job) {}

        void viewShape(@io.mcpmesh.Param("x") String x, McpMeshTool explicitDep) {}

        void withLlmAgent(McpMeshTool a, MeshLlmAgent llm) {}
    }

    // ─────────────────────────────────────────────────────────────────
    // Sound arity
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("Counts match: nothing reported, nothing thrown, in either mode")
    void matchedArityIsSilent() {
        MeshPositionalBinder.Binding binding = bind("matched", List.of(1, 2), null,
            List.of("cap_a", "cap_b"), 2);

        assertNull(MeshDiValidator.checkArity("@MeshTool", binding, binding.slots().size(), binding.slots().size(), false));
        assertNull(MeshDiValidator.checkArity("@MeshTool", binding, binding.slots().size(), binding.slots().size(), true));
    }

    @Test
    @DisplayName("CONSUMER MeshJob slot consumes a declared dependency and counts toward arity")
    void consumerJobSlotCountsAsAnInjectableSlot() {
        MeshPositionalBinder.Binding binding = bind("withJob", List.of(0), 1,
            List.of("cap_a", "job_cap"), 2);

        assertNull(MeshDiValidator.checkArity("@MeshTool", binding, binding.slots().size(), binding.slots().size(), true));
    }

    @Test
    @DisplayName("TRAP 3: a PRODUCER's MeshJob controller slot is OPTIONALLY declared")
    void producerJobControllerSlotIsOptional() {
        // On a task=true tool the MeshJob parameter is the inbound job's
        // controller — the dispatch path fills it, and JobsRuntimeManager
        // explicitly skips task() tools when wiring submitters. Producers
        // normally declare nothing for it (counting it would flag every
        // long-running producer in the ecosystem), yet declaring a capability
        // at its index is also supported and skews the pairing table. Both
        // counts must pass.
        MeshPositionalBinder.Binding undeclared = bind("withJob", List.of(0), 1,
            List.of("cap_a"), 1);
        assertNull(MeshDiValidator.checkArity("@MeshTool", undeclared, 1, 2, true),
            "the producer's controller slot must not demand a declared dependency");

        MeshPositionalBinder.Binding declared = bind("withJob", List.of(0), 1,
            List.of("job_cap", "cap_a"), 2);
        assertNull(MeshDiValidator.checkArity("@MeshTool", declared, 1, 2, true),
            "a producer MAY declare a capability at the job slot's index");

        // ...but the same shape read as a CONSUMER must be backed exactly.
        assertNotNull(MeshDiValidator.checkArity("@MeshTool", undeclared, 2, 2, false));
    }

    @Test
    @DisplayName("TRAP 1: @MeshService view edges are not phantom excess dependencies")
    void viewEdgesAreNotCountedAsExcess() {
        // The declared list is the explicit @Selector prefix plus RFC-1280 view
        // edges; only the prefix is pairable. Counting capabilities.size() here
        // would report two phantom excess dependencies.
        MeshPositionalBinder.Binding binding = bind("viewShape", List.of(1), null,
            List.of("explicit_cap", "view_edge_one", "view_edge_two"), 1);

        assertEquals(3, binding.capabilities().size());
        assertEquals(1, binding.pairableDepCount());
        assertNull(MeshDiValidator.checkArity("@MeshTool", binding, binding.slots().size(), binding.slots().size(), true),
            "view edges own no injectable parameter by construction");
    }

    @Test
    @DisplayName("TRAP 2: MeshLlmAgent parameters are invisible to arity checking by construction")
    void llmAgentParametersAreNotSlots() {
        // MeshToolWrapper.analyzeParameters puts MeshLlmAgent positions in a
        // separate index space (@MeshLlm has no dependencies member), so the
        // agent parameter is neither a slot nor backed by a declared entry.
        MeshPositionalBinder.Binding binding = bind("withLlmAgent", List.of(0), null,
            List.of("cap_a"), 1);

        assertNull(MeshDiValidator.checkArity("@MeshTool", binding, binding.slots().size(), binding.slots().size(), true));
    }

    // ─────────────────────────────────────────────────────────────────
    // Mismatched arity
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("More dependencies than slots: WARN by default, naming both counts and the fix")
    void surplusDependenciesWarnByDefault() {
        MeshPositionalBinder.Binding binding = bind("tooFewParams", List.of(1), null,
            List.of("cap_a", "cap_b"), 2);

        String message = MeshDiValidator.checkArity("@MeshTool", binding, binding.slots().size(), binding.slots().size(), false);

        assertNotNull(message, "a dep/slot mismatch must be reported, never silently dropped");
        assertTrue(message.contains("declares 2 dependencies"), message);
        assertTrue(message.contains("has 1 dependency-backed injectable parameter"), message);
        assertTrue(message.contains("injected nowhere"), message);
        assertTrue(message.contains("dependencies[i] pairs with the i-th injectable parameter"),
            "the message must state the positional rule, as Python's does");
        assertTrue(message.contains("declare exactly 1 entry"), message);
        assertTrue(message.contains("(no injectable parameter — dropped)"),
            "the binder's own pairing table must be part of the diagnostic");
        assertTrue(message.contains("MCP_MESH_STRICT_DI=true"),
            "the non-strict message must point at the knob that hardens it");
    }

    @Test
    @DisplayName("More slots than dependencies: WARN naming the null-injected surplus")
    void surplusParametersWarnByDefault() {
        MeshPositionalBinder.Binding binding = bind("tooManyParams", List.of(0, 1, 2), null,
            List.of("cap_a"), 1);

        String message = MeshDiValidator.checkArity("@MeshTool", binding, binding.slots().size(), binding.slots().size(), false);

        assertNotNull(message);
        assertTrue(message.contains("declares 1 dependency"), message);
        assertTrue(message.contains("has 3 dependency-backed injectable parameters"), message);
        assertTrue(message.contains("injected null"), message);
        assertTrue(message.contains("declare exactly 3 entries"), message);
    }

    @Test
    @DisplayName("MCP_MESH_STRICT_DI: the same diagnostic becomes a boot failure")
    void strictModeFailsBoot() {
        MeshPositionalBinder.Binding binding = bind("tooFewParams", List.of(1), null,
            List.of("cap_a", "cap_b"), 2);

        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> MeshDiValidator.checkArity("@MeshTool", binding, binding.slots().size(), binding.slots().size(), true));

        assertTrue(e.getMessage().contains("declares 2 dependencies"), e.getMessage());
        assertTrue(e.getMessage().contains("has 1 dependency-backed injectable parameter"), e.getMessage());
        assertTrue(!e.getMessage().contains("Set MCP_MESH_STRICT_DI=true"),
            "the strict message must not tell the user to enable what is already enabled");
    }

    @Test
    @DisplayName("The declaration site is named so a multi-site agent knows where to look")
    void siteLabelIsCarriedIntoTheMessage() {
        MeshPositionalBinder.Binding binding = bind("tooFewParams", List.of(1), null,
            List.of("cap_a", "cap_b"), 2);

        String message = MeshDiValidator.checkArity("@MeshTool", binding, binding.slots().size(), binding.slots().size(), false);
        assertTrue(message.startsWith("@MeshTool io.mcpmesh.spring.MeshDiValidatorTest$Shapes"
            + ".tooFewParams("), message);
    }

    @Test
    @DisplayName("Default posture is permissive: MCP_MESH_STRICT_DI is off unless set")
    void strictIsOptIn() {
        // The suite does not set the variable; DI stays soft-fail by default.
        assertEquals(System.getenv(MeshDiValidator.STRICT_DI_ENV) != null
                && List.of("1", "true", "yes")
                    .contains(System.getenv(MeshDiValidator.STRICT_DI_ENV).trim().toLowerCase()),
            MeshDiValidator.strictDiEnabled());
    }

    // ─────────────────────────────────────────────────────────────────
    // At the real call site: MeshToolWrapper
    // ─────────────────────────────────────────────────────────────────

    @SuppressWarnings("unused")
    static class Tools {
        @MeshTool(capability = "produce_report", task = true)
        public String producer(@io.mcpmesh.Param("x") String x, MeshJob job) {
            return "";
        }

        @MeshTool(capability = "consume", dependencies = @Selector(capability = "remote_task"))
        public String consumer(@io.mcpmesh.Param("x") String x, MeshJob job) {
            return "";
        }

        @MeshTool(capability = "mismatched",
            dependencies = {@Selector(capability = "a"), @Selector(capability = "b")})
        public String mismatched(@io.mcpmesh.Param("x") String x, McpMeshTool only) {
            return "";
        }

        /** The skew shape: a producer that DOES declare at the job slot's index. */
        @MeshTool(capability = "skew", task = true,
            dependencies = {@Selector(capability = "job_cap"), @Selector(capability = "db_cap")})
        public String skewProducer(MeshJob job, McpMeshTool db) {
            return "";
        }
    }

    @Test
    @DisplayName("Real wrapper: a task=true producer with a MeshJob parameter warns about nothing")
    void wrapperDoesNotWarnForTaskProducers() {
        assertEquals(List.of(), warningsFromWrapper("producer", List.of(), true));
    }

    @Test
    @DisplayName("Real wrapper: a producer that DOES declare at the job slot's index is also silent")
    void wrapperDoesNotWarnForSkewedProducers() {
        assertEquals(List.of(),
            warningsFromWrapper("skewProducer", List.of("job_cap", "db_cap"), true));
    }

    @Test
    @DisplayName("Real wrapper: a consumer MeshJob slot backed by its declared dependency is silent")
    void wrapperDoesNotWarnForWiredConsumers() {
        assertEquals(List.of(), warningsFromWrapper("consumer", List.of("remote_task"), false));
    }

    @Test
    @DisplayName("Real wrapper: a genuine mismatch still warns, and the wrapper still builds")
    void wrapperWarnsButStillBuilds() {
        List<String> warnings = warningsFromWrapper("mismatched", List.of("a", "b"), false);

        assertEquals(1, warnings.size(), warnings.toString());
        assertTrue(warnings.get(0).contains("declares 2 dependencies"), warnings.get(0));
        assertTrue(warnings.get(0).contains("has 1 dependency-backed injectable parameter"),
            warnings.get(0));
    }

    /** Build a real {@link MeshToolWrapper} and collect what the validator logged. */
    private static List<String> warningsFromWrapper(
            String methodName, List<String> dependencies, boolean task) {

        Method method = null;
        for (Method m : Tools.class.getDeclaredMethods()) {
            if (m.getName().equals(methodName)) {
                method = m;
            }
        }
        if (method == null) {
            throw new AssertionError("No such tool: " + methodName);
        }

        ch.qos.logback.classic.Logger logger = (ch.qos.logback.classic.Logger)
            org.slf4j.LoggerFactory.getLogger(MeshDiValidator.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            new MeshToolWrapper(
                "test." + methodName,
                "cap",
                "",
                new Tools(),
                method,
                dependencies,
                JsonMapper.builder().build(),
                task,
                new Class[0],
                List.of());
        } finally {
            logger.detachAppender(appender);
        }
        return appender.list.stream().map(ILoggingEvent::getFormattedMessage).toList();
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    private static MeshPositionalBinder.Binding bind(
            String methodName,
            List<Integer> proxyPositions,
            Integer jobPosition,
            List<String> capabilities,
            int pairableDepCount) {

        return MeshPositionalBinder.bind(
            methodOf(methodName),
            MeshPositionalBinder.slots(proxyPositions, jobPosition),
            capabilities,
            pairableDepCount);
    }

    private static Method methodOf(String name) {
        for (Method m : Shapes.class.getDeclaredMethods()) {
            if (m.getName().equals(name)) {
                return m;
            }
        }
        throw new AssertionError("No such shape: " + name);
    }
}
