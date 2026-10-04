package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshDependencyInjector;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.ResponseEntity;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Type;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Issue #1568 A, A2A side: the dispatcher used to ask the injector for the
 * capability's single untyped proxy, whose return type was whatever another
 * consumer of the capability last set on it. Each dependency slot now requests
 * its own typed proxy — the {@code McpMeshTool<T>} argument of the parameter it
 * positionally binds to, else the declared {@code expectedType}.
 */
@DisplayName("#1568 A: @MeshA2A dependency slots get their own typed proxy")
class MeshA2ADispatcherTypedProxyTest {

    record Alpha(String a) {}
    record Beta(String b) {}

    public static class TypedA2A {
        static final ThreadLocal<List<Object>> SEEN = new ThreadLocal<>();

        @MeshA2A(path = "/agents/typed", skillId = "typed", skillName = "Typed",
                 dependencies = {
                     @MeshDependency(capability = "first"),
                     @MeshDependency(capability = "second"),
                     @MeshDependency(capability = "third", expectedType = Beta.class),
                     @MeshDependency(capability = "fourth")
                 })
        public Map<String, Object> handle(Map<String, Object> message,
                                          McpMeshTool<Alpha> second,
                                          McpMeshTool<List<Beta>> first,
                                          McpMeshTool raw,
                                          McpMeshTool untyped) {
            SEEN.set(java.util.Arrays.asList(second, first, raw, untyped));
            return new LinkedHashMap<>(Map.of("ok", true));
        }
    }

    private MeshA2ARegistry registry;
    private MeshDependencyInjector injector;
    private MeshA2ADispatcher dispatcher;
    private final ObjectMapper mapper = A2ATestFixtures.objectMapper();

    @BeforeEach
    void setUp() {
        registry = new MeshA2ARegistry();
        injector = mock(MeshDependencyInjector.class);
        when(injector.getToolProxy(anyString())).thenReturn(null);
        when(injector.getToolProxy(anyString(), any(Type.class))).thenReturn(null);
        new MeshA2ABeanPostProcessor(registry).postProcessAfterInitialization(new TypedA2A(), "typed");
        dispatcher = new MeshA2ADispatcher(registry, new MeshA2ATaskStore(), mapper,
            new ObjectProvider<>() {
                @Override public MeshDependencyInjector getObject() { return injector; }
                @Override public MeshDependencyInjector getObject(Object... args) { return injector; }
                @Override public MeshDependencyInjector getIfAvailable() { return injector; }
                @Override public MeshDependencyInjector getIfUnique() { return injector; }
            });
    }

    @Test
    @DisplayName("each slot is resolved with the type its position declares")
    void slotsResolveTyped() throws Exception {
        McpMeshTool alpha = mock(McpMeshTool.class, "alpha");
        McpMeshTool listOfBeta = mock(McpMeshTool.class, "listOfBeta");
        McpMeshTool beta = mock(McpMeshTool.class, "beta");
        McpMeshTool dynamic = mock(McpMeshTool.class, "dynamic");
        Type listOfBetaType = TypedA2A.class.getMethod("handle",
            Map.class, McpMeshTool.class, McpMeshTool.class, McpMeshTool.class, McpMeshTool.class)
            .getGenericParameterTypes()[2];
        Type listArg = ((java.lang.reflect.ParameterizedType) listOfBetaType).getActualTypeArguments()[0];

        // dependency[0] 'first' binds to parameter 1 (McpMeshTool<Alpha>), not to
        // the parameter NAMED first.
        when(injector.getToolProxy(eq("first"), eq(Alpha.class))).thenReturn(alpha);
        when(injector.getToolProxy(eq("second"), eq(listArg))).thenReturn(listOfBeta);
        // Raw parameter: falls back to the declared expectedType.
        when(injector.getToolProxy(eq("third"), eq(Beta.class))).thenReturn(beta);
        // Raw parameter, no expectedType: the dynamic (untyped) proxy.
        when(injector.getToolProxy("fourth")).thenReturn(dynamic);

        ResponseEntity<String> resp = dispatcher.dispatch("/agents/typed",
            A2ATestFixtures.jsonRpcBody(1, "tasks/send",
                Map.of("id", "t1", "message", Map.of("text", "hi"))));
        JsonNode result = mapper.readTree(resp.getBody()).get("result");
        assertNotNull(result, resp.getBody());
        assertEquals("completed", result.get("status").get("state").asText(), resp.getBody());

        List<Object> seen = TypedA2A.SEEN.get();
        assertSame(alpha, seen.get(0));
        assertSame(listOfBeta, seen.get(1));
        assertSame(beta, seen.get(2));
        assertSame(dynamic, seen.get(3));
    }

    @Test
    @DisplayName("the scanner stamps each dependency with its positional McpMeshTool<T>")
    void scannerStampsPositionalTypes() {
        List<MeshRouteRegistry.DependencySpec> deps = registry.getByPath("/agents/typed").dependencies();
        assertEquals(Alpha.class, deps.get(0).getReturnType());
        assertEquals("java.util.List<" + Beta.class.getName() + ">",
            deps.get(1).getReturnType().getTypeName());
        assertNull(deps.get(2).getReturnType());
        assertEquals(Beta.class, deps.get(2).getProxyType());
        assertNull(deps.get(3).getProxyType());
    }
}
