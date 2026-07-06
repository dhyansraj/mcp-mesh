package io.mcpmesh.spring;

import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshServiceUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;

/**
 * {@link InvocationHandler} backing a {@link io.mcpmesh.McpMeshService} view
 * proxy (RFC #1280). Each abstract method delegates to its own per-capability
 * {@link McpMeshTool} proxy resolved from the shared {@link MeshDependencyInjector}
 * — so different methods may bind different provider agents and rebind
 * independently as the mesh topology changes (the injector mutates the same
 * proxy instance in place, so the cached reference stays live).
 *
 * <p>The {@code minAvailable} floor is enforced BEFORE any delegation: when
 * fewer than {@code minAvailable} of the view's methods currently resolve,
 * EVERY facade call fails with {@link MeshServiceUnavailableException}. During
 * the startup settling window the floor check first performs the same bounded,
 * capability-keyed wait the injected-proxy path uses, so a floored view does
 * NOT fail fast while an unfloored one would wait (issue #1193 parity). This is
 * a consumer-local circuit breaker with no wire effect.
 *
 * <p>{@code default}/{@code static} interface methods are dispatched via
 * {@link InvocationHandler#invokeDefault} and are NOT dependency edges.
 * {@link Object} methods ({@code toString}/{@code hashCode}/{@code equals}) are
 * handled conventionally.
 */
class McpMeshServiceInvocationHandler implements InvocationHandler {

    private static final Logger log = LoggerFactory.getLogger(McpMeshServiceInvocationHandler.class);

    /**
     * Pluggable per-method proxy + settle-key lookup — the ONLY difference
     * between the two facade paths (RFC #1280 phase 1 vs phase 2). Floor / param
     * / return / dispatch logic is shared.
     *
     * <ul>
     *   <li><b>Bean path (phase 1):</b> injector-backed — {@code proxyFor} returns
     *       {@link MeshDependencyInjector}'s shared per-capability proxy;
     *       {@code settleKey} is the capability name.</li>
     *   <li><b>Tool-param path (phase 2):</b> wrapper-slot-backed — {@code proxyFor}
     *       reads the {@link MeshToolWrapper}'s per-method slot proxy;
     *       {@code settleKey} is the {@code funcId:dep_N} composite key.</li>
     * </ul>
     */
    interface ViewProxyBinding {
        /** Non-null proxy for the binding's method (unresolved → an unavailable sentinel). */
        McpMeshTool<?> proxyFor(McpMeshServiceRegistrar.ServiceMethodBinding binding);

        /** Settle-wait key for the binding's capability (capability name or funcId:dep_N). */
        String settleKey(McpMeshServiceRegistrar.ServiceMethodBinding binding);
    }

    private final String serviceName;
    private final int minAvailable;
    private final Map<Method, McpMeshServiceRegistrar.ServiceMethodBinding> bindings;
    private final ViewProxyBinding proxyBinding;
    private final ObjectMapper objectMapper;

    /**
     * Cache for the binding lookup of a Method that isn't an exact key in
     * {@link #bindings} — e.g. a covariantly-overridden method invoked through a
     * SUPER-interface reference dispatches the super method, whose
     * {@code equals} misses. Resolved by name + parameter types, cached so the
     * reflective fallback costs once per Method.
     */
    private final Map<Method, McpMeshServiceRegistrar.ServiceMethodBinding> resolvedBindings =
        new ConcurrentHashMap<>();

    /**
     * Floor-transition tracker for observability. {@code null} = never
     * evaluated; {@code TRUE} = currently below floor. Only meaningful when
     * {@code minAvailable > 0}.
     */
    private final AtomicReference<Boolean> belowFloor = new AtomicReference<>();

    McpMeshServiceInvocationHandler(
            Class<?> iface,
            int minAvailable,
            List<McpMeshServiceRegistrar.ServiceMethodBinding> bindingList,
            ViewProxyBinding proxyBinding,
            ObjectMapper objectMapper) {
        this.serviceName = iface.getSimpleName();
        this.minAvailable = minAvailable;
        this.proxyBinding = proxyBinding;
        this.objectMapper = objectMapper;
        Map<Method, McpMeshServiceRegistrar.ServiceMethodBinding> map = new LinkedHashMap<>();
        for (McpMeshServiceRegistrar.ServiceMethodBinding b : bindingList) {
            map.put(b.method(), b);
        }
        this.bindings = map;
    }

    @Override
    public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
        // Object methods handled conventionally.
        if (method.getDeclaringClass() == Object.class) {
            return switch (method.getName()) {
                case "toString" -> renderToString();
                case "hashCode" -> System.identityHashCode(proxy);
                case "equals" -> proxy == (args != null ? args[0] : null);
                default -> throw new UnsupportedOperationException(method.getName());
            };
        }

        // default/static interface methods: NOT dependency edges — dispatch to
        // the interface's own implementation. invokeDefault resolves the
        // most-specific override and works under JPMS (issue: MethodHandles
        // privateLookupIn needs an accessible module).
        if (method.isDefault()) {
            return InvocationHandler.invokeDefault(proxy, method, args);
        }

        McpMeshServiceRegistrar.ServiceMethodBinding binding = resolveBinding(method);
        if (binding == null) {
            // Genuinely unknown method (not just a super-interface dispatch of a
            // covariant override — that is resolved by name + parameter types).
            throw new IllegalStateException("No mesh binding for method " + method
                + " on service view " + serviceName);
        }

        // A floored async method must not block the caller: the floor check can
        // perform a bounded settle-window wait, so for ASYNC + a floor we run it
        // OFF the caller thread and compose the delegate call — a floor breach
        // surfaces as a failed future. Executor = the CompletableFuture common
        // pool, matching McpMeshToolProxy.callAsync; the caller's trace context
        // is captured and restored on the pool thread (TraceContext.wrapSupplier).
        // With no floor (minAvailable == 0) enforceFloor is a no-op — there is
        // nothing to wait on — so we delegate directly (callAsync is already
        // async) and avoid an extra thread hop.
        if (binding.returnMode() == McpMeshServiceRegistrar.ReturnMode.ASYNC && minAvailable > 0) {
            McpMeshServiceRegistrar.ServiceMethodBinding b = binding;
            return CompletableFuture
                .supplyAsync(io.mcpmesh.spring.tracing.TraceContext.wrapSupplier(() -> {
                    enforceFloor();
                    return asCompletableFuture(delegate(b, proxyFor(b), args));
                }))
                .thenCompose(future -> future);
        }

        enforceFloor();
        McpMeshTool<?> tool = proxyFor(binding);
        return delegate(binding, tool, args);
    }

    /**
     * Resolve the binding for {@code method}: the exact-key hit is the common
     * path; a covariant override invoked through a super-interface reference
     * misses (the super {@link Method} is dispatched) and is resolved by name +
     * parameter types, cached so the reflective fallback runs once per Method.
     */
    private McpMeshServiceRegistrar.ServiceMethodBinding resolveBinding(Method method) {
        McpMeshServiceRegistrar.ServiceMethodBinding direct = bindings.get(method);
        if (direct != null) {
            return direct;
        }
        return resolvedBindings.computeIfAbsent(method, m -> {
            for (McpMeshServiceRegistrar.ServiceMethodBinding b : bindings.values()) {
                Method bound = b.method();
                if (bound.getName().equals(m.getName())
                        && Arrays.equals(bound.getParameterTypes(), m.getParameterTypes())) {
                    return b;
                }
            }
            return null;
        });
    }

    /**
     * Enforce the {@code minAvailable} floor across the whole view. Counts the
     * methods whose per-capability proxy is currently available; below the floor
     * during the settling window it performs a bounded, capability-keyed wait on
     * the unresolved capabilities before a single authoritative recount, then
     * fails only if still below. Logs INFO on floor-state transitions and DEBUG
     * per-method counts.
     */
    private void enforceFloor() {
        if (minAvailable <= 0) {
            return; // no floor declared
        }
        // Single pass (O(n)): count available bindings, and while the agent is
        // still settling (#1193) perform a bounded, capability-keyed wait on the
        // unresolved ones — matching McpMeshToolProxy.awaitSettleIfUnavailable.
        // The running counter drives an early exit (never wait past the floor)
        // and also counts side-effect resolutions (a capability resolved by
        // another consumer's event while we waited on an earlier one). Once
        // settled the waits are no-ops and the floor fails fast as before.
        MeshSettleState settle = MeshSettleState.getInstance();
        boolean settled = settle.isSettled();
        int available = 0;
        for (McpMeshServiceRegistrar.ServiceMethodBinding b : bindings.values()) {
            if (available >= minAvailable) {
                break;
            }
            McpMeshTool<?> proxy = proxyFor(b);
            if (!proxy.isAvailable() && !settled) {
                settle.awaitDependency(proxyBinding.settleKey(b), b.capability());
                // The wrapper-slot path replaces the slot with a NEW proxy on
                // resolution (the injector path mutates in place), so re-read.
                proxy = proxyFor(b);
            }
            if (proxy.isAvailable()) {
                available++;
            }
        }
        if (available < minAvailable) {
            // Authoritative final count (single recount) — catches a capability
            // that resolved after the pass had already visited it.
            available = countAvailable();
        }
        boolean below = available < minAvailable;
        Boolean prev = belowFloor.getAndSet(below);
        if (prev == null || prev != below) {
            log.info("service view {} {}: methods_available={}/{} (minAvailable={})",
                serviceName, below ? "below floor" : "restored",
                available, bindings.size(), minAvailable);
        } else {
            log.debug("service view {} methods_available={}/{}", serviceName, available, bindings.size());
        }
        if (below) {
            throw new MeshServiceUnavailableException(
                serviceName, available, bindings.size(), minAvailable);
        }
    }

    private int countAvailable() {
        int available = 0;
        for (McpMeshServiceRegistrar.ServiceMethodBinding b : bindings.values()) {
            if (proxyFor(b).isAvailable()) {
                available++;
            }
        }
        return available;
    }

    /** Resolve the per-method proxy via the pluggable strategy (never null). */
    private McpMeshTool<?> proxyFor(McpMeshServiceRegistrar.ServiceMethodBinding binding) {
        return proxyBinding.proxyFor(binding);
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private Object delegate(McpMeshServiceRegistrar.ServiceMethodBinding binding,
                            McpMeshTool<?> tool, Object[] args) {
        if (binding.paramMode() == McpMeshServiceRegistrar.ParamMode.SINGLE_POJO
                && (args == null || args[0] == null)) {
            throw new IllegalArgumentException("@McpMeshService " + serviceName + "."
                + binding.method().getName() + " single-object parameter must not be null");
        }
        McpMeshTool raw = tool;
        return switch (binding.returnMode()) {
            case SYNC -> switch (binding.paramMode()) {
                case NONE -> raw.call();
                case SINGLE_POJO -> raw.call(args[0]);
                case PARAM_MAP -> raw.call(buildParamMap(binding, args));
            };
            case ASYNC -> switch (binding.paramMode()) {
                case NONE -> raw.callAsync();
                case SINGLE_POJO -> raw.callAsync(args[0]);
                case PARAM_MAP -> raw.callAsync(buildParamMap(binding, args));
            };
            case STREAM -> switch (binding.paramMode()) {
                case NONE -> raw.stream();
                case SINGLE_POJO -> raw.stream(pojoToMap(args[0]));
                case PARAM_MAP -> raw.stream(buildParamMap(binding, args));
            };
        };
    }

    private Map<String, Object> buildParamMap(
            McpMeshServiceRegistrar.ServiceMethodBinding binding, Object[] args) {
        // LinkedHashMap: preserve declared parameter order (deterministic wire
        // payload), mirroring the @MeshTool param-map assembly.
        Map<String, Object> params = new LinkedHashMap<>();
        String[] names = binding.paramNames();
        for (int i = 0; i < names.length; i++) {
            params.put(names[i], args[i]);
        }
        return params;
    }

    /** The ASYNC delegate result is always a {@code CompletableFuture} (callAsync). */
    @SuppressWarnings("unchecked")
    private static CompletableFuture<Object> asCompletableFuture(Object result) {
        return (CompletableFuture<Object>) result;
    }

    /** Convert a single POJO argument to a params map for the stream path. */
    private Map<String, Object> pojoToMap(Object arg) {
        return objectMapper.convertValue(arg, new TypeReference<Map<String, Object>>() {});
    }

    private String renderToString() {
        String counts;
        try {
            counts = countAvailable() + "/" + bindings.size();
        } catch (RuntimeException e) {
            counts = "?/" + bindings.size();
        }
        return "McpMeshService[" + serviceName + ", " + counts + " available]";
    }
}
