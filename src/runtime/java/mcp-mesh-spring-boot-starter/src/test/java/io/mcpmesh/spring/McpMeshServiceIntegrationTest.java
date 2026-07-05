package io.mcpmesh.spring;

import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.spring.sv.Views;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshDependsOn;
import io.mcpmesh.spring.web.MeshRouteAutoConfiguration;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshServiceUnavailableException;
import io.mcpmesh.types.MeshToolUnavailableException;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.beans.factory.support.BeanDefinitionRegistry;
import org.springframework.boot.autoconfigure.AutoConfigurationPackages;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Proxy;
import java.lang.reflect.Type;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Flow;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.entry;

/**
 * RFC #1280 (Phase 1): {@link io.mcpmesh.McpMeshService} service views. A
 * consumer-owned typed interface whose abstract methods each bind one capability
 * via {@link io.mcpmesh.Selector}; a facade bean is registered per interface and
 * each method delegates to its own per-capability proxy.
 *
 * <p>Mirrors {@link MeshDependsOnIntegrationTest}: the Rust-FFI boot is
 * suppressed by neutralizing the {@link MeshRuntime} bean. Discovery is
 * classpath-scanning scoped to {@link AutoConfigurationPackages}, so each test
 * registers the fixture base package via an initializer.
 */
@DisplayName("RFC #1280 — @McpMeshService service views")
class McpMeshServiceIntegrationTest {

    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    // ---- Rust-FFI neutralizer (copied from MeshDependsOnIntegrationTest) ----

    static class MeshRuntimeNeutralizer implements BeanPostProcessor {
        @Override
        public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
            if (bean instanceof MeshRuntime real && !(bean instanceof NoOpRuntime)) {
                return new NoOpRuntime(real.getAgentSpec());
            }
            return bean;
        }
    }

    static class NoOpRuntime extends MeshRuntime {
        NoOpRuntime(AgentSpec spec) {
            super(spec);
        }
        @Override public void start() { /* skip native FFI */ }
        @Override public void stop() { /* no-op */ }
        @Override public boolean isRunning() { return false; }
    }

    @Configuration
    static class CommonTestConfig {
        @Bean
        public MeshRuntimeNeutralizer meshRuntimeNeutralizer() {
            return new MeshRuntimeNeutralizer();
        }
    }

    // ---- Recording injector: observes delegation type + param mapping -------

    static class RecordingTool implements McpMeshTool<Object> {
        final String capability;
        volatile boolean available = true;
        volatile String lastMethod;
        volatile Object[] lastArgs;
        volatile Map<String, Object> lastMap;

        RecordingTool(String capability) {
            this.capability = capability;
        }

        @Override public Object call() { lastMethod = "call0"; return null; }
        @Override public Object call(Map<String, Object> params) { lastMethod = "callMap"; lastMap = params; return null; }
        @Override public Object call(Object... args) { lastMethod = "callVarargs"; lastArgs = args; return null; }
        @Override public CompletableFuture<Object> callAsync() { lastMethod = "callAsync0"; return CompletableFuture.completedFuture(null); }
        @Override public CompletableFuture<Object> callAsync(Map<String, Object> params) { lastMethod = "callAsyncMap"; lastMap = params; return CompletableFuture.completedFuture(null); }
        @Override public CompletableFuture<Object> callAsync(Object... args) { lastMethod = "callAsyncVarargs"; lastArgs = args; return CompletableFuture.completedFuture(null); }
        @Override public String getCapability() { return capability; }
        @Override public String getEndpoint() { return "recording"; }
        @Override public String getFunctionName() { return "fn"; }
        @Override public boolean isAvailable() { return available; }
        @Override public Flow.Publisher<String> stream(Map<String, Object> params) {
            lastMethod = "streamMap"; lastMap = params;
            return subscriber -> subscriber.onSubscribe(new Flow.Subscription() {
                @Override public void request(long n) { subscriber.onComplete(); }
                @Override public void cancel() { }
            });
        }
    }

    static class RecordingInjector extends MeshDependencyInjector {
        final Map<String, RecordingTool> tools = new ConcurrentHashMap<>();
        final Map<String, Type> requestedTypes = new ConcurrentHashMap<>();

        @Override
        public McpMeshTool getToolProxy(String capability) {
            return tools.computeIfAbsent(capability, RecordingTool::new);
        }

        @Override
        public McpMeshTool getToolProxy(String capability, Type returnType) {
            requestedTypes.put(capability, returnType);
            return getToolProxy(capability);
        }
    }

    /**
     * Recording injector whose per-capability tools start UNAVAILABLE and whose
     * {@code updateToolDependency} both flips availability and counts down the
     * settle latch — mirrors the real injector's contract so the floor-wait
     * (settle grace) path can be exercised without HTTP.
     */
    static class SettleAwareRecordingInjector extends MeshDependencyInjector {
        final Map<String, RecordingTool> tools = new ConcurrentHashMap<>();

        @Override
        public McpMeshTool getToolProxy(String capability) {
            return tools.computeIfAbsent(capability, c -> {
                RecordingTool t = new RecordingTool(c);
                t.available = false;
                return t;
            });
        }

        @Override
        public McpMeshTool getToolProxy(String capability, Type returnType) {
            return getToolProxy(capability);
        }

        @Override
        public void updateToolDependency(String capability, String endpoint, String functionName) {
            RecordingTool t = (RecordingTool) getToolProxy(capability);
            t.available = endpoint != null;
            if (endpoint != null) {
                MeshSettleState.getInstance().markResolved(capability);
            }
        }
    }

    @Configuration
    @MeshAgent(name = "sv-floor-wait-agent")
    static class FloorWaitConfig {
        @Bean public MeshDependencyInjector meshDependencyInjector() { return new SettleAwareRecordingInjector(); }
    }

    // ---- Test configs -------------------------------------------------------

    static class LlmConsumer {
        final Views.LlmService service;
        LlmConsumer(Views.LlmService service) {
            this.service = service;
        }
    }

    @Configuration
    @MeshAgent(name = "sv-recording-agent")
    static class RecordingAgentConfig {
        @Bean public MeshDependencyInjector meshDependencyInjector() { return new RecordingInjector(); }
        @Bean public LlmConsumer llmConsumer(Views.LlmService service) { return new LlmConsumer(service); }
    }

    @Configuration
    @MeshAgent(name = "sv-agent")
    static class PlainAgentConfig {
    }

    @MeshDependsOn(@MeshDependency(capability = "rw_cap"))
    static class RwDependsOn {
    }

    @Configuration
    @MeshAgent(name = "sv-required-wins-agent")
    static class RequiredWinsAgentConfig {
        @Bean public RwDependsOn rwDependsOn() { return new RwDependsOn(); }
    }

    /** Recording injector only — no view-specific consumer beans. */
    @Configuration
    @MeshAgent(name = "sv-recording-only-agent")
    static class RecordingInjectorConfig {
        @Bean public MeshDependencyInjector meshDependencyInjector() { return new RecordingInjector(); }
    }

    // Self-produced capability (#6): @MeshTool producer whose capability a view binds.
    static class SelfProducer {
        @MeshTool(capability = "self.produced")
        public String produce(@Param("x") String x) { return x; }
    }

    @Configuration
    @MeshAgent(name = "sv-self-agent")
    static class SelfProducedConfig {
        @Bean public SelfProducer selfProducer() { return new SelfProducer(); }
    }

    // Cross-source conflict (#5): @MeshDependsOn declares xs.cap with a type.
    @MeshDependsOn(@MeshDependency(capability = "xs.cap",
        expectedType = io.mcpmesh.spring.svxsrc.XsrcViews.TypeY.class))
    static class XsrcConflictDependsOn {
    }

    @Configuration
    @MeshAgent(name = "sv-xsrc-conflict-agent")
    static class XsrcConflictConfig {
        @Bean public XsrcConflictDependsOn xsrcConflictDependsOn() { return new XsrcConflictDependsOn(); }
    }

    @MeshDependsOn(@MeshDependency(capability = "xs.cap",
        expectedType = io.mcpmesh.spring.svxsrc.XsrcViews.TypeX.class))
    static class XsrcMatchDependsOn {
    }

    @Configuration
    @MeshAgent(name = "sv-xsrc-match-agent")
    static class XsrcMatchConfig {
        @Bean public XsrcMatchDependsOn xsrcMatchDependsOn() { return new XsrcMatchDependsOn(); }
    }

    // Facade name-conflict (#name-conflict policy): user owns "llmService".
    static class UserOwnedBean {
    }

    @Configuration
    @MeshAgent(name = "sv-name-conflict-agent")
    static class NameConflictConfig {
        @Bean(name = "llmService") public UserOwnedBean llmService() { return new UserOwnedBean(); }
    }

    @Configuration
    @MeshAgent(name = "sv-multi-agent")
    static class MultiAgentConfig {
    }

    // ---- Runner helpers -----------------------------------------------------

    private WebApplicationContextRunner runnerFor(String basePackage, Class<?>... userConfigs) {
        WebApplicationContextRunner runner = new WebApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(MeshAutoConfiguration.class,
                MeshRouteAutoConfiguration.class))
            .withInitializer(ctx -> AutoConfigurationPackages.register(
                (BeanDefinitionRegistry) ctx.getBeanFactory(), basePackage))
            .withUserConfiguration(CommonTestConfig.class);
        return runner.withUserConfiguration(userConfigs);
    }

    private static AgentSpec.DependencySpec serviceDep(AgentSpec spec, String capability) {
        return spec.getTools().stream()
            .filter(t -> "__mesh_service_deps".equals(t.getCapability()))
            .flatMap(t -> t.getDependencies().stream())
            .filter(d -> capability.equals(d.getCapability()))
            .findFirst()
            .orElseThrow(() -> new AssertionError(
                capability + " missing from __mesh_service_deps tool"));
    }

    // ---- Tests --------------------------------------------------------------

    @Test
    @DisplayName("Facade bean is registered and @Autowired-injectable")
    void facadeBeanRegisteredAndInjectable() {
        runnerFor("io.mcpmesh.spring.sv", RecordingAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            Object bean = context.getBean(Views.LlmService.class);
            assertThat(bean).isNotNull();
            assertThat(Proxy.isProxyClass(bean.getClass()))
                .as("facade must be a JDK proxy").isTrue();
            LlmConsumer consumer = context.getBean(LlmConsumer.class);
            assertThat(consumer.service).as("view must be constructor-injectable").isNotNull();
        });
    }

    @Test
    @DisplayName("Methods delegate to the correct per-capability proxy with the right resolved Type")
    void methodsDelegateWithResolvedTypes() {
        runnerFor("io.mcpmesh.spring.sv", RecordingAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            RecordingInjector injector = (RecordingInjector) context.getBean(MeshDependencyInjector.class);
            Views.LlmService svc = context.getBean(Views.LlmService.class);

            svc.chat(new Views.ChatRequest("hi"));
            assertThat(injector.tools.get("llm.chat").lastMethod).isEqualTo("callVarargs");
            assertThat(injector.requestedTypes.get("llm.chat"))
                .as("sync method resolves the proxy to its return type")
                .isEqualTo(Views.ChatResult.class);

            svc.fetchAsync(new Views.Query("x"));
            assertThat(injector.tools.get("llm.async").lastMethod).isEqualTo("callAsyncVarargs");
            assertThat(injector.requestedTypes.get("llm.async"))
                .as("CompletableFuture<T> resolves the proxy to the unwrapped T")
                .isEqualTo(Views.Item.class);
        });
    }

    @Test
    @DisplayName("Param mapping: 0-arg → call(), single-POJO → call(pojo), multi-@Param → call(map)")
    void paramMappingModes() {
        runnerFor("io.mcpmesh.spring.sv", RecordingAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            RecordingInjector injector = (RecordingInjector) context.getBean(MeshDependencyInjector.class);
            Views.LlmService svc = context.getBean(Views.LlmService.class);

            // 0-arg
            svc.list();
            assertThat(injector.tools.get("llm.list").lastMethod).isEqualTo("call0");

            // single POJO
            Views.ChatRequest req = new Views.ChatRequest("hi");
            svc.chat(req);
            RecordingTool chat = injector.tools.get("llm.chat");
            assertThat(chat.lastMethod).isEqualTo("callVarargs");
            assertThat(chat.lastArgs).containsExactly(req);

            // multi @Param → ordered LinkedHashMap
            svc.lookup("7", "us");
            RecordingTool lookup = injector.tools.get("llm.lookup");
            assertThat(lookup.lastMethod).isEqualTo("callMap");
            assertThat(lookup.lastMap).containsExactly(entry("id", "7"), entry("region", "us"));

            // stream param-map
            svc.streamIt("q1");
            RecordingTool stream = injector.tools.get("llm.stream");
            assertThat(stream.lastMethod).isEqualTo("streamMap");
            assertThat(stream.lastMap).containsExactly(entry("q", "q1"));
        });
    }

    @Test
    @DisplayName("default interface method + toString are handled locally, not as edges")
    void defaultMethodAndToString() {
        runnerFor("io.mcpmesh.spring.sv", RecordingAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            Views.LlmService svc = context.getBean(Views.LlmService.class);
            assertThat(svc.label()).isEqualTo("llm-view");
            assertThat(svc.toString()).contains("LlmService").contains("available");

            // The default method's body is not a capability, so no such edge.
            AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
            boolean hasLabelEdge = spec.getTools().stream()
                .filter(t -> "__mesh_service_deps".equals(t.getCapability()))
                .flatMap(t -> t.getDependencies().stream())
                .anyMatch(d -> d.getCapability() != null && d.getCapability().contains("label"));
            assertThat(hasLabelEdge).isFalse();
        });
    }

    @Test
    @DisplayName("Deterministic expansion: dependencies sorted by method name regardless of declaration order")
    void deterministicExpansion() {
        runnerFor("io.mcpmesh.spring.sv", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
            List<String> detCaps = spec.getTools().stream()
                .filter(t -> "__mesh_service_deps".equals(t.getCapability()))
                .flatMap(t -> t.getDependencies().stream())
                .map(AgentSpec.DependencySpec::getCapability)
                .filter(c -> c.startsWith("det."))
                .toList();
            // Methods declared zeta, yankee, alpha → sorted alpha, yankee, zeta.
            assertThat(detCaps).containsExactly("det.alpha", "det.yankee", "det.zeta");
        });
    }

    @Test
    @DisplayName("Wire serialization: required=true view edge serializes, required=false omitted")
    void wireSerialization() {
        runnerFor("io.mcpmesh.spring.sv", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();

            AgentSpec.DependencySpec req = serviceDep(spec, "wire.req");
            AgentSpec.DependencySpec opt = serviceDep(spec, "wire.opt");
            assertThat(req.isRequired()).isTrue();
            assertThat(opt.isRequired()).isFalse();

            assertThat(MAPPER.writeValueAsString(req))
                .as("required view dep must serialize \"required\":true")
                .contains("\"required\":true");
            assertThat(MAPPER.writeValueAsString(opt))
                .as("optional view dep must OMIT the required field")
                .doesNotContain("required");
        });
    }

    @Test
    @DisplayName("Required-wins: a required view edge upgrades a deduped optional @MeshDependsOn edge")
    void requiredWinsAcrossSources() {
        runnerFor("io.mcpmesh.spring.sv", RequiredWinsAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();

            // rw_cap is folded first via @MeshDependsOn, so the service source
            // dedupes it away — it must NOT be on __mesh_service_deps.
            boolean onService = spec.getTools().stream()
                .filter(t -> "__mesh_service_deps".equals(t.getCapability()))
                .flatMap(t -> t.getDependencies().stream())
                .anyMatch(d -> "rw_cap".equals(d.getCapability()));
            assertThat(onService)
                .as("rw_cap must be deduped off __mesh_service_deps (already on @MeshDependsOn)")
                .isFalse();

            // The surviving @MeshDependsOn edge must be upgraded to required=true.
            AgentSpec.DependencySpec dependsOn = spec.getTools().stream()
                .filter(t -> "__mesh_depends_on_deps".equals(t.getCapability()))
                .flatMap(t -> t.getDependencies().stream())
                .filter(d -> "rw_cap".equals(d.getCapability()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("rw_cap missing from __mesh_depends_on_deps"));
            assertThat(dependsOn.isRequired())
                .as("required view edge must upgrade the deduped optional @MeshDependsOn edge")
                .isTrue();
        });
    }

    @Test
    @DisplayName("minAvailable floor: below floor → MeshServiceUnavailableException on ANY method")
    void floorBelowThrowsServiceUnavailable() {
        runnerFor("io.mcpmesh.spring.sv", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            Views.FloorService floor = context.getBean(Views.FloorService.class);
            // No endpoints resolved → 0/3 available, below the minAvailable=2 floor.
            assertThatThrownBy(floor::alpha)
                .isInstanceOf(MeshServiceUnavailableException.class);
            assertThatThrownBy(floor::charlie)
                .isInstanceOf(MeshServiceUnavailableException.class);
        });
    }

    @Test
    @DisplayName("minAvailable floor: at/above floor → optional-missing method throws only MeshToolUnavailableException")
    void floorSatisfiedDelegatesPerMethod() {
        runnerFor("io.mcpmesh.spring.sv", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            MeshDependencyInjector injector = context.getBean(MeshDependencyInjector.class);
            Views.FloorService floor = context.getBean(Views.FloorService.class);

            // Resolve two of the three methods → 2/3 available == minAvailable.
            injector.updateToolDependency("floor.a", "http://localhost:9", "fn");
            injector.updateToolDependency("floor.b", "http://localhost:9", "fn");

            // Floor satisfied: charlie (still unresolved) throws its OWN
            // tool-unavailable error, NOT the service-level floor error.
            assertThatThrownBy(floor::charlie)
                .isInstanceOf(MeshToolUnavailableException.class)
                .isNotInstanceOf(MeshServiceUnavailableException.class);
        });
    }

    @Test
    @DisplayName("Rebinding: updateToolDependency reflects in the shared proxy the facade uses (stable reference)")
    void rebindingReflectsInFacadeProxy() {
        runnerFor("io.mcpmesh.spring.sv", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            MeshDependencyInjector injector = context.getBean(MeshDependencyInjector.class);
            Views.LlmService svc = context.getBean(Views.LlmService.class);

            // First call caches the shared proxy in the facade handler and
            // creates the injector's per-capability proxy (still unresolved).
            assertThatThrownBy(() -> svc.chat(new Views.ChatRequest("hi")))
                .isInstanceOf(MeshToolUnavailableException.class);

            // The facade resolves llm.chat through the injector's SHARED proxy;
            // rebinding it in place must be visible without any re-injection.
            McpMeshTool<?> shared = injector.getToolProxy("llm.chat");
            injector.updateToolDependency("llm.chat", "http://ep-1", "fn");
            assertThat(shared.isAvailable()).isTrue();
            assertThat(shared.getEndpoint()).isEqualTo("http://ep-1");

            injector.updateToolDependency("llm.chat", "http://ep-2", "fn");
            assertThat(shared.getEndpoint())
                .as("the same proxy instance rebinds in place")
                .isEqualTo("http://ep-2");
        });
    }

    @Test
    @DisplayName("Settle grace: view-method capabilities are registered as declared in MeshSettleState")
    void viewCapabilitiesRegisteredAsDeclared() {
        // registerDeclared populates the declared set regardless of window
        // state, so the suite-wide disabled settle posture is fine — no window
        // arming (which would leak an armed window into sibling tests).
        runnerFor("io.mcpmesh.spring.sv", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            MeshSettleState state = MeshSettleState.getInstance();
            // Capability key space (same as routes / @MeshDependsOn), covering
            // required + optional, sync/async/stream edges alike.
            assertThat(state.isDeclared("llm.chat")).isTrue();
            assertThat(state.isDeclared("llm.vision")).isTrue();
            assertThat(state.isDeclared("llm.stream")).isTrue();
            assertThat(state.isDeclared("floor.a")).isTrue();
            assertThat(state.isDeclared("wire.opt")).isTrue();
        });
    }

    @Test
    @DisplayName("Boot-fail: abstract view method missing @Selector")
    void bootFailMissingSelector() {
        runnerFor("io.mcpmesh.spring.svbad.selector", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("missing")
                .contains("@Selector");
        });
    }

    @Test
    @DisplayName("Boot-fail: 2+ params with a missing @Param")
    void bootFailMixedParams() {
        runnerFor("io.mcpmesh.spring.svbad.params", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("twoArgs")
                .contains("@Param");
        });
    }

    @Test
    @DisplayName("Boot-fail: same capability bound to conflicting resolved types")
    void bootFailConflictingTypes() {
        runnerFor("io.mcpmesh.spring.svbad.conflict", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            String message = collectMessages(context.getStartupFailure());
            assertThat(message)
                .contains("cc.cap")
                .contains("TypeX")
                .contains("TypeY");
        });
    }

    // ---- MED-3: generics / covariance / diamond -----------------------------

    @Test
    @DisplayName("MED-3: generic super-interface resolves the concrete bound type")
    void genericSuperInterfaceResolvesConcreteType() {
        runnerFor("io.mcpmesh.spring.svgen", RecordingInjectorConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            RecordingInjector injector = (RecordingInjector) context.getBean(MeshDependencyInjector.class);
            io.mcpmesh.spring.svgen.GenericViews.GenericView view =
                context.getBean(io.mcpmesh.spring.svgen.GenericViews.GenericView.class);
            view.get();
            assertThat(injector.requestedTypes.get("gen.get"))
                .as("Base<Item> must bind Item, not a TypeVariable/Object")
                .isEqualTo(io.mcpmesh.spring.svgen.GenericViews.Item.class);
        });
    }

    @Test
    @DisplayName("MED-3: covariant override skips the bridge method and binds the specific return")
    void covariantOverrideResolvesConcreteType() {
        runnerFor("io.mcpmesh.spring.svgen", RecordingInjectorConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            RecordingInjector injector = (RecordingInjector) context.getBean(MeshDependencyInjector.class);
            io.mcpmesh.spring.svgen.GenericViews.CovView view =
                context.getBean(io.mcpmesh.spring.svgen.GenericViews.CovView.class);
            view.thing();
            assertThat(injector.requestedTypes.get("cov.thing"))
                .isEqualTo(io.mcpmesh.spring.svgen.GenericViews.Item.class);
        });
    }

    @Test
    @DisplayName("MED-3: diamond inheritance collapses to a single dependency edge")
    void diamondInheritanceSingleBinding() {
        runnerFor("io.mcpmesh.spring.svgen", MultiAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
            long count = spec.getTools().stream()
                .filter(t -> "__mesh_service_deps".equals(t.getCapability()))
                .flatMap(t -> t.getDependencies().stream())
                .filter(d -> "diamond.x".equals(d.getCapability()))
                .count();
            assertThat(count).as("diamond-inherited method must expand once").isEqualTo(1L);
        });
    }

    @Test
    @DisplayName("MED-3: annotated+unannotated diamond dedupe keeps the annotated binding deterministically")
    void mixedAnnotationDiamondKeepsAnnotatedBinding() {
        runnerFor("io.mcpmesh.spring.svgen", MultiAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
            long count = spec.getTools().stream()
                .filter(t -> "__mesh_service_deps".equals(t.getCapability()))
                .flatMap(t -> t.getDependencies().stream())
                .filter(d -> "diamond.mixed".equals(d.getCapability()))
                .count();
            assertThat(count)
                .as("annotated diamond member must survive the dedupe as a single edge")
                .isEqualTo(1L);
        });
    }

    @Test
    @DisplayName("MED-2 fallback: covariant override invoked through a super-interface reference routes correctly")
    void superInterfaceReferenceRoutesCovariantOverride() {
        runnerFor("io.mcpmesh.spring.svgen", RecordingInjectorConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            RecordingInjector injector = (RecordingInjector) context.getBean(MeshDependencyInjector.class);
            io.mcpmesh.spring.svgen.GenericViews.CovView view =
                context.getBean(io.mcpmesh.spring.svgen.GenericViews.CovView.class);
            // Call through the SUPER-interface reference: dispatches CovBase.thing(),
            // whose Method misses the exact binding key — the name+params fallback
            // must resolve it instead of throwing.
            io.mcpmesh.spring.svgen.GenericViews.CovBase ref = view;
            Object result = ref.thing();
            assertThat(result).isNull(); // RecordingTool returns null, but the call routed
            assertThat(injector.tools.get("cov.thing").lastMethod).isEqualTo("call0");
        });
    }

    // ---- MED-1 / MED-4 / MED-7 / MED-8: boot-fail validation -----------------

    @Test
    @DisplayName("MED-1: single unannotated scalar parameter boot-fails")
    void scalarParamBootFail() {
        runnerFor("io.mcpmesh.spring.svbad.scalarparam", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("get").contains("POJO/record").contains("@Param");
        });
    }

    @Test
    @DisplayName("MED-4: @McpMeshService on a class boot-fails")
    void meshServiceOnClassBootFail() {
        runnerFor("io.mcpmesh.spring.svbad.onclass", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("@McpMeshService must be on an interface");
        });
    }

    @Test
    @DisplayName("MED-7: minAvailable exceeding bound-method count boot-fails")
    void unsatisfiableFloorBootFail() {
        runnerFor("io.mcpmesh.spring.svbad.unsatfloor", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("minAvailable").contains("can never be satisfied");
        });
    }

    @Test
    @DisplayName("MED-7: negative minAvailable boot-fails")
    void negativeFloorBootFail() {
        runnerFor("io.mcpmesh.spring.svbad.negfloor", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("minAvailable must be >= 0");
        });
    }

    @Test
    @DisplayName("MED-8: raw CompletableFuture boot-fails")
    void rawFutureBootFail() {
        runnerFor("io.mcpmesh.spring.svbad.rawfuture", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("raw CompletableFuture");
        });
    }

    @Test
    @DisplayName("MED-8: non-CompletableFuture Future/CompletionStage boot-fails")
    void badFutureBootFail() {
        runnerFor("io.mcpmesh.spring.svbad.badfuture", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("must return CompletableFuture<T>");
        });
    }

    @Test
    @DisplayName("MED-8: Flow.Publisher<non-String> boot-fails")
    void badStreamBootFail() {
        runnerFor("io.mcpmesh.spring.svbad.badstream", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("Flow.Publisher<String>");
        });
    }

    @Test
    @DisplayName("MED-4: duplicate @Param names boot-fail")
    void duplicateParamNameBootFail() {
        runnerFor("io.mcpmesh.spring.svbad.duplicateparam", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("get").contains("duplicate @Param name").contains("id");
        });
    }

    @Test
    @DisplayName("Boot-fail: @Selector with a blank capability")
    void blankCapabilityBootFail() {
        runnerFor("io.mcpmesh.spring.svbad.blankcap", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(collectMessages(context.getStartupFailure()))
                .contains("empty").contains("capability");
        });
    }

    // ---- MED-5: cross-source resolved-type conflict --------------------------

    @Test
    @DisplayName("MED-5: view + @MeshDependsOn same capability, different types → boot-fail")
    void crossSourceTypeConflictBootFail() {
        runnerFor("io.mcpmesh.spring.svxsrc", XsrcConflictConfig.class).run(context -> {
            assertThat(context).hasFailed();
            String message = collectMessages(context.getStartupFailure());
            assertThat(message)
                .contains("xs.cap").contains("TypeX").contains("TypeY");
        });
    }

    @Test
    @DisplayName("MED-5: view + @MeshDependsOn same capability, identical type → boots")
    void crossSourceMatchingTypeBoots() {
        runnerFor("io.mcpmesh.spring.svxsrc", XsrcMatchConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
        });
    }

    // ---- MED-6: self-produced capability -------------------------------------

    @Test
    @DisplayName("MED-6: self-produced view edge is deduped with WARN + markResolved")
    void selfProducedCapabilityWarnsAndResolves() {
        LogCapture capture = LogCapture.attach(MeshAutoConfiguration.class);
        try {
            runnerFor("io.mcpmesh.spring.svself", SelfProducedConfig.class).run(context -> {
                assertThat(context).hasNotFailed();
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();

                boolean onService = spec.getTools().stream()
                    .filter(t -> "__mesh_service_deps".equals(t.getCapability()))
                    .flatMap(t -> t.getDependencies().stream())
                    .anyMatch(d -> "self.produced".equals(d.getCapability()));
                assertThat(onService)
                    .as("self-produced capability must not become a registry dependency")
                    .isFalse();

                assertThat(MeshSettleState.getInstance().isResolved("self.produced"))
                    .as("self-produced capability must be markResolved so the eager latch isn't stranded")
                    .isTrue();
            });
            assertThat(capture.events)
                .anyMatch(e -> e.message.contains("self.produced")
                    && e.message.contains("produced by this"));
        } finally {
            capture.detach();
        }
    }

    // ---- MED-2 / MED-10 / MED-11: floor + settle + async + null --------------

    @Test
    @DisplayName("MED-2: floored view waits out the settling window and passes when deps resolve mid-window")
    void floorWaitsThenSatisfiedMidWindow() throws Exception {
        MeshSettleState.resetForTests(10.0);
        try {
            runnerFor("io.mcpmesh.spring.sv", FloorWaitConfig.class).run(context -> {
                assertThat(context).hasNotFailed();
                MeshDependencyInjector injector = context.getBean(MeshDependencyInjector.class);
                Views.FloorService floor = context.getBean(Views.FloorService.class);
                MeshSettleState state = MeshSettleState.getInstance();

                // Run the (blocking) floored call on its own thread so we can
                // deterministically observe it PARKED in the settle wait before
                // resolving — no wall-clock sleep/threshold.
                java.util.concurrent.atomic.AtomicReference<Throwable> error =
                    new java.util.concurrent.atomic.AtomicReference<>();
                Thread caller = new Thread(() -> {
                    try {
                        floor.alpha();
                    } catch (Throwable t) {
                        error.set(t);
                    }
                });
                caller.start();

                // Deterministic signal: the below-floor call must register a
                // settle wait before we resolve anything.
                long deadline = System.currentTimeMillis() + 3000;
                while (state.getWaitCount() < 1 && System.currentTimeMillis() < deadline) {
                    Thread.sleep(5);
                }
                assertThat(state.getWaitCount())
                    .as("the below-floor call must park in the settle wait")
                    .isGreaterThanOrEqualTo(1);
                assertThat(caller.isAlive())
                    .as("the call is still waiting, not failed fast").isTrue();

                // Resolve two methods → floor satisfied → the wait unblocks.
                injector.updateToolDependency("floor.a", "ep", "fn");
                injector.updateToolDependency("floor.b", "ep", "fn");
                caller.join(3000);

                assertThat(caller.isAlive()).as("call must unblock once the floor is met").isFalse();
                assertThat(error.get())
                    .as("floor satisfied via the wait — no service-unavailable error")
                    .isNull();
            });
        } finally {
            MeshSettleState.resetForTests();
        }
    }

    @Test
    @DisplayName("MED-3: async floor check runs off-thread — the caller is not blocked by the settle wait")
    void asyncFloorCheckDoesNotBlockCaller() throws Exception {
        MeshSettleState.resetForTests(10.0);
        try {
            runnerFor("io.mcpmesh.spring.sv", FloorWaitConfig.class).run(context -> {
                assertThat(context).hasNotFailed();
                MeshDependencyInjector injector = context.getBean(MeshDependencyInjector.class);
                Views.FloorService floor = context.getBean(Views.FloorService.class);
                MeshSettleState state = MeshSettleState.getInstance();

                // Below floor + armed window: the async method returns a future
                // IMMEDIATELY (floor wait runs on the common pool), so the caller
                // thread is never blocked.
                CompletableFuture<String> future = floor.deltaAsync();
                assertThat(future.isDone())
                    .as("async method must return before the off-thread floor wait completes")
                    .isFalse();

                // The off-thread floor check parks in the settle wait.
                long deadline = System.currentTimeMillis() + 3000;
                while (state.getWaitCount() < 1 && System.currentTimeMillis() < deadline) {
                    Thread.sleep(5);
                }
                assertThat(state.getWaitCount()).isGreaterThanOrEqualTo(1);

                // Resolve two methods → floor satisfied → future completes.
                injector.updateToolDependency("floor.a", "ep", "fn");
                injector.updateToolDependency("floor.b", "ep", "fn");
                assertThat(future.get(3, java.util.concurrent.TimeUnit.SECONDS)).isNull();
            });
        } finally {
            MeshSettleState.resetForTests();
        }
    }

    @Test
    @DisplayName("MED-10: async floor breach surfaces as a failed future, not a synchronous throw")
    void asyncFloorBreachReturnsFailedFuture() {
        runnerFor("io.mcpmesh.spring.sv", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            Views.FloorService floor = context.getBean(Views.FloorService.class);
            CompletableFuture<String> future = floor.deltaAsync();
            assertThat(future).isCompletedExceptionally();
            assertThatThrownBy(future::join).hasCauseInstanceOf(MeshServiceUnavailableException.class);
        });
    }

    @Test
    @DisplayName("MED-11: null single-POJO argument throws IllegalArgumentException naming the method")
    void nullSinglePojoArgThrows() {
        runnerFor("io.mcpmesh.spring.sv", RecordingAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            Views.LlmService svc = context.getBean(Views.LlmService.class);
            assertThatThrownBy(() -> svc.chat(null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("chat");
        });
    }

    // ---- MED-12: consumer-only gate ------------------------------------------

    @Test
    @DisplayName("MED-12: an app whose only mesh surface is a service view boots name-less")
    void consumerOnlyViewBoots() {
        runnerFor("io.mcpmesh.spring.svconsumer", EmptyConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context.getBean(io.mcpmesh.spring.svconsumer.ConsumerViews.ConsumerView.class))
                .isNotNull();
        });
    }

    // ---- Facade proxy semantics + name-conflict ------------------------------

    @Test
    @DisplayName("Name-conflict: user bean wins, but the view's edges + settle keys still register")
    void nameConflictSkipsFacadeButKeepsEdgesAndSettleKeys() {
        runnerFor("io.mcpmesh.spring.sv", NameConflictConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context.getBean("llmService"))
                .as("user-owned bean must not be overwritten by the facade")
                .isInstanceOf(UserOwnedBean.class);
            AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
            assertThat(serviceDep(spec, "llm.chat"))
                .as("skipped facade still contributes its dependency edges").isNotNull();
            assertThat(MeshSettleState.getInstance().isDeclared("llm.chat"))
                .as("skipped facade still declares its settle keys").isTrue();
        });
    }

    @Test
    @DisplayName("Facade proxy equals/hashCode behave by identity")
    void facadeEqualsHashCode() {
        runnerFor("io.mcpmesh.spring.sv", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            Views.LlmService svc = context.getBean(Views.LlmService.class);
            assertThat(svc.equals(svc)).isTrue();
            assertThat(svc.equals("not-a-view")).isFalse();
            assertThat(svc.hashCode()).isEqualTo(svc.hashCode());
        });
    }

    @Test
    @DisplayName("Rebinding: markUnavailable then re-resolve reflects in the shared proxy")
    void rebindThroughMarkUnavailable() {
        runnerFor("io.mcpmesh.spring.sv", PlainAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            MeshDependencyInjector injector = context.getBean(MeshDependencyInjector.class);
            McpMeshTool<?> shared = injector.getToolProxy("llm.chat");

            injector.updateToolDependency("llm.chat", "http://ep-1", "fn");
            assertThat(shared.isAvailable()).isTrue();

            injector.updateToolDependency("llm.chat", null, "fn"); // markUnavailable
            assertThat(shared.isAvailable()).isFalse();

            injector.updateToolDependency("llm.chat", "http://ep-2", "fn"); // re-resolve
            assertThat(shared.isAvailable()).isTrue();
            assertThat(shared.getEndpoint()).isEqualTo("http://ep-2");
        });
    }

    @Test
    @DisplayName("Cross-view determinism: two views expand in interface-name order")
    void crossViewExpansionDeterminism() {
        runnerFor("io.mcpmesh.spring.svmulti", MultiAgentConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
            List<String> caps = spec.getTools().stream()
                .filter(t -> "__mesh_service_deps".equals(t.getCapability()))
                .flatMap(t -> t.getDependencies().stream())
                .map(AgentSpec.DependencySpec::getCapability)
                .filter(c -> c.startsWith("mv."))
                .toList();
            // AlphaView < ZuluView by interface name despite reverse declaration.
            assertThat(caps).containsExactly("mv.alpha", "mv.zulu");
        });
    }

    @Configuration
    static class EmptyConfig {
    }

    // RFC #1280 phase 2: a view used as BOTH a phase-1 bean and a @MeshTool param.
    public static class CoexistTool {
        @MeshTool(capability = "coexist_tool")
        public String run(@Param("x") String x, io.mcpmesh.spring.svtool.ToolViews.CoexistView view) {
            return "ok";
        }
    }

    @Configuration
    @MeshAgent(name = "coexist-agent")
    static class CoexistConfig {
        @Bean public CoexistTool coexistTool() { return new CoexistTool(); }
    }

    @Test
    @DisplayName("Phase 2: bean-path and tool-param usage of the same view coexist independently")
    void beanAndToolParamCoexist() {
        runnerFor("io.mcpmesh.spring.svtool", CoexistConfig.class).run(context -> {
            assertThat(context).hasNotFailed();
            // Phase-1 bean path: the facade bean is registered + injectable.
            assertThat(context.getBean(io.mcpmesh.spring.svtool.ToolViews.CoexistView.class))
                .as("phase-1 facade bean must still exist").isNotNull();
            // Phase-2 tool-param path: the tool's DependencySpec list carries the
            // view edges as ordinary tool deps.
            AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
            List<String> toolDeps = spec.getTools().stream()
                .filter(t -> "coexist_tool".equals(t.getCapability()))
                .flatMap(t -> t.getDependencies().stream())
                .map(AgentSpec.DependencySpec::getCapability)
                .toList();
            assertThat(toolDeps)
                .as("tool-param view edges must be the tool's own dependencies")
                .containsExactly("coexist.one", "coexist.two");
        });
    }

    /**
     * Minimal Logback appender recording level + message for a target logger.
     */
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

    private static String collectMessages(Throwable failure) {
        StringBuilder sb = new StringBuilder();
        Throwable t = failure;
        while (t != null) {
            if (t.getMessage() != null) {
                sb.append(t.getMessage()).append('\n');
            }
            t = t.getCause();
        }
        return sb.toString();
    }
}
