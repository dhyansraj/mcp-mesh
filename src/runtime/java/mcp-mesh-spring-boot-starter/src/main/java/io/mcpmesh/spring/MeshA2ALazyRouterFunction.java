package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshA2ADispatcherController;
import org.springframework.web.servlet.function.HandlerFunction;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.RouterFunctions;
import org.springframework.web.servlet.function.ServerRequest;
import org.springframework.web.servlet.function.ServerResponse;

import java.util.Optional;

/**
 * Lazy wrapper around {@link MeshA2ADispatcherController#buildRouterFunction()}.
 *
 * <p>Returned by {@code MeshAutoConfiguration.meshA2ARouterFunction(...)} as the
 * registered {@link RouterFunction} bean. The inner router is materialised on the
 * first invocation of either {@link #route(ServerRequest)} or
 * {@link #accept(RouterFunctions.Visitor)}, OR explicitly via
 * {@link #materialise()} (called from a {@code SmartInitializingSingleton}).
 *
 * <h2>Why lazy</h2>
 *
 * <p>An earlier revision built the inner router synchronously inside the
 * {@code meshA2ARouterFunction} factory, after forcing creation of every
 * {@code @Component}/{@code @Service} bean so {@link io.mcpmesh.spring.web.MeshA2ABeanPostProcessor}
 * had a chance to populate {@link io.mcpmesh.spring.web.MeshA2ARegistry}. That
 * forced walk re-entered any user {@code @Component} that autowired
 * {@link MeshRuntime}, triggering a Spring bean-creation cycle (issue #937).
 *
 * <p>Deferring the {@code buildRouterFunction()} call to first-access
 * (either {@code accept(...)} from {@code RouterFunctionMapping.afterPropertiesSet()}
 * or {@code route(...)} from the first matching HTTP request) removes the
 * factory from the cycle path. By the time first-access occurs, every
 * candidate bean has been post-processed by Spring's bean-creation pipeline
 * and the registry is fully populated — the registry-driven route table
 * is built once and cached.
 *
 * <h2>Concurrency</h2>
 *
 * <p>The build is single-shot and guarded by the monitor on {@code this}.
 * Concurrent first-access from multiple HTTP threads is harmless: only one
 * thread executes {@code buildRouterFunction()}, the rest re-read the
 * cached reference. {@link #materialise()} runs synchronously on the
 * Spring bootstrap thread, so contention in practice is negligible.
 */
final class MeshA2ALazyRouterFunction implements RouterFunction<ServerResponse> {

    private final MeshA2ADispatcherController controller;
    private volatile RouterFunction<ServerResponse> delegate;

    MeshA2ALazyRouterFunction(MeshA2ADispatcherController controller) {
        this.controller = controller;
    }

    /**
     * Build the inner router if it hasn't been built yet. Idempotent —
     * subsequent calls are no-ops. Invoked by the post-singleton
     * {@code SmartInitializingSingleton} initializer in
     * {@code MeshAutoConfiguration} to guarantee the router is ready
     * before the first request can arrive.
     */
    void materialise() {
        ensureDelegate();
    }

    private RouterFunction<ServerResponse> ensureDelegate() {
        RouterFunction<ServerResponse> local = this.delegate;
        if (local != null) {
            return local;
        }
        synchronized (this) {
            local = this.delegate;
            if (local == null) {
                local = controller.buildRouterFunction();
                this.delegate = local;
            }
            return local;
        }
    }

    @Override
    public Optional<HandlerFunction<ServerResponse>> route(ServerRequest request) {
        return ensureDelegate().route(request);
    }

    @Override
    public void accept(RouterFunctions.Visitor visitor) {
        ensureDelegate().accept(visitor);
    }
}
