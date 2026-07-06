package io.mcpmesh.spring;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshServiceUnavailableException;
import io.mcpmesh.types.MeshToolUnavailableException;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * RFC #1280 phase 2: {@link McpMeshService} interface as a {@code @MeshTool}
 * PARAMETER. One view param expands to N ordinary dependency edges ON THAT
 * TOOL, positionally paired AFTER the explicit {@code @Selector} deps.
 *
 * <p>Unit-tests the below-FFI machinery directly (wrapper construction +
 * updateDependency + invoke), mirroring {@link MeshToolWrapperRequiredDepGuardTest}.
 */
class McpMeshServiceToolParamTest {

    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    // ---- Fixtures -----------------------------------------------------------

    @McpMeshService
    public interface MediaService {
        @Selector(capability = "media.caption")
        String caption(@Param("id") String id);

        @Selector(capability = "media.transcribe")
        String transcribe(@Param("id") String id);

        @Selector(capability = "media.thumbnail")
        String thumbnail(@Param("id") String id);
    }

    /** Records the params map it was called with; returns "RESP:"+capability. */
    static class ViewStub implements McpMeshTool<String> {
        final String cap;
        final boolean available;
        volatile Map<String, Object> lastParams;

        ViewStub(String cap, boolean available) {
            this.cap = cap;
            this.available = available;
        }

        @Override public String call() { return "RESP:" + cap; }
        @Override public String call(Map<String, Object> params) { lastParams = params; return "RESP:" + cap; }
        @Override public String call(Object... args) { return "RESP:" + cap; }
        @Override public CompletableFuture<String> callAsync() { return CompletableFuture.completedFuture("RESP:" + cap); }
        @Override public CompletableFuture<String> callAsync(Map<String, Object> params) { return CompletableFuture.completedFuture("RESP:" + cap); }
        @Override public CompletableFuture<String> callAsync(Object... keyValuePairs) { return CompletableFuture.completedFuture("RESP:" + cap); }
        @Override public String getCapability() { return cap; }
        @Override public String getEndpoint() { return "http://stub"; }
        @Override public String getFunctionName() { return cap; }
        @Override public boolean isAvailable() { return available; }
    }

    public static class MediaProcessor {
        @MeshTool(capability = "process_media",
            dependencies = @Selector(capability = "audit_log"))
        public Map<String, Object> processMedia(
                @Param("assetId") String assetId,
                McpMeshTool<String> auditLog,
                MediaService media) {
            Map<String, Object> out = new java.util.LinkedHashMap<>();
            out.put("caption", media.caption(assetId));
            out.put("transcribe", media.transcribe(assetId));
            return out;
        }
    }

    private static Method processMediaMethod() throws Exception {
        return MediaProcessor.class.getMethod("processMedia",
            String.class, McpMeshTool.class, MediaService.class);
    }

    private static MeshToolWrapper mediaWrapper(MediaProcessor bean) throws Exception {
        Method m = processMediaMethod();
        MeshToolWrapper w = new MeshToolWrapper(
            "MediaProcessor.processMedia", "process_media", "test", bean, m,
            List.of("audit_log"), JsonMapper.builder().build(), false, null,
            McpMeshServiceToolSupport.analyzeViewParams(m));
        w.setDependencyRequired(List.of(false)); // audit_log optional
        return w;
    }

    // ---- Detection + expansion order ----------------------------------------

    @Test
    void expansion_explicitFirst_thenViewEdgesNameSorted() throws Exception {
        MeshToolWrapper w = mediaWrapper(new MediaProcessor());
        // Explicit dep FIRST, then the view's methods in method-name order
        // (caption, thumbnail, transcribe).
        assertEquals(List.of("audit_log", "media.caption", "media.thumbnail", "media.transcribe"),
            w.getDependencyNames());
        // Return types: audit_log McpMeshTool<String>, each view edge = String.
        assertEquals(String.class, w.getDependencyReturnType(0));
        assertEquals(String.class, w.getDependencyReturnType(1));
        assertEquals(String.class, w.getDependencyReturnType(3));
        // Every McpMeshTool slot AND view edge gets a funcId:dep_N settle key.
        assertEquals(List.of(0, 1, 2, 3), w.getSettleDepIndices());
    }

    // ---- Event routing to the right per-method proxy ------------------------

    @Test
    void updateDependency_routesViewEdgeToCorrectMethodProxy() throws Exception {
        MediaProcessor bean = new MediaProcessor();
        MeshToolWrapper w = mediaWrapper(bean);

        // caption = declared index 1, transcribe = declared index 3.
        ViewStub caption = new ViewStub("media.caption", true);
        ViewStub transcribe = new ViewStub("media.transcribe", true);
        w.updateDependency(1, caption);
        w.updateDependency(3, transcribe);

        @SuppressWarnings("unchecked")
        Map<String, Object> out = (Map<String, Object>) w.invoke(Map.of("assetId", "asset-7"));

        assertEquals("RESP:media.caption", out.get("caption"));
        assertEquals("RESP:media.transcribe", out.get("transcribe"));
        // The @Param("id") facade method built a params map from the arg.
        assertEquals(Map.of("id", "asset-7"), caption.lastParams);
    }

    // ---- Skew: MeshJob + explicit dep + view param in one signature ---------

    public static class SkewProcessor {
        @MeshTool(capability = "skew_tool", task = true, dependencies = {
            @Selector(capability = "job_cap"),
            @Selector(capability = "db_cap")
        })
        public Map<String, Object> skew(MeshJob job, McpMeshTool<String> db, MediaService media) {
            Map<String, Object> out = new java.util.LinkedHashMap<>();
            out.put("caption", media.caption("x"));
            return out;
        }
    }

    @Test
    void skew_jobPlusExplicitPlusView_indicesAlign() throws Exception {
        SkewProcessor bean = new SkewProcessor();
        Method m = SkewProcessor.class.getMethod("skew",
            MeshJob.class, McpMeshTool.class, MediaService.class);
        MeshToolWrapper w = new MeshToolWrapper(
            "SkewProcessor.skew", "skew_tool", "test", bean, m,
            List.of("job_cap", "db_cap"), JsonMapper.builder().build(), true, null,
            McpMeshServiceToolSupport.analyzeViewParams(m));

        // Declared list: job_cap(0), db_cap(1), then view edges 2..4.
        assertEquals(List.of("job_cap", "db_cap", "media.caption", "media.thumbnail", "media.transcribe"),
            w.getDependencyNames());
        // db_cap is declared index 1 but McpMeshTool slot 0 (MeshJob consumes
        // declared index 0). View edges never collide with that slot.
        assertEquals(String.class, w.getDependencyReturnType(1)); // db
        assertEquals(String.class, w.getDependencyReturnType(2)); // caption
        // MeshJob-backed dep (index 0) gets NO settle key; db + view edges do.
        assertEquals(List.of(1, 2, 3, 4), w.getSettleDepIndices());

        // Route a view edge (index 2) and a db-slot proxy (index 1); the facade
        // method must reach the VIEW proxy, not the db slot.
        w.updateDependency(1, new ViewStub("db_cap", true));
        w.updateDependency(2, new ViewStub("media.caption", true));
        @SuppressWarnings("unchecked")
        Map<String, Object> out = (Map<String, Object>) w.invoke(Map.of());
        assertEquals("RESP:media.caption", out.get("caption"));
    }

    // ---- Required view edge → pre-invoke refusal ----------------------------

    @McpMeshService
    public interface ReqView {
        @Selector(capability = "req.a", required = true)
        String a(@Param("id") String id);

        @Selector(capability = "req.b")
        String b(@Param("id") String id);
    }

    public static class ReqProcessor {
        final java.util.concurrent.atomic.AtomicBoolean handlerRan =
            new java.util.concurrent.atomic.AtomicBoolean(false);

        @MeshTool(capability = "req_tool")
        public Map<String, Object> run(@Param("x") String x, ReqView view) {
            handlerRan.set(true);
            Map<String, Object> out = new java.util.LinkedHashMap<>();
            out.put("a", view.a(x));
            return out;
        }
    }

    private static MeshToolWrapper reqWrapper(ReqProcessor bean) throws Exception {
        Method m = ReqProcessor.class.getMethod("run", String.class, ReqView.class);
        MeshToolWrapper w = new MeshToolWrapper(
            "ReqProcessor.run", "req_tool", "test", bean, m,
            List.of(), JsonMapper.builder().build(), false, null,
            McpMeshServiceToolSupport.analyzeViewParams(m));
        w.setDependencyRequired(List.of());
        return w;
    }

    @Test
    void requiredViewEdge_participatesInFirstUnresolvedRequired() throws Exception {
        MeshToolWrapper w = reqWrapper(new ReqProcessor());
        // req.a is required=true and unresolved → the tool's required-dep guard
        // names it (declared index 0: a < b by method name).
        assertEquals("req.a", w.firstUnresolvedRequiredDependency());

        Object refusal = w.invoke(Map.of("x", "v"));
        assertInstanceOf(CallToolResult.class, refusal);
        assertEquals(Boolean.TRUE, ((CallToolResult) refusal).isError());
        String text = ((TextContent) ((CallToolResult) refusal).content().get(0)).text();
        assertTrue(text.contains("\"capability\":\"req.a\""), text);

        // Resolve the required edge → guard clears, handler runs.
        w.updateDependency(0, new ViewStub("req.a", true));
        assertNull(w.firstUnresolvedRequiredDependency());
        @SuppressWarnings("unchecked")
        Map<String, Object> out = (Map<String, Object>) w.invoke(Map.of("x", "v"));
        assertEquals("RESP:req.a", out.get("a"));
    }

    // ---- minAvailable floor via a tool view param ---------------------------

    @McpMeshService(minAvailable = 2)
    public interface FloorView {
        @Selector(capability = "fl.a") String a(@Param("id") String id);
        @Selector(capability = "fl.b") String b(@Param("id") String id);
        @Selector(capability = "fl.c") String c(@Param("id") String id);
    }

    public static class FloorProcessor {
        @MeshTool(capability = "floor_tool")
        public String run(@Param("x") String x, FloorView view) {
            return view.a(x);
        }
    }

    @Test
    void floorViaToolParam_belowFloorThrows_atFloorWorks() throws Exception {
        FloorProcessor bean = new FloorProcessor();
        Method m = FloorProcessor.class.getMethod("run", String.class, FloorView.class);
        MeshToolWrapper w = new MeshToolWrapper(
            "FloorProcessor.run", "floor_tool", "test", bean, m,
            List.of(), JsonMapper.builder().build(), false, null,
            McpMeshServiceToolSupport.analyzeViewParams(m));
        w.setDependencyRequired(List.of());

        // Below floor (0/3) → the facade method throws the service-level error,
        // which propagates out of invoke.
        Exception below = assertThrows(Exception.class, () -> w.invoke(Map.of("x", "v")));
        assertInstanceOf(MeshServiceUnavailableException.class, unwrap(below));

        // Resolve 2/3 (fl.a + fl.b) → floor satisfied; fl.a resolved so a() works.
        w.updateDependency(0, new ViewStub("fl.a", true)); // fl.a = index 0
        w.updateDependency(1, new ViewStub("fl.b", true)); // fl.b = index 1
        assertEquals("RESP:fl.a", w.invoke(Map.of("x", "v")));
    }

    private static Throwable unwrap(Throwable t) {
        return (t.getCause() != null && t instanceof RuntimeException && t.getCause() != t)
            ? t.getCause() : t;
    }

    // ---- @Param on a view param → boot-fail ---------------------------------

    public static class BadViewParamBean {
        @MeshTool(capability = "bad_tool")
        public String run(@Param("x") String x, @Param("media") MediaService media) {
            return "x";
        }
    }

    @Test
    void paramOnViewParam_bootFails() throws Exception {
        Method m = BadViewParamBean.class.getMethod("run", String.class, MediaService.class);
        IllegalStateException ex = assertThrows(IllegalStateException.class,
            () -> McpMeshServiceToolSupport.analyzeViewParams(m));
        assertTrue(ex.getMessage().contains("must NOT carry"), ex.getMessage());
    }

    // ---- Wire serialization of the expanded tool DependencySpec list --------

    @Test
    void wireSpec_containsExplicitThenViewEdges_requiredSerialization() throws Exception {
        MeshToolRegistry reg = new MeshToolRegistry();
        Method media = processMediaMethod();
        reg.registerTool(new MediaProcessor(), media, media.getAnnotation(MeshTool.class));
        Method req = ReqProcessor.class.getMethod("run", String.class, ReqView.class);
        reg.registerTool(new ReqProcessor(), req, req.getAnnotation(MeshTool.class));

        AgentSpec.ToolSpec mediaSpec = reg.getToolSpecs().stream()
            .filter(t -> "process_media".equals(t.getCapability())).findFirst().orElseThrow();
        assertEquals(List.of("audit_log", "media.caption", "media.thumbnail", "media.transcribe"),
            mediaSpec.getDependencies().stream().map(AgentSpec.DependencySpec::getCapability).toList());

        AgentSpec.ToolSpec reqSpec = reg.getToolSpecs().stream()
            .filter(t -> "req_tool".equals(t.getCapability())).findFirst().orElseThrow();
        AgentSpec.DependencySpec reqA = reqSpec.getDependencies().stream()
            .filter(d -> "req.a".equals(d.getCapability())).findFirst().orElseThrow();
        AgentSpec.DependencySpec reqB = reqSpec.getDependencies().stream()
            .filter(d -> "req.b".equals(d.getCapability())).findFirst().orElseThrow();
        assertTrue(reqA.isRequired());
        assertFalse(reqB.isRequired());
        assertTrue(MAPPER.writeValueAsString(reqA).contains("\"required\":true"));
        assertFalse(MAPPER.writeValueAsString(reqB).contains("required"));
    }

    // ---- MED-1: near-miss view params → dedicated boot-fail ------------------

    @McpMeshService
    public static class AnnotatedClassView {
        // A CLASS annotated @McpMeshService — not a valid service view.
    }

    @McpMeshService
    public interface AnnotatedBaseView {
        @Selector(capability = "base.x")
        String x(@Param("id") String id);
    }

    public interface SubView extends AnnotatedBaseView {
        // Inherits @McpMeshService but does NOT carry it directly.
    }

    public static class ClassParamBean {
        @MeshTool(capability = "cp_tool")
        public String run(@Param("x") String x, AnnotatedClassView bad) {
            return "x";
        }
    }

    public static class SubIfaceParamBean {
        @MeshTool(capability = "si_tool")
        public String run(@Param("x") String x, SubView bad) {
            return "x";
        }
    }

    private static MeshToolWrapper wrapperFor(Object bean, String funcId, String cap, Method m,
                                              List<String> explicit) {
        return new MeshToolWrapper(funcId, cap, "test", bean, m, explicit,
            JsonMapper.builder().build(), false, null,
            McpMeshServiceToolSupport.analyzeViewParams(m));
    }

    @Test
    void nearMiss_classAnnotatedAsView_rewordedBootFail() throws Exception {
        // A CLASS annotated @McpMeshService is the producer path, NOT a valid
        // view param — the reworded message points that out.
        Method m = ClassParamBean.class.getMethod("run", String.class, AnnotatedClassView.class);
        IllegalStateException ex = assertThrows(IllegalStateException.class,
            () -> wrapperFor(new ClassParamBean(), "ClassParamBean.run", "cp_tool", m, List.of()));
        assertTrue(ex.getMessage().contains("view parameters must be @McpMeshService interfaces"),
            ex.getMessage());
        assertTrue(ex.getMessage().contains("publishes methods as tools (producer side)"), ex.getMessage());
        assertTrue(ex.getMessage().contains("carries or inherits @McpMeshService but is not an interface"),
            ex.getMessage());
        assertTrue(ex.getMessage().contains(ClassParamBean.class.getName()), ex.getMessage());
        assertTrue(ex.getMessage().contains(AnnotatedClassView.class.getName()),
            "message names the resolved parameter type: " + ex.getMessage());
    }

    @Test
    void subInterfaceInheritsAnnotation_isAValidViewParam() throws Exception {
        // Phase-2 cleanup 7a: a sub-interface that INHERITS @McpMeshService is a
        // valid view param — its inherited method edge is published on the tool.
        SubIfaceParamBean bean = new SubIfaceParamBean();
        Method m = SubIfaceParamBean.class.getMethod("run", String.class, SubView.class);
        MeshToolWrapper w = wrapperFor(bean, "SubIfaceParamBean.run", "si_tool", m, List.of());
        assertEquals(List.of("base.x"), w.getDependencyNames());
        assertEquals(String.class, w.getDependencyReturnType(0));
    }

    // ---- HIGH-1b + item-9: generic narrowing / grandparent / diamond params --

    public record GItem(String id) {
    }

    @McpMeshService
    public interface GenBase<T> {
        @Selector(capability = "gen.item")
        T get(@Param("id") String id);
    }

    public interface ItemSub extends GenBase<GItem> {
    }

    public static class GenParamBean {
        @MeshTool(capability = "gen_tool")
        public String run(@Param("x") String x, ItemSub view) {
            return x;
        }
    }

    @Test
    void genericParentNarrowedSubAsParam_getsConcreteTyping() throws Exception {
        // A generic annotated parent (T) narrowed by a sub used as a view param
        // resolves to the CONCRETE type (Item), not Object — the concrete wins
        // the proxy typing (HIGH-1b: Object is non-conflicting/dynamic).
        Method m = GenParamBean.class.getMethod("run", String.class, ItemSub.class);
        MeshToolWrapper w = wrapperFor(new GenParamBean(), "GenParamBean.run", "gen_tool", m, List.of());
        assertEquals(List.of("gen.item"), w.getDependencyNames());
        assertEquals(GItem.class, w.getDependencyReturnType(0));
    }

    public record CX(String x) {
    }

    public record CY(int y) {
    }

    @McpMeshService
    public interface TwoConcreteView {
        @Selector(capability = "cc")
        CX a(@Param("id") String id);

        @Selector(capability = "cc")
        CY b(@Param("id") String id);
    }

    public static class TwoConcreteBean {
        @MeshTool(capability = "cc_tool")
        public String run(@Param("x") String x, TwoConcreteView view) {
            return x;
        }
    }

    @Test
    void twoDifferentConcreteTypesForSameCapability_bootFails() throws Exception {
        Method m = TwoConcreteBean.class.getMethod("run", String.class, TwoConcreteView.class);
        IllegalStateException ex = assertThrows(IllegalStateException.class,
            () -> McpMeshServiceToolSupport.analyzeViewParams(m));
        assertTrue(ex.getMessage().contains("conflicting resolved"), ex.getMessage());
        assertTrue(ex.getMessage().contains("cc"), ex.getMessage());
    }

    @McpMeshService
    public interface GrandP {
        @Selector(capability = "gp.x")
        String x(@Param("id") String id);
    }

    public interface Par extends GrandP {
    }

    public interface Chi extends Par {
    }

    public static class GrandParamBean {
        @MeshTool(capability = "gp_tool")
        public String run(@Param("x") String x, Chi view) {
            return x;
        }
    }

    @Test
    void transitiveGrandparentInheritance_isValidViewParam() throws Exception {
        Method m = GrandParamBean.class.getMethod("run", String.class, Chi.class);
        MeshToolWrapper w = wrapperFor(new GrandParamBean(), "GrandParamBean.run", "gp_tool", m, List.of());
        assertEquals(List.of("gp.x"), w.getDependencyNames());
    }

    @McpMeshService
    public interface D1 {
        @Selector(capability = "d.x")
        String x(@Param("id") String id);
    }

    @McpMeshService
    public interface D2 {
        @Selector(capability = "d.y")
        String y(@Param("id") String id);
    }

    public interface Dia extends D1, D2 {
    }

    public static class DiaParamBean {
        @MeshTool(capability = "dia_tool")
        public String run(@Param("x") String x, Dia view) {
            return x;
        }
    }

    @Test
    void diamondTwoAnnotatedParents_isValidViewParam() throws Exception {
        Method m = DiaParamBean.class.getMethod("run", String.class, Dia.class);
        MeshToolWrapper w = wrapperFor(new DiaParamBean(), "DiaParamBean.run", "dia_tool", m, List.of());
        // Both parents' methods become edges, name-sorted (x < y → d.x, d.y).
        assertEquals(List.of("d.x", "d.y"), w.getDependencyNames());
    }

    // ---- MED-2: claim-path refusal for an unresolved required VIEW edge ------

    @Test
    void invokeForClaim_requiredViewEdgeUnresolved_releasesAndDoesNotInvoke() throws Exception {
        ReqProcessor bean = new ReqProcessor();
        MeshToolWrapper w = reqWrapper(bean);

        AtomicReference<String> released = new AtomicReference<>();
        // The guard is the FIRST statement in invokeForClaim — BEFORE buildFullArgs
        // (and its settle wait), same as slot deps: an unresolved required view
        // edge releases the lease instead of invoking the handler.
        Object result = w.invokeForClaim(Map.of("x", "v"), null, null, released::set);

        assertNull(result, "guard must return null (job re-queues), not a handler result");
        assertFalse(bean.handlerRan.get(), "handler MUST NOT run for an unresolved required view edge");
        assertNotNull(released.get(), "the lease MUST be released so the job re-queues");
        assertTrue(released.get().contains("req.a"), released.get());
    }

    // ---- MED-3: down-transition — resolve, unavailable event, re-resolve -----

    @Test
    void viewEdge_downThenReResolve_sentinelSubstitution() throws Exception {
        MediaProcessor bean = new MediaProcessor();
        MeshToolWrapper w = mediaWrapper(bean);
        w.updateDependency(3, new ViewStub("media.transcribe", true)); // keep transcribe up

        // Resolve caption → OK.
        w.updateDependency(1, new ViewStub("media.caption", true));
        @SuppressWarnings("unchecked")
        Map<String, Object> ok = (Map<String, Object>) w.invoke(Map.of("assetId", "x"));
        assertEquals("RESP:media.caption", ok.get("caption"));

        // Registry unavailable event → the facade method now throws via the
        // unavailable sentinel.
        w.updateDependency(1, null);
        Exception down = assertThrows(Exception.class, () -> w.invoke(Map.of("assetId", "x")));
        assertInstanceOf(MeshToolUnavailableException.class, unwrap(down));

        // Re-resolve → OK again.
        w.updateDependency(1, new ViewStub("media.caption", true));
        @SuppressWarnings("unchecked")
        Map<String, Object> again = (Map<String, Object>) w.invoke(Map.of("assetId", "x"));
        assertEquals("RESP:media.caption", again.get("caption"));
    }

    // ---- MED-4: two view params + explicit dep — offset arithmetic ----------

    @McpMeshService
    public interface AudioService {
        @Selector(capability = "audio.x") String x(@Param("id") String id);
        @Selector(capability = "audio.y") String y(@Param("id") String id);
    }

    public static class MultiViewProcessor {
        @MeshTool(capability = "multi_tool", dependencies = @Selector(capability = "audit_log"))
        public Map<String, Object> run(@Param("id") String id, McpMeshTool<String> auditLog,
                                       MediaService media, AudioService audio) {
            Map<String, Object> out = new java.util.LinkedHashMap<>();
            out.put("caption", media.caption(id));
            out.put("audioX", audio.x(id));
            return out;
        }
    }

    @Test
    void multiViewParams_offsetArithmeticAndRouting() throws Exception {
        MultiViewProcessor bean = new MultiViewProcessor();
        Method m = MultiViewProcessor.class.getMethod("run",
            String.class, McpMeshTool.class, MediaService.class, AudioService.class);
        MeshToolWrapper w = wrapperFor(bean, "MultiViewProcessor.run", "multi_tool", m,
            List.of("audit_log"));

        // audit_log(0), view1 media edges 1..3 (caption,thumbnail,transcribe),
        // view2 audio edges start at explicitDepCount + view1.size() = 1 + 3 = 4.
        assertEquals(List.of("audit_log", "media.caption", "media.thumbnail", "media.transcribe",
                "audio.x", "audio.y"),
            w.getDependencyNames());

        // Events route to the right facade method on BOTH views.
        w.updateDependency(1, new ViewStub("media.caption", true)); // view1 caption
        w.updateDependency(4, new ViewStub("audio.x", true));       // view2 x
        @SuppressWarnings("unchecked")
        Map<String, Object> out = (Map<String, Object>) w.invoke(Map.of("id", "a1"));
        assertEquals("RESP:media.caption", out.get("caption"));
        assertEquals("RESP:audio.x", out.get("audioX"));

        // Wire list order matches the declared-index order.
        MeshToolRegistry reg = new MeshToolRegistry();
        reg.registerTool(bean, m, m.getAnnotation(MeshTool.class));
        AgentSpec.ToolSpec spec = reg.getToolSpecs().stream()
            .filter(t -> "multi_tool".equals(t.getCapability())).findFirst().orElseThrow();
        assertEquals(List.of("audit_log", "media.caption", "media.thumbnail", "media.transcribe",
                "audio.x", "audio.y"),
            spec.getDependencies().stream().map(AgentSpec.DependencySpec::getCapability).toList());
    }

    // ---- MED-5: duplicate capability between explicit dep and view edge ------

    @McpMeshService
    public interface AuditView {
        @Selector(capability = "audit_log") String log(@Param("id") String id);
    }

    public static class DupCapProcessor {
        @MeshTool(capability = "dup_tool", dependencies = @Selector(capability = "audit_log"))
        public String run(@Param("x") String x, AuditView view) {
            return "x";
        }
    }

    @Test
    void duplicateCapability_explicitAndViewEdge_warnsButKeepsBothEdges() throws Exception {
        LogCapture capture = LogCapture.attach(MeshToolWrapper.class);
        try {
            Method m = DupCapProcessor.class.getMethod("run", String.class, AuditView.class);
            MeshToolWrapper w = wrapperFor(new DupCapProcessor(), "DupCapProcessor.run", "dup_tool",
                m, List.of("audit_log"));
            // Behavior unchanged: two independent edges kept.
            assertEquals(List.of("audit_log", "audit_log"), w.getDependencyNames());
            assertTrue(capture.events.stream().anyMatch(e -> "WARN".equals(e.level)
                    && e.message.contains("DupCapProcessor.run")
                    && e.message.contains("audit_log")
                    && e.message.contains("explicit @Selector")),
                "a duplicate-capability WARN must name the tool, capability, and both sources");
        } finally {
            capture.detach();
        }
    }

    // ---- MED-7: bean-path and tool-param strategies are independent ----------

    @Test
    void beanAndToolStrategies_operateIndependently() throws Exception {
        // Bean-path facade (injector strategy) for MediaService, unresolved.
        McpMeshServiceRegistrar.ServiceViewMetadata meta =
            McpMeshServiceRegistrar.analyze(MediaService.class);
        AtomicReference<MeshDependencyInjector> injectorRef =
            new AtomicReference<>(new MeshDependencyInjector());
        MediaService beanFacade = (MediaService) Proxy.newProxyInstance(
            MediaService.class.getClassLoader(),
            new Class<?>[] {MediaService.class},
            new McpMeshServiceInvocationHandler(MediaService.class, meta.minAvailable(),
                meta.bindings(), new InjectorViewProxyBinding(null, injectorRef), MAPPER));
        assertThrows(MeshToolUnavailableException.class, () -> beanFacade.caption("x"),
            "bean-path facade starts unresolved");

        // Tool-param facade (wrapper-slot strategy) for the SAME capability —
        // resolve ONLY the tool slot; the tool path works.
        MediaProcessor bean = new MediaProcessor();
        MeshToolWrapper w = mediaWrapper(bean);
        w.updateDependency(1, new ViewStub("media.caption", true));
        w.updateDependency(3, new ViewStub("media.transcribe", true));
        @SuppressWarnings("unchecked")
        Map<String, Object> out = (Map<String, Object>) w.invoke(Map.of("assetId", "x"));
        assertEquals("RESP:media.caption", out.get("caption"));

        // The bean path is STILL unresolved — the two strategies key different
        // spaces (injector shared proxy vs wrapper funcId:dep_N slot).
        assertThrows(MeshToolUnavailableException.class, () -> beanFacade.caption("x"),
            "resolving the tool slot must NOT resolve the bean-path injector proxy");
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
            capture.appender.setContext(logger.getLoggerContext());
            capture.appender.start();
            logger.addAppender(capture.appender);
            return capture;
        }

        void detach() {
            target.detachAppender(appender);
            appender.stop();
        }

        record LogEvent(String level, String message) {}
    }
}
