package io.mcpmesh.spring;

import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshServiceUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.config.ConfigurableListableBeanFactory;
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

    private final String serviceName;
    private final int minAvailable;
    private final Map<Method, McpMeshServiceRegistrar.ServiceMethodBinding> bindings;
    private final ConfigurableListableBeanFactory beanFactory;
    private final AtomicReference<MeshDependencyInjector> injectorRef;
    private final ObjectMapper objectMapper;

    /** Per-method resolved proxy cache — the proxy reference is stable. */
    private final Map<Method, McpMeshTool<?>> proxyCache = new ConcurrentHashMap<>();

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
            ConfigurableListableBeanFactory beanFactory,
            AtomicReference<MeshDependencyInjector> injectorRef,
            ObjectMapper objectMapper) {
        this.serviceName = iface.getSimpleName();
        this.minAvailable = minAvailable;
        this.beanFactory = beanFactory;
        this.injectorRef = injectorRef;
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

        // Async floor breach surfaces as a failed future, not a synchronous
        // throw (the method contract returns CompletableFuture).
        if (binding.returnMode() == McpMeshServiceRegistrar.ReturnMode.ASYNC) {
            try {
                enforceFloor();
            } catch (MeshServiceUnavailableException e) {
                return CompletableFuture.failedFuture(e);
            }
        } else {
            enforceFloor();
        }

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
        int available = countAvailable();
        if (available < minAvailable) {
            // Settling-window grace (#1193): wait out the unresolved capabilities
            // up to the remaining settle budget, matching the injected-proxy
            // path (McpMeshToolProxy.awaitSettleIfUnavailable). Once settled the
            // waits are no-ops and the floor fails fast as before.
            MeshSettleState settle = MeshSettleState.getInstance();
            if (!settle.isSettled()) {
                // Track availability incrementally for the early-exit decision
                // (avoids an O(n) recount per iteration); a single authoritative
                // recount follows the loop.
                for (McpMeshServiceRegistrar.ServiceMethodBinding b : bindings.values()) {
                    if (available >= minAvailable) {
                        break;
                    }
                    McpMeshTool<?> proxy = proxyFor(b);
                    if (!proxy.isAvailable()) {
                        settle.awaitDependency(b.capability(), b.capability());
                        if (proxy.isAvailable()) {
                            available++;
                        }
                    }
                }
                available = countAvailable();
            }
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

    /** Lazily resolve + cache the per-method proxy (stable reference). */
    private McpMeshTool<?> proxyFor(McpMeshServiceRegistrar.ServiceMethodBinding binding) {
        return proxyCache.computeIfAbsent(binding.method(), m ->
            injector().getToolProxy(binding.capability(), binding.resolvedProxyType()));
    }

    private MeshDependencyInjector injector() {
        MeshDependencyInjector injector = injectorRef.get();
        if (injector == null) {
            injector = beanFactory.getBean(MeshDependencyInjector.class);
            injectorRef.compareAndSet(null, injector);
        }
        return injector;
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
