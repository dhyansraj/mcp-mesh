package io.mcpmesh.spring;

import io.mcpmesh.types.McpMeshTool;
import org.springframework.beans.factory.config.ConfigurableListableBeanFactory;

import java.lang.reflect.Method;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;

/**
 * RFC #1280 phase-1 (bean path) proxy strategy for
 * {@link MeshServiceInvocationHandler}: each view method resolves to
 * {@link MeshDependencyInjector}'s SHARED per-capability proxy. The proxy is
 * stable (the injector mutates its endpoint in place on rebind), so it is cached
 * per method. Settle waits key on the capability name — the same key space the
 * injector's {@code updateToolDependency.markResolved} counts down.
 */
class InjectorViewProxyBinding implements MeshServiceInvocationHandler.ViewProxyBinding {

    private final ConfigurableListableBeanFactory beanFactory;
    private final AtomicReference<MeshDependencyInjector> injectorRef;
    private final Map<Method, McpMeshTool<?>> proxyCache = new ConcurrentHashMap<>();

    InjectorViewProxyBinding(ConfigurableListableBeanFactory beanFactory,
                             AtomicReference<MeshDependencyInjector> injectorRef) {
        this.beanFactory = beanFactory;
        this.injectorRef = injectorRef;
    }

    @Override
    public McpMeshTool<?> proxyFor(MeshServiceRegistrar.ServiceMethodBinding binding) {
        return proxyCache.computeIfAbsent(binding.method(), m ->
            injector().getToolProxy(binding.capability(), binding.resolvedProxyType()));
    }

    @Override
    public String settleKey(MeshServiceRegistrar.ServiceMethodBinding binding) {
        return binding.capability();
    }

    private MeshDependencyInjector injector() {
        MeshDependencyInjector injector = injectorRef.get();
        if (injector == null) {
            injector = beanFactory.getBean(MeshDependencyInjector.class);
            injectorRef.compareAndSet(null, injector);
        }
        return injector;
    }
}
