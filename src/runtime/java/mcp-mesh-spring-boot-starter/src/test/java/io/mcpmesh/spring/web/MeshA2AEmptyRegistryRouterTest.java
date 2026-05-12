package io.mcpmesh.spring.web;

import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.MeshAutoConfiguration;
import io.mcpmesh.spring.MeshProperties;
import io.mcpmesh.spring.MeshRuntime;
import jakarta.servlet.ServletContext;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.converter.StringHttpMessageConverter;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockServletContext;
import org.springframework.web.servlet.function.HandlerFunction;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.ServerRequest;
import org.springframework.web.servlet.function.ServerResponse;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Regression test for the empty-{@code @MeshA2A}-registry crash
 * (hotfix follow-up to #934 + #941).
 *
 * <p>{@link MeshA2ADispatcherController#buildRouterFunction()} previously
 * called {@code RouterFunctions.Builder.build()} on a builder that received
 * zero routes whenever no {@code @MeshA2A} surfaces were registered.
 * {@code Builder.build()} throws:
 *
 * <pre>
 *   IllegalStateException: No routes registered.
 *   Register a route with GET(), POST(), etc.
 * </pre>
 *
 * <p>which crashed the agent process at context refresh BEFORE it could
 * register with the mesh registry. The crash hit ~100 integration tests
 * because most Java agents (basic {@code @MeshTool} agents, consumer-only
 * apps, lifecycle/registry tests) do NOT declare {@code @MeshA2A} surfaces
 * — the producer wiring is always installed but the registry is empty
 * until a user opts in.
 *
 * <h2>The fix</h2>
 *
 * <p>When the registry is empty, {@code buildRouterFunction()} returns a
 * never-matching {@link RouterFunction} directly (bypassing the builder
 * entirely). Spring's {@code RouterFunctionMapping} accepts the bean
 * without complaint and no fake/internal path lands in the route table; if
 * any request ever reaches it, {@code route()} returns
 * {@link Optional#empty()} and the request falls through to the next
 * handler.
 *
 * <h2>Coverage</h2>
 *
 * <ol>
 *   <li>Unit: {@code buildRouterFunction()} on an empty registry does NOT
 *       throw and returns a non-null router.</li>
 *   <li>Unit: the returned router never matches any probe request
 *       (route() returns Optional.empty() in every case).</li>
 *   <li>Context: a Spring application context with NO {@code @MeshA2A}
 *       beans refreshes cleanly (no {@code IllegalStateException: No
 *       routes registered}) and exposes the {@code meshA2ARouterFunction}
 *       bean.</li>
 * </ol>
 */
@DisplayName("MeshA2A producer — empty-registry router (hotfix regression)")
class MeshA2AEmptyRegistryRouterTest {

    private static final List<HttpMessageConverter<?>> CONVERTERS =
        List.of(new StringHttpMessageConverter(StandardCharsets.UTF_8));

    @Test
    @DisplayName("Empty registry → router exists but matches no requests "
        + "(bypasses RouterFunctions.Builder.build() empty-list rejection)")
    void buildRouterFunction_emptyRegistry_returnsNeverMatchingRouter() throws Exception {
        MeshA2ARegistry emptyRegistry = new MeshA2ARegistry();
        assertTrue(emptyRegistry.getAllSurfaces().isEmpty(),
            "Pre-condition: registry must be empty for this regression case");

        MeshA2ADispatcherController controller = new MeshA2ADispatcherController(
            emptyRegistry,
            new MeshA2ADispatcher(emptyRegistry, new MeshA2ATaskStore(),
                A2ATestFixtures.objectMapper(),
                A2ATestFixtures.emptyInjectorProvider()),
            new MeshA2ASseDispatcher(new MeshA2ADispatcher(emptyRegistry,
                new MeshA2ATaskStore(), A2ATestFixtures.objectMapper(),
                A2ATestFixtures.emptyInjectorProvider())),
            new MeshA2ACardBuilder(null, A2ATestFixtures.objectMapper()),
            emptyProvider(MeshProperties.class),
            emptyProvider(MeshA2APublicUrlCache.class));

        RouterFunction<ServerResponse> router = controller.buildRouterFunction();
        assertNotNull(router, "buildRouterFunction() must never return null");

        // The empty-registry router must match NO request — there's no fake
        // path in the route table. Probe a few representative paths to prove
        // that route() returns Optional.empty() in every case. The bean
        // exists only so Spring's RouterFunctionMapping can collect it; it
        // never serves real traffic.
        ServletContext servletContext = new MockServletContext();
        for (String path : new String[]{
                "/", "/anything", "/agents/foo", "/agents/foo/.well-known/agent.json"}) {
            MockHttpServletRequest req = new MockHttpServletRequest(
                servletContext, "GET", path);
            req.addHeader(HttpHeaders.ACCEPT, MediaType.ALL_VALUE);
            ServerRequest serverRequest = ServerRequest.create(req, CONVERTERS);
            Optional<HandlerFunction<ServerResponse>> match = router.route(serverRequest);
            assertTrue(match.isEmpty(),
                "Empty-registry router must NOT match any request (probed "
                    + path + ") — it returns Optional.empty() so requests fall "
                    + "through to other handlers in the chain");
        }
    }

    /**
     * Context-level guard: boots a real {@link MeshAutoConfiguration} with
     * NO user beans declaring {@code @MeshA2A}. Pre-fix this fails at
     * context refresh with {@code IllegalStateException: No routes
     * registered}; post-fix the context loads cleanly and the router bean
     * is present (carrying the never-matching empty-registry router).
     *
     * <p>Uses a {@link WebApplicationContextRunner} rather than a full
     * {@code @SpringBootTest} so the regression target — the empty-builder
     * rejection by {@code RouterFunctions.Builder.build()} during the
     * {@link RouterFunction} bean's materialisation — is exercised at
     * context refresh without spinning up Tomcat or the native Rust core.
     */
    @Test
    @DisplayName("Context with NO @MeshA2A beans loads cleanly "
        + "(no IllegalStateException: No routes registered)")
    void contextLoads_withoutAnyMeshA2ABeans() {
        new WebApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(MeshAutoConfiguration.class))
            .withUserConfiguration(NoA2ABeansTestConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                assertThat(context).hasBean("meshA2ARegistry");
                MeshA2ARegistry registry = context.getBean(MeshA2ARegistry.class);
                assertThat(registry.hasSurfaces())
                    .as("Pre-condition for this regression: no @MeshA2A "
                        + "surfaces should have been registered")
                    .isFalse();
                // The router bean must still exist (it's what would have
                // crashed RouterFunctionMapping pre-fix); post-fix it is
                // a never-matching RouterFunction.
                assertThat(context).hasBean("meshA2ARouterFunction");
                RouterFunction<?> router = context.getBean(
                    "meshA2ARouterFunction", RouterFunction.class);
                assertThat(router).isNotNull();
            });
    }

    /**
     * Test config providing a no-op {@link MeshRuntime} so the auto-config
     * doesn't try to load the native Rust core during a unit test. NOTE:
     * this config deliberately registers NO {@code @MeshA2A} beans — that's
     * the regression scenario.
     */
    @Configuration
    static class NoA2ABeansTestConfig {

        @Bean
        public MeshRuntime meshRuntime() {
            AgentSpec spec = new AgentSpec();
            spec.setName("no-a2a-test-agent");
            spec.setAgentId("no-a2a-test-agent-00000000");
            return new NoOpMeshRuntime(spec);
        }
    }

    /** Test-only {@link MeshRuntime} that overrides the SmartLifecycle hooks
     *  so the native core never starts. */
    static class NoOpMeshRuntime extends MeshRuntime {
        private volatile boolean running;

        NoOpMeshRuntime(AgentSpec spec) {
            super(spec);
        }

        @Override
        public void start() {
            running = true;
        }

        @Override
        public void stop() {
            running = false;
        }

        @Override
        public boolean isRunning() {
            return running;
        }
    }

    @SuppressWarnings("unchecked")
    private static <T> ObjectProvider<T> emptyProvider(Class<T> type) {
        ObjectProvider<T> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(null);
        return provider;
    }
}
