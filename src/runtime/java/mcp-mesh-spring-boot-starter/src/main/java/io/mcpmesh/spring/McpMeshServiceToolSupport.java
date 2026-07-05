package io.mcpmesh.spring;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshToolUnavailableException;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Flow;
import java.util.concurrent.atomic.AtomicReferenceArray;

/**
 * RFC #1280 phase 2: shared support for using a {@link McpMeshService} interface
 * as a {@code @MeshTool} PARAMETER. One view parameter expands to N ordinary
 * dependency edges ON THAT TOOL, positionally paired AFTER the explicit
 * {@code @Selector} deps — the same pairing precedent as the MeshJob
 * type-detected slot.
 *
 * <p>Detection + the interface→bindings analysis are shared with the phase-1
 * bean path via {@link McpMeshServiceRegistrar#analyze(Class)}: the same
 * bridge/synthetic filtering, {@link org.springframework.core.ResolvableType}
 * resolution, diamond dedupe, and param/return validation apply.
 */
final class McpMeshServiceToolSupport {

    private McpMeshServiceToolSupport() {
    }

    /** A {@code @MeshTool} parameter that is a service-view facade. */
    record ViewParamInfo(int position, McpMeshServiceRegistrar.ServiceViewMetadata view) {
    }

    /** Whether {@code type} is an interface annotated {@link McpMeshService}. */
    static boolean isServiceView(Class<?> type) {
        return type.isInterface() && type.isAnnotationPresent(McpMeshService.class);
    }

    /**
     * Detect service-view parameters on a {@code @MeshTool} method, in parameter
     * order. A view parameter must NOT carry {@code @Param} (boot-fail). The
     * interface itself is analyzed + validated via the shared analyzer, so all
     * phase-1 interface-level validations apply here too.
     */
    static List<ViewParamInfo> analyzeViewParams(Method method) {
        List<ViewParamInfo> views = new ArrayList<>();
        Parameter[] params = method.getParameters();
        for (int i = 0; i < params.length; i++) {
            Class<?> type = params[i].getType();
            if (!isServiceView(type)) {
                continue;
            }
            if (params[i].isAnnotationPresent(Param.class)) {
                throw new IllegalStateException(String.format(
                    "@MeshTool method %s of %s: @McpMeshService view parameter #%d (%s) must NOT "
                        + "carry @Param — a service-view parameter is injected, not an MCP input.",
                    method.getName(), method.getDeclaringClass().getName(), i, type.getSimpleName()));
            }
            views.add(new ViewParamInfo(i, McpMeshServiceRegistrar.analyze(type)));
        }
        return views;
    }

    /**
     * Build the JDK-proxy facade for a view parameter, backed by the wrapper's
     * per-method slot array (phase-2 proxy strategy). Reuses
     * {@link McpMeshServiceInvocationHandler} — floor / param / return / dispatch
     * logic is identical to the bean path.
     */
    static Object buildFacade(McpMeshServiceRegistrar.ServiceViewMetadata view,
                              McpMeshServiceInvocationHandler.ViewProxyBinding proxyBinding,
                              ObjectMapper objectMapper) {
        Class<?> iface = view.iface();
        return Proxy.newProxyInstance(
            iface.getClassLoader(),
            new Class<?>[] {iface},
            new McpMeshServiceInvocationHandler(
                iface, view.minAvailable(), view.bindings(), proxyBinding, objectMapper));
    }

    /**
     * Phase-2 proxy strategy: per-method proxies come from the
     * {@link MeshToolWrapper}'s slot array (per-consumer-slot typed proxies from
     * {@link McpMeshToolProxyFactory}, funcId:dep_N key space), NOT the shared
     * injector proxies. A slot may be null (unresolved) → an unavailable
     * sentinel is returned so the handler's floor/dispatch logic is uniform.
     */
    static final class WrapperSlotViewProxyBinding
            implements McpMeshServiceInvocationHandler.ViewProxyBinding {

        @SuppressWarnings("rawtypes")
        private final AtomicReferenceArray<McpMeshTool> proxies;
        private final Map<Method, Integer> methodToLocal;
        private final int[] localToDeclaredIndex;
        private final String funcId;
        private final McpMeshTool<?>[] sentinels;

        WrapperSlotViewProxyBinding(
                @SuppressWarnings("rawtypes") AtomicReferenceArray<McpMeshTool> proxies,
                Map<Method, Integer> methodToLocal,
                int[] localToDeclaredIndex,
                String funcId,
                List<McpMeshServiceRegistrar.ServiceMethodBinding> bindings) {
            this.proxies = proxies;
            this.methodToLocal = methodToLocal;
            this.localToDeclaredIndex = localToDeclaredIndex;
            this.funcId = funcId;
            this.sentinels = new McpMeshTool<?>[bindings.size()];
            for (McpMeshServiceRegistrar.ServiceMethodBinding b : bindings) {
                this.sentinels[methodToLocal.get(b.method())] = new UnavailableMeshTool(b.capability());
            }
        }

        @Override
        public McpMeshTool<?> proxyFor(McpMeshServiceRegistrar.ServiceMethodBinding binding) {
            int local = methodToLocal.get(binding.method());
            McpMeshTool<?> proxy = proxies.get(local);
            return proxy != null ? proxy : sentinels[local];
        }

        @Override
        public String settleKey(McpMeshServiceRegistrar.ServiceMethodBinding binding) {
            int local = methodToLocal.get(binding.method());
            return MeshToolWrapperRegistry.buildDependencyKey(funcId, localToDeclaredIndex[local]);
        }
    }

    /**
     * Stand-in for an unresolved view-edge slot: mirrors an unresolved
     * {@code McpMeshToolProxy} so the handler's dispatch is uniform — synchronous
     * calls throw {@link MeshToolUnavailableException}; async calls fail the
     * future; streams throw.
     */
    static final class UnavailableMeshTool implements McpMeshTool<Object> {
        private final String capability;

        UnavailableMeshTool(String capability) {
            this.capability = capability;
        }

        @Override public Object call() { throw unavailable(); }
        @Override public Object call(Map<String, Object> params) { throw unavailable(); }
        @Override public Object call(Object... args) { throw unavailable(); }
        @Override public CompletableFuture<Object> callAsync() { return CompletableFuture.failedFuture(unavailable()); }
        @Override public CompletableFuture<Object> callAsync(Map<String, Object> params) { return CompletableFuture.failedFuture(unavailable()); }
        @Override public CompletableFuture<Object> callAsync(Object... args) { return CompletableFuture.failedFuture(unavailable()); }
        @Override public String getCapability() { return capability; }
        @Override public String getEndpoint() { return null; }
        @Override public String getFunctionName() { return null; }
        @Override public boolean isAvailable() { return false; }
        @Override public Flow.Publisher<String> stream(Map<String, Object> params) { throw unavailable(); }

        private MeshToolUnavailableException unavailable() {
            return new MeshToolUnavailableException(capability);
        }
    }
}
