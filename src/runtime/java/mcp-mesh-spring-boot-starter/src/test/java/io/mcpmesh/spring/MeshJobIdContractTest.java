package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.spring.tracing.TracingFilter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Issue #1570 — the cross-runtime {@code x-mesh-job-id} contract.
 *
 * <p>{@code x-mesh-job-id} is the push-mode dispatch DISCRIMINATOR. Java used
 * to put it on the propagate allowlist, which is a single switch driving BOTH
 * the inbound capture and the outbound forward — so making inbound dispatch
 * work also made every outbound call forward it, and a nested same-instance
 * {@code task=true} call self-dispatched as the CALLER's job (owner + epoch
 * match) and auto-completed it with the wrong result. That is the hazard
 * {@code TraceContext.callingJobHeaders()}' own javadoc warns about.
 *
 * <p>The two concerns are now separate: the dispatch trio is captured from the
 * RAW inbound request into its own store, and is stripped from every outbound
 * header map.
 */
class MeshJobIdContractTest {

    @AfterEach
    void clearContext() {
        TraceContext.clearPropagatedHeaders();
        TraceContext.clearDispatchHeaders();
    }

    // ---- allowlist ---------------------------------------------------------

    @Test
    void dispatchTrioIsNotOnThePropagateAllowlist() {
        for (String name : TraceContext.DISPATCH_HEADERS) {
            assertFalse(TraceContext.matchesPropagateHeader(name),
                name + " must never be allowlisted — the allowlist drives the OUTBOUND "
                    + "forward, and forwarding the discriminator self-dispatches nested calls");
        }
        // The calling-identity carrier is unaffected.
        assertTrue(TraceContext.matchesPropagateHeader("x-mesh-calling-job-id"));
        assertTrue(TraceContext.matchesPropagateHeader("x-mesh-calling-claim-epoch"));
    }

    @Test
    void stripDispatchHeaders_removesTheTrioCaseInsensitively() {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("X-Mesh-Job-Id", "job-leaked");
        headers.put("x-mesh-claim-epoch", "9");
        headers.put("x-mesh-recv-cursor", "{\"work\":4}");
        headers.put("x-mesh-timeout", "30");
        headers.put("x-mesh-calling-job-id", "job-caller");

        TraceContext.stripDispatchHeaders(headers);

        assertFalse(headers.containsKey("X-Mesh-Job-Id"));
        assertFalse(headers.containsKey("x-mesh-claim-epoch"));
        assertFalse(headers.containsKey("x-mesh-recv-cursor"));
        assertEquals("30", headers.get("x-mesh-timeout"),
            "a genuinely propagated header is untouched");
        assertEquals("job-caller", headers.get("x-mesh-calling-job-id"));
    }

    // ---- inbound capture ---------------------------------------------------

    @Test
    void tracingFilterCapturesTheTrioFromTheRawRequest() throws Exception {
        // TracingFilter holds the HttpServletRequest, so the raw header read is
        // reachable there without any new plumbing.
        Map<String, String> inbound = new LinkedHashMap<>();
        inbound.put("X-Mesh-Job-Id", "job-inbound-1570");
        inbound.put("X-Mesh-Claim-Epoch", "7");
        inbound.put("X-Mesh-Timeout", "30");

        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeaderNames()).thenAnswer(inv ->
            Collections.enumeration(inbound.keySet()));
        when(request.getHeader(any(String.class))).thenAnswer(inv -> {
            String name = inv.getArgument(0);
            for (Map.Entry<String, String> e : inbound.entrySet()) {
                if (e.getKey().equalsIgnoreCase(name)) return e.getValue();
            }
            return null;
        });
        HttpServletResponse response = mock(HttpServletResponse.class);

        AtomicReference<Map<String, String>> dispatchSeen = new AtomicReference<>();
        AtomicReference<Map<String, String>> propagatedSeen = new AtomicReference<>();
        FilterChain chain = (req, res) -> {
            dispatchSeen.set(new LinkedHashMap<>(TraceContext.getDispatchHeaders()));
            propagatedSeen.set(new LinkedHashMap<>(TraceContext.getPropagatedHeaders()));
        };

        new TracingFilter().doFilter(request, response, chain);

        assertEquals("job-inbound-1570", dispatchSeen.get().get("x-mesh-job-id"),
            "the dispatch gate must see the raw inbound job id");
        assertEquals("7", dispatchSeen.get().get("x-mesh-claim-epoch"),
            "the claim epoch was previously read off the allowlist-filtered map, "
                + "where it could never appear");
        assertFalse(propagatedSeen.get().containsKey("x-mesh-job-id"),
            "the propagated map is what rides outbound — it must not carry the discriminator");
        assertEquals("30", propagatedSeen.get().get("x-mesh-timeout"));
    }

    // ---- dispatch gate -----------------------------------------------------

    public static class TaskProbe {
        final AtomicReference<String> jobScope = new AtomicReference<>();

        @MeshTool(capability = "probe", task = true)
        public String probe(@Param("input") String input) {
            io.mcpmesh.JobContext.Snapshot snap = io.mcpmesh.JobContext.current();
            jobScope.set(snap == null ? null : snap.jobId);
            return "ok:" + input;
        }
    }

    private static MeshToolWrapper taskProbeWrapper(TaskProbe bean) throws Exception {
        Method m = TaskProbe.class.getMethod("probe", String.class);
        return new MeshToolWrapper(
            "TaskProbe.probe", "probe", "test", bean, m,
            List.of(), JsonMapper.builder().build(), true);
    }

    @Test
    void dispatchGateReadsTheRawStore_notThePropagatedOne() throws Exception {
        TaskProbe bean = new TaskProbe();
        MeshToolWrapper wrapper = taskProbeWrapper(bean);

        TraceContext.setDispatchHeaders(Map.of("x-mesh-job-id", "job-dispatch"));
        Object result = wrapper.invoke(Map.of("input", "x"));

        assertEquals("ok:x", result);
        assertEquals("job-dispatch", bean.jobScope.get(),
            "a raw inbound job id must bind the JobContext for the handler");
    }

    @Test
    void aStalePropagatedJobIdDoesNotDispatch() throws Exception {
        // Nothing emits x-mesh-job-id outbound any more, but an operator who
        // widens MCP_MESH_PROPAGATE_HEADERS must not be able to reopen the
        // self-dispatch hazard: the gate does not consult this map at all.
        TaskProbe bean = new TaskProbe();
        MeshToolWrapper wrapper = taskProbeWrapper(bean);

        TraceContext.setPropagatedHeaders(Map.of("x-mesh-job-id", "job-caller"));
        Object result = wrapper.invoke(Map.of("input", "x"));

        assertEquals("ok:x", result);
        assertNull(bean.jobScope.get(),
            "an inherited/propagated job id must NOT dispatch — that is the "
                + "self-dispatch hazard (the callee would auto-complete the caller's row)");
    }

    // ---- version-skew guard -----------------------------------------------

    @Test
    void aJobIdArrivingWithCallingIdentityIsRefused() throws Exception {
        // A pre-3.8 caller DID forward its job id, and only ever from inside a
        // bound job context — which seeds x-mesh-calling-job-id on the same
        // request. The pair together is a leak, not a dispatch: honouring it
        // would bind this handler to the old caller's row for the length of
        // the skew window, which is precisely the corruption being removed.
        TaskProbe bean = new TaskProbe();
        MeshToolWrapper wrapper = taskProbeWrapper(bean);

        TraceContext.setDispatchHeaders(Map.of("x-mesh-job-id", "job-caller"));
        TraceContext.setPropagatedHeaders(Map.of("x-mesh-calling-job-id", "job-caller"));
        Object result = wrapper.invoke(Map.of("input", "x"));

        assertEquals("ok:x", result);
        assertNull(bean.jobScope.get(),
            "an old caller's leaked job id must not bind this handler to its row");
    }

    @Test
    void aGenuinePushDispatchCarriesNoCallingIdentityAndStillDispatches() throws Exception {
        TaskProbe bean = new TaskProbe();
        MeshToolWrapper wrapper = taskProbeWrapper(bean);

        TraceContext.setDispatchHeaders(Map.of("x-mesh-job-id", "job-push"));
        wrapper.invoke(Map.of("input", "x"));

        assertEquals("job-push", bean.jobScope.get(),
            "the skew guard must not cost a real push-mode dispatch");
    }

    @Test
    void rawMeshHeadersArgumentChannelAlsoFeedsTheGate() throws Exception {
        // Non-Java callers pass headers in the _mesh_headers argument because
        // FastMCP hides HTTP headers; the raw read must cover that channel too.
        TaskProbe bean = new TaskProbe();
        MeshToolWrapper wrapper = taskProbeWrapper(bean);

        Map<String, Object> args = new LinkedHashMap<>();
        args.put("input", "x");
        args.put("_mesh_headers", Map.of("x-mesh-job-id", "job-from-args"));

        Object result = wrapper.invoke(args);

        assertEquals("ok:x", result);
        assertEquals("job-from-args", bean.jobScope.get());
        assertFalse(TraceContext.getPropagatedHeaders().containsKey("x-mesh-job-id"),
            "the args channel must not smuggle the discriminator into the outbound map");
    }
}
