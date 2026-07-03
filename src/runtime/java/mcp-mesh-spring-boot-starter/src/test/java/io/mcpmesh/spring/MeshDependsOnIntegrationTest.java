package io.mcpmesh.spring;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.SchemaMode;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshDependsOn;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshRouteAutoConfiguration;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.stereotype.Component;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import java.lang.reflect.Field;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Issue #1086: {@code @MeshDependsOn} surfaces mesh capabilities to
 * Spring-managed beans outside {@code @MeshRoute}-annotated controller
 * methods, and the auto-configuration registers a singleton
 * {@link McpMeshTool} bean per declared capability so users can
 * {@code @Qualifier("capability")}-inject the proxy.
 *
 * <p>Mirrors the {@link MeshA2aFlagsTest} fixture pattern — production
 * wiring runs unmodified except the Rust-FFI boot is suppressed by
 * replacing the started {@link MeshRuntime} bean.
 */
@DisplayName("Issue #1086 — @MeshDependsOn registers qualified McpMeshTool beans")
class MeshDependsOnIntegrationTest {

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

    // ---- Fixture beans ----

    @Component
    @MeshDependsOn(@MeshDependency(capability = "test_cap"))
    static class SingleCapConsumer {
    }

    @Configuration
    @MeshAgent(name = "single-cap-agent")
    static class SingleCapAgentConfig {
        @Bean public SingleCapConsumer singleCapConsumer() { return new SingleCapConsumer(); }
    }

    // Two-capability consumer with a @Qualifier-injected constructor
    @Service
    @MeshDependsOn({
        @MeshDependency(capability = "alpha_cap"),
        @MeshDependency(capability = "beta_cap")
    })
    static class TwoCapService {
        final McpMeshTool<?> alpha;
        final McpMeshTool<?> beta;
        TwoCapService(
                @Qualifier("alpha_cap") McpMeshTool<?> alpha,
                @Qualifier("beta_cap") McpMeshTool<?> beta) {
            this.alpha = alpha;
            this.beta = beta;
        }
    }

    @Configuration
    @MeshAgent(name = "two-cap-agent")
    static class TwoCapAgentConfig {
        // Nit2: TwoCapService is registered via a @Bean factory method (NOT
        // component scanning) so this fixture also exercises the
        // factory-method annotation discovery path. The class-level
        // @MeshDependsOn on TwoCapService is picked up by the registrar via
        // resolveBeanClass() — see F4 reorder which puts beanClassName-based
        // resolution first.
        @Bean public TwoCapService twoCapService(
                @Qualifier("alpha_cap") McpMeshTool<?> alpha,
                @Qualifier("beta_cap") McpMeshTool<?> beta) {
            return new TwoCapService(alpha, beta);
        }
    }

    // Field injection target
    @Component
    static class FieldInjectionTarget {
        @Autowired @Qualifier("field_cap")
        McpMeshTool<?> tool;
    }

    @Component
    @MeshDependsOn(@MeshDependency(capability = "field_cap"))
    static class FieldCapDeclarer {}

    @Configuration
    @MeshAgent(name = "field-injection-agent")
    static class FieldInjectionAgentConfig {
        @Bean public FieldInjectionTarget fieldInjectionTarget() { return new FieldInjectionTarget(); }
        @Bean public FieldCapDeclarer fieldCapDeclarer() { return new FieldCapDeclarer(); }
    }

    // Dedup: same capability declared via both @MeshRoute and @MeshDependsOn
    @RestController
    static class RouteController {
        @PostMapping("/route")
        @MeshRoute(dependencies = @MeshDependency(capability = "shared_cap"))
        public String handle() { return "ok"; }
    }

    @Component
    @MeshDependsOn(@MeshDependency(capability = "shared_cap"))
    static class SharedCapDeclarer {}

    @Configuration
    @MeshAgent(name = "dedup-agent")
    static class DedupAgentConfig {
        @Bean public RouteController routeController() { return new RouteController(); }
        @Bean public SharedCapDeclarer sharedCapDeclarer() { return new SharedCapDeclarer(); }
    }

    // Name-conflict guard: user already has a bean named "conflicting_cap"
    @Component
    @MeshDependsOn(@MeshDependency(capability = "conflicting_cap"))
    static class ConflictDeclarer {}

    static class UserOwnedBean {
        // Marker — represents a user-owned bean that happens to share a
        // capability name. The conflict guard must NOT overwrite it.
    }

    @Configuration
    @MeshAgent(name = "conflict-agent")
    static class ConflictAgentConfig {
        @Bean public ConflictDeclarer conflictDeclarer() { return new ConflictDeclarer(); }
        @Bean(name = "conflicting_cap") public UserOwnedBean userOwnedBean() { return new UserOwnedBean(); }
    }

    // Name-conflict + downstream consumer: user owns "conflicting_cap" AND
    // another bean tries to @Qualifier-inject McpMeshTool<?> for it. The
    // context refresh must fail with a useful error.
    @Service
    @MeshDependsOn(@MeshDependency(capability = "conflicting_cap"))
    static class BrokenConsumer {
        @SuppressWarnings("unused")
        final McpMeshTool<?> tool;
        BrokenConsumer(@Qualifier("conflicting_cap") McpMeshTool<?> tool) {
            this.tool = tool;
        }
    }

    @Configuration
    @MeshAgent(name = "conflict-breaks-consumer-agent")
    static class ConflictBreaksConsumerAgentConfig {
        @Bean public BrokenConsumer brokenConsumer(
                @Qualifier("conflicting_cap") McpMeshTool<?> tool) {
            return new BrokenConsumer(tool);
        }
        @Bean(name = "conflicting_cap") public UserOwnedBean userOwnedBean() { return new UserOwnedBean(); }
    }

    // Schema-fields wiring fixture (B1): a class-level @MeshDependsOn with
    // expectedType set to a concrete record and schemaMode = SUBSET. Also
    // carries tags/version (Nit1) so the schema + tag + version propagation
    // path is exercised end-to-end on a single fixture.
    public record SchemaPayload(String id, int weight) {}

    @Component
    @MeshDependsOn(@MeshDependency(
        capability = "schema_cap",
        tags = {"v2", "beta"},
        version = ">=1.0",
        expectedType = SchemaPayload.class,
        schemaMode = SchemaMode.SUBSET))
    static class SchemaCapDeclarer {}

    @Configuration
    @MeshAgent(name = "schema-cap-agent")
    static class SchemaCapAgentConfig {
        @Bean public SchemaCapDeclarer schemaCapDeclarer() { return new SchemaCapDeclarer(); }
    }

    // Typed-deserialization-via-expectedType fixture (I4): no @Qualifier
    // generic type — just the expectedType on the annotation should drive
    // the proxy's return type.
    public record TypedPayload(String name) {}

    @Component
    @MeshDependsOn(@MeshDependency(
        capability = "typed_cap",
        expectedType = TypedPayload.class))
    static class TypedCapDeclarer {}

    @Configuration
    @MeshAgent(name = "typed-cap-agent")
    static class TypedCapAgentConfig {
        @Bean public TypedCapDeclarer typedCapDeclarer() { return new TypedCapDeclarer(); }
    }

    // Issue #1249: a @MeshDependsOn edge marked required=true must carry the
    // flag into the synthetic __mesh_depends_on_deps tool spec; a sibling
    // default edge stays required=false (omitted on the wire).
    @Component
    @MeshDependsOn({
        @MeshDependency(capability = "req_dep_cap", required = true),
        @MeshDependency(capability = "opt_dep_cap")
    })
    static class RequiredCapDeclarer {}

    @Configuration
    @MeshAgent(name = "required-cap-agent")
    static class RequiredCapAgentConfig {
        @Bean public RequiredCapDeclarer requiredCapDeclarer() { return new RequiredCapDeclarer(); }
    }

    // Heartbeat-driven availability
    @Component
    @MeshDependsOn(@MeshDependency(capability = "avail_cap"))
    static class AvailDeclarer {}

    @Configuration
    @MeshAgent(name = "avail-agent")
    static class AvailAgentConfig {
        @Bean public AvailDeclarer availDeclarer() { return new AvailDeclarer(); }
    }

    // F2: producer-side dedup. SelfProducer publishes a @MeshTool capability
    // named "self_cap"; SelfConsumer redundantly declares a @MeshDependsOn
    // on the same capability name. The dependency-fold step
    // (addMeshDependsOnDependencies) must skip self_cap because the agent
    // produces it locally — re-declaring it as a registry dependency is a
    // useless self-edge. The bean-registration step must NOT register an
    // McpMeshTool proxy bean for self_cap either, because the agent
    // dispatches its own producer methods directly without going through
    // the proxy.
    @Component
    static class SelfProducer {
        @MeshTool(capability = "self_cap")
        public String produce(@Param("input") String input) { return input; }
    }

    @Component
    @MeshDependsOn(@MeshDependency(capability = "self_cap"))
    static class SelfConsumer {}

    @Configuration
    @MeshAgent(name = "self-cap-agent")
    static class SelfCapAgentConfig {
        @Bean public SelfProducer selfProducer() { return new SelfProducer(); }
        @Bean public SelfConsumer selfConsumer() { return new SelfConsumer(); }
    }

    // F3: conflicting expectedType across two @MeshDependsOn sites for the
    // same capability name. Context refresh must fail fast with an
    // IllegalStateException carrying both type names — silently dropping
    // one declarer's expectedType would leave the proxy mis-typed for that
    // consumer.
    public record TypeAlpha(String name) {}
    public record TypeBeta(int weight) {}

    @Component
    @MeshDependsOn(@MeshDependency(capability = "conflict_cap", expectedType = TypeAlpha.class))
    static class ConflictTypeAlphaDeclarer {}

    @Component
    @MeshDependsOn(@MeshDependency(capability = "conflict_cap", expectedType = TypeBeta.class))
    static class ConflictTypeBetaDeclarer {}

    @Configuration
    @MeshAgent(name = "conflict-types-agent")
    static class ConflictExpectedTypesAgentConfig {
        @Bean public ConflictTypeAlphaDeclarer alphaDeclarer() { return new ConflictTypeAlphaDeclarer(); }
        @Bean public ConflictTypeBetaDeclarer betaDeclarer() { return new ConflictTypeBetaDeclarer(); }
    }

    // F3 upgrade path: one declarer omits expectedType; another supplies it.
    // The non-null type wins so the registered proxy gets typed
    // deserialisation from the first call.
    public record UpgradePayload(String id) {}

    @Component
    @MeshDependsOn(@MeshDependency(capability = "upgrade_cap"))
    static class UpgradeUntypedDeclarer {}

    @Component
    @MeshDependsOn(@MeshDependency(capability = "upgrade_cap", expectedType = UpgradePayload.class))
    static class UpgradeTypedDeclarer {}

    @Configuration
    @MeshAgent(name = "upgrade-cap-agent")
    static class UpgradeTypeAgentConfig {
        // Order matters: untyped declarer registered first, typed second.
        // The capabilities-map upgrade path replaces the initial null
        // expectedType with UpgradePayload.class.
        @Bean public UpgradeUntypedDeclarer untypedDeclarer() { return new UpgradeUntypedDeclarer(); }
        @Bean public UpgradeTypedDeclarer typedDeclarer() { return new UpgradeTypedDeclarer(); }
    }

    // Cross-source expectedType fixture: @MeshRoute declares the dependency
    // with expectedType, no @MeshDependsOn anywhere. The late-phase
    // registrar registers the McpMeshTool proxy bean for the route's
    // capability — and must thread the expectedType through so a downstream
    // @Qualifier consumer's typed McpMeshTool<Foo> gets a proxy whose
    // returnType is Foo (not null). Without the fix the proxy returnType
    // stays null and the first call deserialises to Map<String, Object>.
    public record RouteTypedResponse(String value) {}

    @RestController
    static class RouteTypedController {
        @PostMapping("/route-typed")
        @MeshRoute(dependencies = @MeshDependency(
            capability = "route_typed_cap",
            expectedType = RouteTypedResponse.class))
        public String handle() { return "ok"; }
    }

    @Configuration
    @MeshAgent(name = "route-typed-agent")
    static class RouteTypedAgentConfig {
        @Bean public RouteTypedController routeTypedController() { return new RouteTypedController(); }
    }

    // Companion cross-source fixture for the @MeshA2A path. Same shape as
    // the @MeshRoute fixture: the dependency's expectedType lives only on
    // the producer-side annotation; the late-phase registrar must propagate
    // it into the qualified McpMeshTool bean's proxy.
    public record A2aTypedResponse(String label) {}

    @Component
    static class A2aTypedSurface {
        @MeshA2A(
            path = "/agents/a2a-typed",
            skillId = "a2a-typed",
            skillName = "A2A Typed",
            dependencies = @MeshDependency(
                capability = "a2a_typed_cap",
                expectedType = A2aTypedResponse.class))
        public Map<String, Object> handle(Map<String, Object> message) {
            return Map.of("ok", true);
        }
    }

    @Configuration
    @MeshAgent(name = "a2a-typed-agent")
    static class A2aTypedAgentConfig {
        @Bean public A2aTypedSurface a2aTypedSurface() { return new A2aTypedSurface(); }
    }

    // Issue #1088: real constructor injection driven purely by a
    // @MeshRoute-declared capability (no @MeshDependsOn anywhere). The
    // early-phase BeanDefinitionRegistryPostProcessor must register the
    // route_typed_cap McpMeshTool bean BEFORE this consumer's constructor is
    // autowired, and the proxy's returnType must reflect the route's
    // expectedType.
    @Service
    static class RouteCapConstructorConsumer {
        final McpMeshTool<RouteTypedResponse> tool;
        RouteCapConstructorConsumer(
                @Qualifier("route_typed_cap") McpMeshTool<RouteTypedResponse> tool) {
            this.tool = tool;
        }
    }

    @Configuration
    @MeshAgent(name = "route-ctor-inject-agent")
    static class RouteConstructorInjectAgentConfig {
        @Bean public RouteTypedController routeTypedController() { return new RouteTypedController(); }
        @Bean public RouteCapConstructorConsumer routeCapConstructorConsumer(
                @Qualifier("route_typed_cap") McpMeshTool<RouteTypedResponse> tool) {
            return new RouteCapConstructorConsumer(tool);
        }
    }

    // Issue #1088: analogous constructor-injection fixture for the @MeshA2A
    // path. Capability declared only on the @MeshA2A surface; a separate
    // @Service constructor-injects the qualified proxy.
    @Service
    static class A2aCapConstructorConsumer {
        final McpMeshTool<A2aTypedResponse> tool;
        A2aCapConstructorConsumer(
                @Qualifier("a2a_typed_cap") McpMeshTool<A2aTypedResponse> tool) {
            this.tool = tool;
        }
    }

    @Configuration
    @MeshAgent(name = "a2a-ctor-inject-agent")
    static class A2aConstructorInjectAgentConfig {
        @Bean public A2aTypedSurface a2aTypedSurface() { return new A2aTypedSurface(); }
        @Bean public A2aCapConstructorConsumer a2aCapConstructorConsumer(
                @Qualifier("a2a_typed_cap") McpMeshTool<A2aTypedResponse> tool) {
            return new A2aCapConstructorConsumer(tool);
        }
    }

    // Issue #1088: name-conflict guard for a @MeshRoute-declared capability.
    // A user @Bean owns the capability name "route_conflict_cap"; the
    // early-phase registrar must NOT overwrite it and must emit the ERROR
    // diagnostic naming @MeshRoute as the source.
    @RestController
    static class RouteConflictController {
        @PostMapping("/route-conflict")
        @MeshRoute(dependencies = @MeshDependency(capability = "route_conflict_cap"))
        public String handle() { return "ok"; }
    }

    @Configuration
    @MeshAgent(name = "route-conflict-agent")
    static class RouteConflictAgentConfig {
        @Bean public RouteConflictController routeConflictController() { return new RouteConflictController(); }
        @Bean(name = "route_conflict_cap") public UserOwnedBean userOwnedBean() { return new UserOwnedBean(); }
    }

    private final WebApplicationContextRunner baseRunner = new WebApplicationContextRunner()
        .withConfiguration(AutoConfigurations.of(MeshAutoConfiguration.class,
            MeshRouteAutoConfiguration.class))
        .withUserConfiguration(CommonTestConfig.class);

    @Test
    @DisplayName("@MeshDependsOn registers a McpMeshTool bean named by the capability")
    void registersBeanNamedByCapability() {
        baseRunner
            .withUserConfiguration(SingleCapAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                assertThat(context.containsBean("test_cap"))
                    .as("singleton bean named 'test_cap' must be registered")
                    .isTrue();
                Object bean = context.getBean("test_cap");
                assertThat(bean)
                    .as("'test_cap' must be an McpMeshTool proxy")
                    .isInstanceOf(McpMeshTool.class);

                // And the synthetic tool must reach the heartbeat catalog.
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
                boolean hasSynthetic = spec.getTools().stream()
                    .anyMatch(t -> "__mesh_depends_on_deps".equals(t.getCapability()));
                assertThat(hasSynthetic)
                    .as("synthetic __mesh_depends_on_deps tool must be present")
                    .isTrue();

                // Issue #1158: a tag-less dependency must keep the JSON-array
                // default — an empty string would fail the Rust core's JSON
                // parse and degrade to "no tag constraint".
                AgentSpec.DependencySpec dep = spec.getTools().stream()
                    .filter(t -> "__mesh_depends_on_deps".equals(t.getCapability()))
                    .flatMap(t -> t.getDependencies().stream())
                    .filter(d -> "test_cap".equals(d.getCapability()))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError(
                        "test_cap dependency missing from __mesh_depends_on_deps tool"));
                assertThat(dep.getTags())
                    .as("empty tags must serialise as the JSON-array default '[]'")
                    .isEqualTo("[]");
            });
    }

    @Test
    @DisplayName("@Qualifier constructor-injection resolves the proxy")
    void qualifierConstructorInjection() {
        baseRunner
            .withUserConfiguration(TwoCapAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                TwoCapService svc = context.getBean(TwoCapService.class);
                assertThat(svc.alpha)
                    .as("alpha proxy must be injected via @Qualifier")
                    .isNotNull();
                assertThat(svc.beta)
                    .as("beta proxy must be injected via @Qualifier")
                    .isNotNull();
                assertThat(svc.alpha.getCapability()).isEqualTo("alpha_cap");
                assertThat(svc.beta.getCapability()).isEqualTo("beta_cap");
            });
    }

    @Test
    @DisplayName("@Autowired + @Qualifier field injection resolves the proxy")
    void qualifierFieldInjection() {
        baseRunner
            .withUserConfiguration(FieldInjectionAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                FieldInjectionTarget target = context.getBean(FieldInjectionTarget.class);
                assertThat(target.tool)
                    .as("field 'tool' must be wired with the 'field_cap' proxy")
                    .isNotNull();
                assertThat(target.tool.getCapability()).isEqualTo("field_cap");
            });
    }

    @Test
    @DisplayName("Proxy transitions to available when MeshDependencyInjector receives an endpoint")
    void proxyReachesAvailableOnEndpointUpdate() {
        baseRunner
            .withUserConfiguration(AvailAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                McpMeshTool<?> proxy = (McpMeshTool<?>) context.getBean("avail_cap");
                assertThat(proxy.isAvailable())
                    .as("proxy starts in unavailable state")
                    .isFalse();

                // Simulate the heartbeat-driven path:
                // MeshEventProcessor.handleDependencyAvailable() delegates to
                // MeshDependencyInjector.updateToolDependency(). Calling the
                // injector directly avoids spinning up the native event loop.
                MeshDependencyInjector injector = context.getBean(MeshDependencyInjector.class);
                injector.updateToolDependency("avail_cap", "http://localhost:9999", "avail_fn");

                assertThat(proxy.isAvailable())
                    .as("after endpoint update the same bean instance reports available")
                    .isTrue();
                assertThat(proxy.getEndpoint()).isEqualTo("http://localhost:9999");
            });
    }

    @Test
    @DisplayName("Dedup: same capability via @MeshRoute and @MeshDependsOn registers one bean")
    void dedupAcrossSources() {
        baseRunner
            .withUserConfiguration(DedupAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                assertThat(context.containsBean("shared_cap"))
                    .as("'shared_cap' must be registered as a McpMeshTool bean")
                    .isTrue();
                // Only one bean of that name: getBeansOfType on McpMeshTool
                // filtered to name 'shared_cap' should resolve uniquely.
                assertThat(context.getBean("shared_cap")).isInstanceOf(McpMeshTool.class);

                // The synthetic __mesh_depends_on_deps tool should NOT
                // contain 'shared_cap' — it's already declared by the
                // @MeshRoute synthetic tool, so dedup drops it.
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
                boolean dependsOnHasShared = spec.getTools().stream()
                    .filter(t -> "__mesh_depends_on_deps".equals(t.getCapability()))
                    .flatMap(t -> t.getDependencies().stream())
                    .anyMatch(d -> "shared_cap".equals(d.getCapability()));
                assertThat(dependsOnHasShared)
                    .as("dedup: 'shared_cap' must not appear in __mesh_depends_on_deps when also on a route")
                    .isFalse();

                // Route tool DOES carry it.
                boolean routeHasShared = spec.getTools().stream()
                    .filter(t -> "__mesh_route_deps".equals(t.getCapability()))
                    .flatMap(t -> t.getDependencies().stream())
                    .anyMatch(d -> "shared_cap".equals(d.getCapability()));
                assertThat(routeHasShared)
                    .as("'shared_cap' must remain on __mesh_route_deps")
                    .isTrue();
            });
    }

    @Test
    @DisplayName("Name-conflict guard: user-owned bean wins, no overwrite")
    void nameConflictGuardPreservesUserBean() {
        baseRunner
            .withUserConfiguration(ConflictAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                Object bean = context.getBean("conflicting_cap");
                assertThat(bean)
                    .as("user-owned bean must NOT be overwritten by the McpMeshTool proxy")
                    .isInstanceOf(UserOwnedBean.class);
            });
    }

    @Test
    @DisplayName("B2/W5: name-conflict breaks @Qualifier consumer + logs actionable ERROR")
    void nameConflictBreaksConsumerInjection() {
        LogCapture capture = LogCapture.attach(MeshCapabilityBeanRegistrar.class);
        try {
            baseRunner
                .withUserConfiguration(ConflictBreaksConsumerAgentConfig.class)
                .run(context -> {
                    // Refresh must fail — user-owned bean is not an McpMeshTool,
                    // so the @Qualifier-injected consumer cannot be satisfied.
                    assertThat(context).hasFailed();
                    Throwable failure = context.getStartupFailure();
                    assertThat(failure)
                        .as("context startup must fail when a non-McpMeshTool bean shadows the capability name")
                        .isNotNull();
                    // The root cause should mention the consumer's required McpMeshTool type
                    // OR the bean name 'conflicting_cap' — both are diagnostic.
                    String message = collectMessages(failure);
                    assertThat(message)
                        .as("failure must reference McpMeshTool or 'conflicting_cap'")
                        .containsAnyOf("McpMeshTool", "conflicting_cap");
                });

            // ERROR log must have been emitted with the conflicting class + declarer list.
            assertThat(capture.events)
                .as("MeshCapabilityBeanRegistrar must emit at least one ERROR log")
                .anyMatch(e -> "ERROR".equals(e.level)
                    && e.message.contains("conflicting_cap")
                    && e.message.contains("UserOwnedBean")
                    && e.message.contains("BrokenConsumer"));
        } finally {
            capture.detach();
        }
    }

    @Test
    @DisplayName("B1: expectedType + schemaMode propagate to DependencySpec for @MeshDependsOn")
    void schemaFieldsPropagateForMeshDependsOn() {
        baseRunner
            .withUserConfiguration(SchemaCapAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
                AgentSpec.DependencySpec dep = spec.getTools().stream()
                    .filter(t -> "__mesh_depends_on_deps".equals(t.getCapability()))
                    .flatMap(t -> t.getDependencies().stream())
                    .filter(d -> "schema_cap".equals(d.getCapability()))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError(
                        "schema_cap dependency missing from __mesh_depends_on_deps tool"));

                assertThat(dep.getExpectedSchemaCanonical())
                    .as("expectedSchemaCanonical must be populated for @MeshDependsOn with expectedType")
                    .isNotNull()
                    .isNotEmpty();
                assertThat(dep.getExpectedSchemaHash())
                    .as("expectedSchemaHash must be populated alongside canonical schema")
                    .isNotNull()
                    .isNotEmpty();
                assertThat(dep.getMatchMode())
                    .as("matchMode must reflect the requested SUBSET mode")
                    .isEqualTo("subset");
                // Nit1: tags/version on the annotation must propagate into the
                // synthetic dependency spec — same serialisation as the
                // @MeshRoute / @MeshA2A paths (JSON-array string, version
                // string copied through verbatim). Issue #1158: the Rust core
                // JSON-parses this field; comma-joined strings silently
                // degrade to "no tag constraint".
                assertThat(dep.getTags())
                    .as("tags from @MeshDependency must serialise as a JSON-array string")
                    .isEqualTo("[\"v2\",\"beta\"]");
                assertThat(dep.getVersion())
                    .as("version constraint must propagate verbatim")
                    .isEqualTo(">=1.0");
            });
    }

    @Test
    @DisplayName("#1249: required flag propagates to DependencySpec for @MeshDependsOn")
    void requiredFlagPropagatesForMeshDependsOn() {
        baseRunner
            .withUserConfiguration(RequiredCapAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();
                AgentSpec.DependencySpec req = spec.getTools().stream()
                    .filter(t -> "__mesh_depends_on_deps".equals(t.getCapability()))
                    .flatMap(t -> t.getDependencies().stream())
                    .filter(d -> "req_dep_cap".equals(d.getCapability()))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError(
                        "req_dep_cap dependency missing from __mesh_depends_on_deps tool"));
                AgentSpec.DependencySpec opt = spec.getTools().stream()
                    .filter(t -> "__mesh_depends_on_deps".equals(t.getCapability()))
                    .flatMap(t -> t.getDependencies().stream())
                    .filter(d -> "opt_dep_cap".equals(d.getCapability()))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError(
                        "opt_dep_cap dependency missing from __mesh_depends_on_deps tool"));

                assertThat(req.isRequired())
                    .as("required=true @MeshDependsOn edge must carry required into the spec")
                    .isTrue();
                assertThat(opt.isRequired())
                    .as("default @MeshDependsOn edge must stay required=false")
                    .isFalse();
            });
    }

    @Test
    @DisplayName("I4: expectedType on @MeshDependency pre-sets the proxy's return type")
    void expectedTypePreSetsProxyReturnType() throws Exception {
        baseRunner
            .withUserConfiguration(TypedCapAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                Object bean = context.getBean("typed_cap");
                assertThat(bean).isInstanceOf(McpMeshToolProxy.class);
                McpMeshToolProxy<?> proxy = (McpMeshToolProxy<?>) bean;

                // The proxy's returnType field is package-private; use a
                // reflective read so we don't widen the public surface for
                // a test-only assertion.
                Field f = McpMeshToolProxy.class.getDeclaredField("returnType");
                f.setAccessible(true);
                Object returnType = f.get(proxy);
                assertThat(returnType)
                    .as("proxy returnType must be wired from @MeshDependency.expectedType")
                    .isEqualTo(TypedPayload.class);
            });
    }

    @Test
    @DisplayName("F2: @MeshDependsOn on a self-produced capability is deduped + no proxy bean registered")
    void producerCapabilityDedupedAgainstMeshDependsOn() {
        baseRunner
            .withUserConfiguration(SelfCapAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                AgentSpec spec = context.getBean(MeshRuntime.class).getAgentSpec();

                // Producer side: self_cap is in the spec as a @MeshTool.
                boolean hasProducer = spec.getTools().stream()
                    .anyMatch(t -> "self_cap".equals(t.getCapability()));
                assertThat(hasProducer)
                    .as("@MeshTool(capability=\"self_cap\") must remain in the spec as a producer")
                    .isTrue();

                // Consumer-side dedup: the synthetic __mesh_depends_on_deps
                // tool must NOT carry self_cap as a dependency. Without F2 it
                // would re-declare the agent's own capability as a registry
                // dependency.
                boolean hasDependencyEntry = spec.getTools().stream()
                    .filter(t -> "__mesh_depends_on_deps".equals(t.getCapability()))
                    .flatMap(t -> t.getDependencies().stream())
                    .anyMatch(d -> "self_cap".equals(d.getCapability()));
                assertThat(hasDependencyEntry)
                    .as("self_cap must not be re-declared as a dependency on __mesh_depends_on_deps")
                    .isFalse();

                // Bean-registration side: the late-phase registrar uses
                // includeProducers=false (F2), so it does not register a
                // duplicate McpMeshTool proxy bean for the agent's own
                // capability. The early-phase
                // BeanDefinitionRegistryPostProcessor still registers a
                // proxy bean for self_cap because @MeshDependsOn declared
                // it — that path is the bean-name-discovery surface and
                // can't pre-scan @MeshTool methods (which haven't been
                // parsed yet at registry-postprocess time). The producer
                // dedup that F2 addresses is the dependency-fold step
                // asserted above; the bean registered here matches the
                // declarer's explicit @MeshDependsOn intent.
                assertThat(context.containsBean("self_cap"))
                    .as("@MeshDependsOn declared self_cap → an McpMeshTool bean is registered "
                        + "for the consumer's @Qualifier injection")
                    .isTrue();
            });
    }

    @Test
    @DisplayName("F3: conflicting expectedType across declarers fails fast with both type names")
    void conflictingExpectedTypesAcrossDeclarersFailsFast() {
        baseRunner
            .withUserConfiguration(ConflictExpectedTypesAgentConfig.class)
            .run(context -> {
                assertThat(context).hasFailed();
                Throwable failure = context.getStartupFailure();
                assertThat(failure)
                    .as("conflicting expectedType across @MeshDependsOn sites must fail context refresh")
                    .isNotNull();
                String message = collectMessages(failure);
                assertThat(message)
                    .as("failure must reference the capability and both conflicting type names")
                    .contains("conflict_cap")
                    .contains(TypeAlpha.class.getName())
                    .contains(TypeBeta.class.getName());
            });
    }

    @Test
    @DisplayName("F3: upgrade path — null expectedType is replaced by a later non-null declaration")
    void expectedTypeUpgradePathWiresProxyReturnType() throws Exception {
        baseRunner
            .withUserConfiguration(UpgradeTypeAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                Object bean = context.getBean("upgrade_cap");
                assertThat(bean).isInstanceOf(McpMeshToolProxy.class);
                McpMeshToolProxy<?> proxy = (McpMeshToolProxy<?>) bean;

                // Same reflective read pattern as expectedTypePreSetsProxyReturnType:
                // the upgrade path must replace the initial null with the
                // later declarer's non-null type so typed deserialisation
                // works from the first call.
                Field f = McpMeshToolProxy.class.getDeclaredField("returnType");
                f.setAccessible(true);
                Object returnType = f.get(proxy);
                assertThat(returnType)
                    .as("proxy returnType must reflect the second declarer's expectedType "
                        + "(upgrade from null wins)")
                    .isEqualTo(UpgradePayload.class);
            });
    }

    @Test
    @DisplayName("expectedType on @MeshRoute flows to the qualified McpMeshTool bean")
    void expectedTypeFromMeshRouteFlowsToQualifiedBean() throws Exception {
        baseRunner
            .withUserConfiguration(RouteTypedAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                Object bean = context.getBean("route_typed_cap");
                assertThat(bean)
                    .as("late-phase registrar must register a proxy bean for the @MeshRoute-declared capability")
                    .isInstanceOf(McpMeshToolProxy.class);
                McpMeshToolProxy<?> proxy = (McpMeshToolProxy<?>) bean;

                // Reflective read of the proxy's returnType field — same
                // assertion pattern as expectedTypePreSetsProxyReturnType.
                // Without the fix, getToolProxy() in the late-phase registrar
                // is called without expectedType, so the proxy's returnType
                // stays null and a downstream @Qualifier consumer gets
                // Map<String, Object> instead of RouteTypedResponse.
                Field f = McpMeshToolProxy.class.getDeclaredField("returnType");
                f.setAccessible(true);
                Object returnType = f.get(proxy);
                assertThat(returnType)
                    .as("proxy returnType must reflect expectedType declared on the @MeshRoute @MeshDependency")
                    .isEqualTo(RouteTypedResponse.class);
            });
    }

    @Test
    @DisplayName("expectedType on @MeshA2A flows to the qualified McpMeshTool bean")
    void expectedTypeFromMeshA2AFlowsToQualifiedBean() throws Exception {
        baseRunner
            .withUserConfiguration(A2aTypedAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                Object bean = context.getBean("a2a_typed_cap");
                assertThat(bean)
                    .as("late-phase registrar must register a proxy bean for the @MeshA2A-declared capability")
                    .isInstanceOf(McpMeshToolProxy.class);
                McpMeshToolProxy<?> proxy = (McpMeshToolProxy<?>) bean;

                Field f = McpMeshToolProxy.class.getDeclaredField("returnType");
                f.setAccessible(true);
                Object returnType = f.get(proxy);
                assertThat(returnType)
                    .as("proxy returnType must reflect expectedType declared on the @MeshA2A @MeshDependency")
                    .isEqualTo(A2aTypedResponse.class);
            });
    }

    @Test
    @DisplayName("#1088: @MeshRoute-declared capability resolves @Qualifier constructor injection")
    void meshRouteCapabilityResolvesConstructorInjection() throws Exception {
        baseRunner
            .withUserConfiguration(RouteConstructorInjectAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                RouteCapConstructorConsumer consumer =
                    context.getBean(RouteCapConstructorConsumer.class);
                assertThat(consumer)
                    .as("consumer bean must be created with the @MeshRoute capability proxy injected")
                    .isNotNull();
                assertThat(consumer.tool)
                    .as("route_typed_cap proxy must be constructor-injected")
                    .isNotNull();
                assertThat(consumer.tool.getCapability()).isEqualTo("route_typed_cap");

                // The early-phase registrar must thread expectedType from the
                // @MeshRoute @MeshDependency into the proxy's returnType.
                Object bean = context.getBean("route_typed_cap");
                assertThat(bean).isInstanceOf(McpMeshToolProxy.class);
                Field f = McpMeshToolProxy.class.getDeclaredField("returnType");
                f.setAccessible(true);
                assertThat(f.get(bean))
                    .as("injected proxy returnType must reflect @MeshRoute expectedType")
                    .isEqualTo(RouteTypedResponse.class);
            });
    }

    @Test
    @DisplayName("#1088: @MeshA2A-declared capability resolves @Qualifier constructor injection")
    void meshA2ACapabilityResolvesConstructorInjection() throws Exception {
        baseRunner
            .withUserConfiguration(A2aConstructorInjectAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                A2aCapConstructorConsumer consumer =
                    context.getBean(A2aCapConstructorConsumer.class);
                assertThat(consumer)
                    .as("consumer bean must be created with the @MeshA2A capability proxy injected")
                    .isNotNull();
                assertThat(consumer.tool)
                    .as("a2a_typed_cap proxy must be constructor-injected")
                    .isNotNull();
                assertThat(consumer.tool.getCapability()).isEqualTo("a2a_typed_cap");

                Object bean = context.getBean("a2a_typed_cap");
                assertThat(bean).isInstanceOf(McpMeshToolProxy.class);
                Field f = McpMeshToolProxy.class.getDeclaredField("returnType");
                f.setAccessible(true);
                assertThat(f.get(bean))
                    .as("injected proxy returnType must reflect @MeshA2A expectedType")
                    .isEqualTo(A2aTypedResponse.class);
            });
    }

    @Test
    @DisplayName("#1088: name-conflict guard for @MeshRoute capability preserves user bean + logs ERROR")
    void meshRouteCapabilityNameConflictPreservesUserBean() {
        LogCapture capture = LogCapture.attach(MeshCapabilityBeanRegistrar.class);
        try {
            baseRunner
                .withUserConfiguration(RouteConflictAgentConfig.class)
                .run(context -> {
                    assertThat(context).hasNotFailed();
                    Object bean = context.getBean("route_conflict_cap");
                    assertThat(bean)
                        .as("user-owned bean must NOT be overwritten by an McpMeshTool proxy")
                        .isInstanceOf(UserOwnedBean.class);
                });

            // ERROR diagnostic must fire naming @MeshRoute as the source.
            assertThat(capture.events)
                .as("MeshCapabilityBeanRegistrar must emit an ERROR naming @MeshRoute as the source")
                .anyMatch(e -> "ERROR".equals(e.level)
                    && e.message.contains("route_conflict_cap")
                    && e.message.contains("@MeshRoute"));
        } finally {
            capture.detach();
        }
    }

    @Test
    @DisplayName("Nit2: @MeshDependsOn on a class registered via @Bean factory method resolves @Qualifier proxies")
    void qualifierConstructorInjection_FactoryMethodPath() {
        // The existing qualifierConstructorInjection test already wires
        // TwoCapService via a @Bean factory method (after F4 the workaround
        // @Component TwoCapDeclarer was removed). This test makes the
        // factory-method path explicit by asserting the alpha_cap/beta_cap
        // McpMeshTool beans exist in the context — proves the
        // BeanDefinitionRegistryPostProcessor discovered the class-level
        // @MeshDependsOn annotation on the factory-method-produced bean.
        baseRunner
            .withUserConfiguration(TwoCapAgentConfig.class)
            .run(context -> {
                assertThat(context).hasNotFailed();
                assertThat(context.containsBean("alpha_cap"))
                    .as("alpha_cap proxy bean must be registered from factory-method-discovered "
                        + "@MeshDependsOn on TwoCapService")
                    .isTrue();
                assertThat(context.containsBean("beta_cap"))
                    .as("beta_cap proxy bean must be registered from factory-method-discovered "
                        + "@MeshDependsOn on TwoCapService")
                    .isTrue();
                assertThat(context.getBean("alpha_cap")).isInstanceOf(McpMeshTool.class);
                assertThat(context.getBean("beta_cap")).isInstanceOf(McpMeshTool.class);

                TwoCapService svc = context.getBean(TwoCapService.class);
                assertThat(svc.alpha)
                    .as("alpha proxy must be constructor-injected even though TwoCapService "
                        + "was produced by a @Bean factory method")
                    .isNotNull();
                assertThat(svc.beta).isNotNull();
            });
    }

    /**
     * Collect the failure message and the messages of its causal chain so
     * tests can assert against any link in the chain without depending on
     * Spring's exact wrapper exception hierarchy.
     */
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

    /**
     * Minimal Logback appender that records the level + formatted message
     * of every event emitted by a target logger. Used to assert the
     * registrar's conflict ERROR is actionable (carries the conflicting
     * bean's class name and every declarer class).
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
                    events.add(new LogEvent(
                        event.getLevel().toString(), event.getFormattedMessage()));
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
