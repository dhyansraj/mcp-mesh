package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.Param;
import io.mcpmesh.MeshTool;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.types.MeshSupersededException;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1278 — provider emit: a handler that rejects a superseded caller by
 * throwing {@link MeshSupersededException} produces the reserved
 * {@code {"error":"claim_superseded"}} {@code isError} tool result (same carrier
 * as the {@code dependency_unavailable} refusal), with {@code detail} present
 * only when supplied. Mirrors {@link MeshToolWrapperRequiredDepGuardTest}.
 */
class MeshToolWrapperSupersededTest {

    /** Provider that throws the supersession signal (app-decided). */
    public static class SupersedingBean {
        @MeshTool(capability = "mutate")
        public Object mutate(@Param("detail") String detail) {
            // The app decides supersession (e.g. via MeshCallContext.callingJob());
            // an empty/absent detail exercises the no-detail envelope.
            throw new MeshSupersededException(
                (detail == null || detail.isEmpty()) ? null : detail);
        }

        @MeshTool(capability = "mutate_async")
        public CompletableFuture<Object> mutateAsync(@Param("detail") String detail) {
            // Async handler: the future completes exceptionally with the signal.
            CompletableFuture<Object> f = new CompletableFuture<>();
            f.completeExceptionally(new MeshSupersededException(
                (detail == null || detail.isEmpty()) ? null : detail));
            return f;
        }
    }

    private static MeshToolWrapper wrapperFor(String methodName) throws Exception {
        SupersedingBean bean = new SupersedingBean();
        Method m = SupersedingBean.class.getMethod(methodName, String.class);
        return new MeshToolWrapper(
            "SupersedingBean." + methodName,
            m.getAnnotation(MeshTool.class).capability(),
            "test",
            bean,
            m,
            List.of(),
            JsonMapper.builder().build());
    }

    private static String textOf(Object result) {
        assertInstanceOf(CallToolResult.class, result,
            "the supersession refusal must be a structured tool result");
        CallToolResult ctr = (CallToolResult) result;
        assertEquals(Boolean.TRUE, ctr.isError(),
            "the refusal must be an isError result (contract-classified, not app success)");
        return ((TextContent) ctr.content().get(0)).text();
    }

    @Test
    void handlerThrows_withDetail_emitsReservedEnvelopeWithDetail() throws Exception {
        MeshToolWrapper wrapper = wrapperFor("mutate");

        Object result = wrapper.invoke(Map.of("detail", "d"));

        assertEquals("{\"error\":\"claim_superseded\",\"detail\":\"d\"}", textOf(result),
            "the envelope must carry the detail key when supplied");
    }

    @Test
    void handlerThrows_noDetail_emitsReservedEnvelope_detailOmitted() throws Exception {
        MeshToolWrapper wrapper = wrapperFor("mutate");

        Object result = wrapper.invoke(Map.of("detail", ""));

        assertEquals("{\"error\":\"claim_superseded\"}", textOf(result),
            "the detail key must be OMITTED (not null) when absent");
    }

    @Test
    void asyncHandlerThrows_withDetail_emitsReservedEnvelopeWithDetail() throws Exception {
        MeshToolWrapper wrapper = wrapperFor("mutateAsync");

        Object result = wrapper.invoke(Map.of("detail", "async-stale"));

        assertEquals("{\"error\":\"claim_superseded\",\"detail\":\"async-stale\"}", textOf(result),
            "an async handler's supersession signal must emit the same reserved envelope");
    }

    @Test
    void asyncHandlerThrows_noDetail_emitsReservedEnvelope_detailOmitted() throws Exception {
        MeshToolWrapper wrapper = wrapperFor("mutateAsync");

        Object result = wrapper.invoke(Map.of("detail", ""));

        assertEquals("{\"error\":\"claim_superseded\"}", textOf(result));
    }

    // ---- job-dispatch path (issue #1278 review gap 1) -----------------------

    /** task=true provider (the PRIMARY supersession scenario) with a MeshJob slot. */
    public static class SupersedingJobBean {
        @MeshTool(capability = "job_mutate", task = true)
        public Object jobMutate(@Param("detail") String detail, MeshJob job) {
            // A dispatched job provider inspects MeshCallContext.callingJob() and
            // rejects a superseded caller. Modeled here by throwing directly.
            throw new MeshSupersededException(
                (detail == null || detail.isEmpty()) ? null : detail);
        }
    }

    @AfterEach
    void reset() {
        MeshSettleState.resetForTests();
        TraceContext.clearPropagatedHeaders();
    }

    @Test
    void jobDispatch_handlerThrows_emitsReservedEnvelope() throws Exception {
        // A task=true tool invoked WITH an X-Mesh-Job-Id header routes through
        // dispatchAsJob → invokeNoController (instanceId/registryUrl are NOT wired,
        // so canInjectController is false). The supersession signal must STILL
        // emit the reserved envelope — the job-dispatch invocation paths convert
        // it exactly like the non-job branch.
        MeshSettleState.resetForTests(); // settled — no grace window
        SupersedingJobBean bean = new SupersedingJobBean();
        Method m = SupersedingJobBean.class.getMethod("jobMutate", String.class, MeshJob.class);
        MeshToolWrapper wrapper = new MeshToolWrapper(
            "SupersedingJobBean.jobMutate", "job_mutate", "test", bean, m,
            List.of(), JsonMapper.builder().build(), true);

        TraceContext.setPropagatedHeaders(Map.of("x-mesh-job-id", "job-xyz"));
        Object result = wrapper.invoke(Map.of("detail", "job-stale"));

        assertEquals("{\"error\":\"claim_superseded\",\"detail\":\"job-stale\"}", textOf(result),
            "a superseded rejection on the job-dispatch path must emit the reserved envelope");
    }
}
