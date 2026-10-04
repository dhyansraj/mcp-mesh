package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshDependencyInjector;
import io.mcpmesh.spring.MeshSettleState;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.ResponseEntity;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Two {@link MeshA2ADispatcher} fixes:
 * <ul>
 *   <li>Issue #1593: {@code @MeshA2A} handlers wait out the settling window for
 *       their dependencies, as {@code @MeshRoute} does (and TypeScript's
 *       {@code mesh.a2a.mount} since #1628).</li>
 *   <li>Issue #1592: the duplicate task-id guard is atomic — two concurrent
 *       {@code tasks/send} requests with one id can no longer both run.</li>
 * </ul>
 */
class MeshA2ADispatcherSettleAndReserveTest {

    public static class SettleA2A {
        static volatile Boolean sawAvailable;

        @MeshA2A(path = "/agents/settle", skillId = "settle", skillName = "Settle",
                 dependencies = {@MeshDependency(capability = "db")})
        public Map<String, Object> handle(Map<String, Object> message, McpMeshTool db) {
            sawAvailable = db != null && db.isAvailable();
            return new LinkedHashMap<>(Map.of("ok", true));
        }
    }

    public static class BlockingA2A {
        static volatile CountDownLatch entered = new CountDownLatch(1);
        static volatile CountDownLatch release = new CountDownLatch(1);

        @MeshA2A(path = "/agents/block", skillId = "block", skillName = "Block")
        public Map<String, Object> handle(Map<String, Object> message) throws InterruptedException {
            entered.countDown();
            release.await(10, TimeUnit.SECONDS);
            return new LinkedHashMap<>(Map.of("ok", true));
        }
    }

    /** A result neither Jackson nor toString() can render. */
    public static final class Unrenderable {
        public String getValue() {
            throw new IllegalStateException("getter blew up");
        }

        @Override
        public String toString() {
            throw new IllegalStateException("toString blew up");
        }
    }

    public static class UnrenderableA2A {
        @MeshA2A(path = "/agents/unrenderable", skillId = "unrenderable", skillName = "Unrenderable")
        public Object handle(Map<String, Object> message) {
            return new Unrenderable();
        }
    }

    private final ObjectMapper mapper = A2ATestFixtures.objectMapper();

    @AfterEach
    void reset() throws Exception {
        setSettleWindow(0.0);
    }

    private MeshA2ADispatcher dispatcher(MeshA2ARegistry registry, MeshDependencyInjector injector) {
        return dispatcher(registry, injector, new MeshA2ATaskStore());
    }

    private MeshA2ADispatcher dispatcher(
            MeshA2ARegistry registry, MeshDependencyInjector injector, MeshA2ATaskStore store) {
        return new MeshA2ADispatcher(registry, store, mapper,
            new ObjectProvider<>() {
                @Override public MeshDependencyInjector getObject() { return injector; }
                @Override public MeshDependencyInjector getObject(Object... args) { return injector; }
                @Override public MeshDependencyInjector getIfAvailable() { return injector; }
                @Override public MeshDependencyInjector getIfUnique() { return injector; }
            });
    }

    private static boolean isDeclared(String key) throws Exception {
        Method m = MeshSettleState.class.getDeclaredMethod("isDeclared", String.class);
        m.setAccessible(true);
        return (boolean) m.invoke(MeshSettleState.getInstance(), key);
    }

    @Test
    void handlerWaitsForItsDependencyWhileSettling() throws Exception {
        setSettleWindow(10.0);
        MeshA2ARegistry registry = new MeshA2ARegistry();
        new MeshA2ABeanPostProcessor(registry).postProcessAfterInitialization(new SettleA2A(), "settle");
        assertTrue(isDeclared("db"), "registration declares the surface's capabilities");

        AtomicBoolean available = new AtomicBoolean(false);
        McpMeshTool db = mock(McpMeshTool.class);
        when(db.isAvailable()).thenAnswer(inv -> available.get());
        MeshDependencyInjector injector = mock(MeshDependencyInjector.class);
        when(injector.getToolProxy(anyString())).thenReturn(db);

        Thread resolver = new Thread(() -> {
            try {
                Thread.sleep(150);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            available.set(true);
            MeshSettleState.getInstance().markResolved("db");
        });
        resolver.start();

        long start = System.nanoTime();
        ResponseEntity<String> resp = dispatcher(registry, injector).dispatch("/agents/settle",
            A2ATestFixtures.jsonRpcBody(1, "tasks/send",
                Map.of("id", "s1", "message", Map.of("text", "hi"))));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        resolver.join(2000);

        JsonNode result = mapper.readTree(resp.getBody()).get("result");
        assertEquals("completed", result.get("status").get("state").asText(), resp.getBody());
        assertEquals(Boolean.TRUE, SettleA2A.sawAvailable,
            "the handler must run after the dependency resolved, not before");
        assertTrue(elapsedMs < 5000, "woken by resolution, not the budget; " + elapsedMs + "ms");
    }

    @Test
    void concurrentSendsWithOneTaskIdRunTheHandlerOnce() throws Exception {
        BlockingA2A.entered = new CountDownLatch(1);
        BlockingA2A.release = new CountDownLatch(1);
        MeshA2ARegistry registry = new MeshA2ARegistry();
        new MeshA2ABeanPostProcessor(registry).postProcessAfterInitialization(new BlockingA2A(), "block");
        MeshA2ADispatcher dispatcher = dispatcher(registry, mock(MeshDependencyInjector.class));
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "dup", "message", Map.of("text", "hi")));

        CompletableFuture<ResponseEntity<String>> first =
            CompletableFuture.supplyAsync(() -> dispatcher.dispatch("/agents/block", body));
        assertTrue(BlockingA2A.entered.await(5, TimeUnit.SECONDS), "first handler started");

        // The first request is still inside its handler — nothing stored yet
        // under the old check-then-act guard, so this used to run a second handler.
        ResponseEntity<String> second = dispatcher.dispatch("/agents/block", body);
        JsonNode secondJson = mapper.readTree(second.getBody());
        assertNotNull(secondJson.get("error"), second.getBody());
        assertEquals(MeshA2ADispatcher.JSONRPC_INVALID_PARAMS, secondJson.get("error").get("code").asInt());
        assertTrue(secondJson.get("error").get("message").asText().contains("already in use"));

        // While in flight, tasks/get sees the reservation as working.
        JsonNode inFlight = mapper.readTree(dispatcher.dispatch("/agents/block",
            A2ATestFixtures.jsonRpcBody(2, "tasks/get", Map.of("id", "dup"))).getBody());
        assertEquals("working", inFlight.get("result").get("status").get("state").asText());

        BlockingA2A.release.countDown();
        JsonNode firstJson = mapper.readTree(first.get(10, TimeUnit.SECONDS).getBody());
        assertEquals("completed", firstJson.get("result").get("status").get("state").asText());
    }

    /** Start a blocking sync handler under task id {@code id}; returns its pending response. */
    private CompletableFuture<ResponseEntity<String>> startBlocked(MeshA2ADispatcher dispatcher, String id)
            throws Exception {
        BlockingA2A.entered = new CountDownLatch(1);
        BlockingA2A.release = new CountDownLatch(1);
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", id, "message", Map.of("text", "hi")));
        CompletableFuture<ResponseEntity<String>> pending =
            CompletableFuture.supplyAsync(() -> dispatcher.dispatch("/agents/block", body));
        assertTrue(BlockingA2A.entered.await(5, TimeUnit.SECONDS), "handler started");
        return pending;
    }

    private MeshA2ADispatcher blockingDispatcher() {
        MeshA2ARegistry registry = new MeshA2ARegistry();
        new MeshA2ABeanPostProcessor(registry).postProcessAfterInitialization(new BlockingA2A(), "block");
        return dispatcher(registry, mock(MeshDependencyInjector.class));
    }

    @Test
    void cancelOnAnInFlightSyncTaskReportsWorkingAndLeavesItToComplete() throws Exception {
        MeshA2ADispatcher dispatcher = blockingDispatcher();
        CompletableFuture<ResponseEntity<String>> first = startBlocked(dispatcher, "c1");

        JsonNode cancel = mapper.readTree(dispatcher.dispatch("/agents/block",
            A2ATestFixtures.jsonRpcBody(2, "tasks/cancel", Map.of("id", "c1"))).getBody());
        assertEquals("working", cancel.get("result").get("status").get("state").asText(),
            "nothing to cancel on a running sync handler — report its current state");

        BlockingA2A.release.countDown();
        first.get(10, TimeUnit.SECONDS);
        JsonNode get = mapper.readTree(dispatcher.dispatch("/agents/block",
            A2ATestFixtures.jsonRpcBody(3, "tasks/get", Map.of("id", "c1"))).getBody());
        assertEquals("completed", get.get("result").get("status").get("state").asText(),
            "cancel must not have marked the task terminal underneath the handler");
    }

    @Test
    void resubscribeOnAnInFlightSyncTaskReportsWorkingNotFailed() throws Exception {
        MeshA2ADispatcher dispatcher = blockingDispatcher();
        CompletableFuture<ResponseEntity<String>> first = startBlocked(dispatcher, "r1");
        try {
            MeshA2ADispatcher.SseStreamPlan plan = dispatcher.buildResubscribeStream(
                A2ATestFixtures.jsonRpcBody(2, "tasks/resubscribe", Map.of("id", "r1")));

            assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.SINGLE_FRAME, plan.kind);
            @SuppressWarnings("unchecked")
            Map<String, Object> result = (Map<String, Object>) plan.firstFrame.get("result");
            @SuppressWarnings("unchecked")
            Map<String, Object> status = (Map<String, Object>) result.get("status");
            assertEquals("working", status.get("state"));
            assertEquals(Boolean.FALSE, result.get("final"));
        } finally {
            BlockingA2A.release.countDown();
            first.get(10, TimeUnit.SECONDS);
        }
    }

    @Test
    void aFailureAfterTheReservationDoesNotLeaveTheIdInUse() throws Exception {
        MeshA2ARegistry registry = new MeshA2ARegistry();
        new MeshA2ABeanPostProcessor(registry).postProcessAfterInitialization(
            new UnrenderableA2A(), "unrenderable");
        MeshA2ATaskStore store = new MeshA2ATaskStore();
        MeshA2ADispatcher dispatcher = dispatcher(registry, mock(MeshDependencyInjector.class), store);
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "leak", "message", Map.of("text", "hi")));

        assertThrows(IllegalStateException.class, () -> dispatcher.dispatch("/agents/unrenderable", body));
        assertFalse(store.contains("leak"), "the reservation must be released");

        assertThrows(IllegalStateException.class,
            () -> dispatcher.buildSendSubscribeStream("/agents/unrenderable", body));
        assertFalse(store.contains("leak"), "the sendSubscribe reservation must be released too");
    }

    @Test
    void taskStoreReserveIsFirstWriterWins() {
        MeshA2ATaskStore store = new MeshA2ATaskStore();
        MeshA2ATaskStore.TaskRecord placeholder =
            new MeshA2ATaskStore.TaskRecord("s", null, null, null, null);

        assertTrue(store.reserve("t", placeholder));
        assertFalse(store.reserve("t", placeholder));
        assertTrue(store.contains("t"));
    }

    private static void setSettleWindow(double seconds) throws Exception {
        Method m = MeshSettleState.class.getDeclaredMethod("resetForTests", double.class);
        m.setAccessible(true);
        m.invoke(null, seconds);
    }
}
