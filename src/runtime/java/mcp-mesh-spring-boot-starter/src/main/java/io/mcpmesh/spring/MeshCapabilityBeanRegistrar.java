package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshDependsOn;
import io.mcpmesh.spring.web.MeshInjectableSlots;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.beans.factory.config.ConfigurableListableBeanFactory;
import org.springframework.beans.factory.support.BeanDefinitionBuilder;
import org.springframework.beans.factory.support.BeanDefinitionRegistry;
import org.springframework.beans.factory.support.BeanDefinitionRegistryPostProcessor;
import org.springframework.core.MethodIntrospector;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.util.ClassUtils;
import org.springframework.util.ReflectionUtils;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Issue #1086: scans bean definitions for class-level {@link MeshDependsOn}
 * annotations and registers a singleton {@link McpMeshTool} bean per
 * declared capability, named by the capability string.
 *
 * <p>Issue #1088: additionally scans each resolved bean class's methods
 * (inherited ones included, #1569) for {@link MeshRoute} and {@link MeshA2A}
 * annotations and feeds
 * their {@code dependencies()} into the same capability map. This lets
 * constructor/field injection of {@code @Qualifier("cap") McpMeshTool<...>}
 * resolve for capabilities declared via {@code @MeshRoute(dependencies=...)}
 * / {@code @MeshA2A(dependencies=...)}, not just {@code @MeshDependsOn}. The
 * {@code MeshRouteRegistry} / {@code MeshA2ARegistry} are NOT consulted here
 * — they are populated by {@link org.springframework.beans.factory.config.BeanPostProcessor}s
 * in {@code postProcessAfterInitialization}, which runs AFTER this
 * registry-postprocess phase, so they are still empty. Reflection on the
 * bean classes is the only data source available this early.
 *
 * <p>Runs as a {@link BeanDefinitionRegistryPostProcessor} so the proxy
 * beans are registered BEFORE user singletons get instantiated. This is
 * essential — a {@code @Service} that declares
 * {@code @Autowired @Qualifier("cap") McpMeshTool<...> tool} would fail
 * with {@code NoSuchBeanDefinitionException} if the proxy bean weren't
 * available at autowire time.
 *
 * <p>Each registered bean definition uses a {@link java.util.function.Supplier}
 * factory that resolves the {@link MeshDependencyInjector} from the bean
 * factory at first use, then delegates to
 * {@link MeshDependencyInjector#getToolProxy(String)} (or the type-aware
 * overload when the {@code @MeshDependency.expectedType} is set). The same
 * proxy instance is returned forever after (Spring caches it as a singleton),
 * which preserves the heartbeat-driven auto-rewiring semantics — the
 * injector updates the capability's shared endpoint state in place.
 *
 * <p>Conflict policy: if a bean name equal to a capability is already
 * defined (user owns it), we log an ERROR — including the conflicting bean's
 * class and every {@code @MeshDependsOn}-annotated class that declared the
 * capability — and skip the registration. Consumers that
 * {@code @Qualifier}-injected {@code McpMeshTool<...>} will fail context
 * refresh with {@code BeanNotOfRequiredTypeException} (the user-owned bean
 * is not an {@code McpMeshTool}); the ERROR log makes the resolution
 * actionable.
 *
 * <p>Dedup: within a single application context, the same capability
 * declared by multiple {@code @MeshDependsOn} beans is registered exactly
 * once.
 */
public class MeshCapabilityBeanRegistrar implements BeanDefinitionRegistryPostProcessor {

    private static final Logger log = LoggerFactory.getLogger(MeshCapabilityBeanRegistrar.class);

    /**
     * Per-registrar cache of capability → resolved injector reference. The
     * supplier closures share this cache so the injector lookup happens
     * exactly once per JVM, no matter how many proxy beans get materialised.
     */
    private final AtomicReference<MeshDependencyInjector> injectorRef = new AtomicReference<>();

    @Override
    public void postProcessBeanDefinitionRegistry(BeanDefinitionRegistry registry) throws BeansException {
        if (!(registry instanceof ConfigurableListableBeanFactory beanFactory)) {
            // The registry should always be a ConfigurableListableBeanFactory
            // in practice (DefaultListableBeanFactory implements both). If
            // we ever see something else we'd lose the early bean
            // registration path; fall back to a no-op so the late
            // SmartInitializingSingleton in MeshAutoConfiguration can still
            // catch up.
            log.debug("BeanDefinitionRegistry is not a ConfigurableListableBeanFactory ({}); "
                + "skipping early @MeshDependsOn proxy registration", registry.getClass().getName());
            return;
        }

        Map<String, CapabilityDeclaration> capabilities = collectCapabilities(beanFactory);
        if (capabilities.isEmpty()) {
            return;
        }

        // Settling-window grace (#1193): declare each successfully-registered
        // capability key with the process-wide settle state so the
        // bean-injected proxy path (McpMeshTool.call) can perform a bounded,
        // capability-keyed wait before failing fast at startup — mirroring the
        // @MeshRoute path. The per-capability latch is counted down by
        // MeshDependencyInjector.updateToolDependency (markResolved) the
        // moment the endpoint lands. We declare keys ONLY for capabilities we
        // actually register a bean/proxy for: a name-conflicting capability is
        // skipped below and never gets a proxy, so marking it declared would
        // strand the agent-level "all declared deps resolved" latch forever.
        MeshSettleState settleState = MeshSettleState.getInstance();

        int added = 0;
        int conflicts = 0;
        for (Map.Entry<String, CapabilityDeclaration> entry : capabilities.entrySet()) {
            String capability = entry.getKey();
            CapabilityDeclaration declaration = entry.getValue();

            if (registry.containsBeanDefinition(capability) || beanFactory.containsSingleton(capability)) {
                logNameConflict(registry, capability, declaration);
                conflicts++;
                continue;
            }

            Class<?> expectedType = declaration.beanType();
            if (expectedType == null && declaration.paramTypes().size() > 1) {
                // A singleton bean cannot vary by injection point, so it can't
                // honour each @Qualifier consumer's own T: say so loudly.
                log.warn("Capability '{}' is consumed as different McpMeshTool<T> types {} by "
                        + "handlers in [{}]. Each handler gets its own typed proxy, but "
                        + "@Qualifier(\"{}\") injection points receive the untyped bean, whose "
                        + "results are dynamic (Map) — a typed McpMeshTool<Foo> field would fail "
                        + "with ClassCastException at the call site. Set "
                        + "@MeshDependency(expectedType = ...) to type the bean.",
                    capability, declaration.paramTypes(),
                    String.join(", ", declaration.declarerClassNames()), capability);
            }
            BeanDefinitionBuilder builder = BeanDefinitionBuilder
                .genericBeanDefinition(McpMeshTool.class,
                    () -> resolveProxy(beanFactory, capability, expectedType));
            BeanDefinition def = builder.getBeanDefinition();
            // I3 (PR #1086 review): mark the bean primary for its
            // capability-named slot. The @Qualifier path is unaffected
            // (primary only kicks in when no qualifier is present), but
            // future Map/Collection injection (e.g.
            // @Autowired Map<String, McpMeshTool<?>>) gets a sensible
            // default candidate when multiple producers share a type.
            def.setPrimary(true);
            registry.registerBeanDefinition(capability, def);
            settleState.registerDeclared(capability);
            added++;
        }
        log.info("@MeshDependsOn: registered {} McpMeshTool bean(s) early "
            + "(skipped {} due to name conflict)", added, conflicts);
    }

    @Override
    public void postProcessBeanFactory(ConfigurableListableBeanFactory beanFactory) throws BeansException {
        // No-op: all wiring is done in postProcessBeanDefinitionRegistry.
    }

    /**
     * Emit an actionable ERROR explaining the conflict: which user-owned
     * bean owns the name, which {@code @MeshDependsOn}-annotated classes
     * declared the capability (and will therefore fail
     * {@code @Qualifier} injection at context-refresh time), and how to
     * resolve it.
     */
    private void logNameConflict(BeanDefinitionRegistry registry, String capability,
                                 CapabilityDeclaration declaration) {
        String conflictClass = "<unknown>";
        try {
            BeanDefinition existing = registry.getBeanDefinition(capability);
            String className = existing.getBeanClassName();
            if (className == null || className.isBlank()) {
                // @Bean factory-method beans report a null beanClassName —
                // their concrete type lives on the ResolvableType. Fall back
                // there before giving up.
                org.springframework.core.ResolvableType resolved = existing.getResolvableType();
                if (resolved != null && resolved != org.springframework.core.ResolvableType.NONE) {
                    Class<?> raw = resolved.resolve();
                    if (raw != null) {
                        className = raw.getName();
                    }
                }
            }
            if (className != null && !className.isBlank()) {
                conflictClass = className;
            }
        } catch (Exception ignored) {
            // Fall back to "<unknown>" if Spring can't report the class.
        }
        List<String> declarers = declaration.declarerClassNames();
        String sources = String.join("/", declaration.sourceLabels());
        log.error("Cannot register McpMeshTool bean for capability '{}' — bean name already in use "
                + "by user-owned bean of type {}. Classes that declared this capability via "
                + "{} will fail @Qualifier injection: {}. Resolve by renaming either "
                + "your bean OR the capability.",
            capability, conflictClass, sources, declarers);
    }

    /**
     * Walk every registered bean definition, resolve its target class, and
     * collect the unique capability declarations via class-level
     * {@code @MeshDependsOn}. Returns an insertion-ordered map keyed by
     * capability name; the first {@link MeshDependency} encountered wins for
     * type/schema metadata (subsequent declarations only extend the
     * declarer-class list so the conflict-diagnostics are complete).
     */
    private Map<String, CapabilityDeclaration> collectCapabilities(ConfigurableListableBeanFactory beanFactory) {
        Map<String, CapabilityDeclaration> capabilities = new LinkedHashMap<>();
        for (String beanName : beanFactory.getBeanDefinitionNames()) {
            BeanDefinition def = beanFactory.getBeanDefinition(beanName);
            Class<?> beanClass = resolveBeanClass(beanFactory, def);
            if (beanClass == null) {
                continue;
            }
            MeshDependsOn annotation = AnnotationUtils.findAnnotation(beanClass, MeshDependsOn.class);
            if (annotation != null) {
                for (MeshDependency dep : annotation.value()) {
                    // Issue #1572: a malformed "a|b" selector tag fails the boot here.
                    MeshTagSpecs.validate(dep.tags(), "@MeshDependsOn on " + beanClass.getName()
                        + " dependency '" + dep.capability() + "'");
                    mergeDependency(capabilities, dep, beanClass, "@MeshDependsOn", null);
                }
            }
            // Issue #1088: also scan method-level @MeshRoute / @MeshA2A
            // dependencies. The registries are not yet populated this early
            // (their BeanPostProcessors run later), so we read the annotations
            // straight off the bean class via reflection — mirroring
            // MeshRouteBeanPostProcessor / MeshA2ABeanPostProcessor.
            //
            // Issue #1569: the full method set, inherited handlers included, via
            // the same MethodIntrospector selection the scanners use — so an
            // override annotated on both levels, or a bridge method, is seen
            // once, and a base-class handler is seen at all.
            for (Method method : handlerMethods(beanClass)) {
                MeshRoute meshRoute = AnnotationUtils.findAnnotation(method, MeshRoute.class);
                if (meshRoute != null) {
                    mergeHandlerDependencies(capabilities, meshRoute.dependencies(), beanClass,
                        "@MeshRoute", method, MeshInjectableSlots.routeSlots(method));
                }
                MeshA2A meshA2A = AnnotationUtils.findAnnotation(method, MeshA2A.class);
                if (meshA2A != null) {
                    mergeHandlerDependencies(capabilities, meshA2A.dependencies(), beanClass,
                        "@MeshA2A", method, MeshInjectableSlots.a2aSlots(method));
                }
            }
        }
        return capabilities;
    }

    /**
     * {@code @MeshRoute} / {@code @MeshA2A} candidates of {@code beanClass}:
     * one entry per logical method, inherited declarations included, bridge and
     * synthetic methods excluded.
     */
    private static Set<Method> handlerMethods(Class<?> beanClass) {
        // Runs over every bean definition: skip classes that cannot carry
        // either annotation, and — as Spring's EventListenerMethodProcessor —
        // treat an unresolvable signature as "no handlers".
        if (!AnnotationUtils.isCandidateClass(beanClass, MeshRoute.class)
                && !AnnotationUtils.isCandidateClass(beanClass, MeshA2A.class)) {
            return Set.of();
        }
        try {
            return MethodIntrospector.selectMethods(beanClass,
                (ReflectionUtils.MethodFilter) m -> !m.isBridge() && !m.isSynthetic()
                    && (AnnotationUtils.findAnnotation(m, MeshRoute.class) != null
                        || AnnotationUtils.findAnnotation(m, MeshA2A.class) != null));
        } catch (Exception | LinkageError ex) {
            log.debug("Could not resolve methods of {} for @MeshRoute/@MeshA2A scanning",
                beanClass.getName(), ex);
            return Set.of();
        }
    }

    /**
     * Merge one handler's declared dependencies, pairing each with the
     * {@code McpMeshTool<T>} parameter it binds to <b>positionally</b> — the
     * same {@link MeshPositionalBinder} pairing the route and A2A resolvers use
     * to hand that parameter its proxy (issue #1568). Parameter names and
     * {@code @MeshInject} values take no part.
     */
    private void mergeHandlerDependencies(Map<String, CapabilityDeclaration> capabilities,
                                          MeshDependency[] deps, Class<?> declarerClass,
                                          String sourceLabel, Method method,
                                          List<MeshPositionalBinder.Slot> slots) {
        List<String> declared = new ArrayList<>(deps.length);
        for (MeshDependency dep : deps) {
            declared.add(dep.capability());
        }
        MeshPositionalBinder.Binding binding =
            MeshPositionalBinder.bind(method, slots, declared, declared.size());
        for (int k = 0; k < deps.length; k++) {
            Class<?> paramType = null;
            int ordinal = binding.depIndexToSlot()[k];
            if (ordinal >= 0) {
                // Route/A2A slots are all PROXY, so slot k is dependency k's slot.
                int position = binding.slots().get(k).parameterPosition();
                if (MeshInjectableSlots.proxyTypeArgument(method, position, declarerClass) instanceof Class<?> concrete) {
                    paramType = concrete;
                }
            }
            mergeDependency(capabilities, deps[k], declarerClass, sourceLabel, paramType);
        }
    }

    /**
     * Merge a single {@link MeshDependency} into the capability map, applying
     * the shared dedup / expectedType upgrade / conflict-detection logic used
     * by every source ({@code @MeshDependsOn}, {@code @MeshRoute},
     * {@code @MeshA2A}).
     *
     * <p>Only an explicit {@link MeshDependency#expectedType()} takes part in
     * the hard conflict check: two different explicit types for one capability
     * fail the boot. {@code paramType} — the concrete {@code Foo} of the
     * {@code McpMeshTool<Foo>} parameter the dependency positionally binds to
     * on a handler — is only a fallback for the {@code @Qualifier} bean's
     * default type (see {@link CapabilityDeclaration#beanType()}). Handlers
     * that declare different {@code T} for one capability are legal: each gets
     * its own typed proxy at request time (issue #1568).
     */
    private void mergeDependency(Map<String, CapabilityDeclaration> capabilities,
                                 MeshDependency dep, Class<?> declarerClass,
                                 String sourceLabel, Class<?> paramType) {
        String capability = dep.capability();
        if (capability == null || capability.isBlank()) {
            log.warn("{} on {} has @MeshDependency with empty capability — skipping",
                sourceLabel, declarerClass.getName());
            return;
        }

        Class<?> incomingExpectedType = dep.expectedType();
        if (incomingExpectedType == Void.class || incomingExpectedType == void.class) {
            incomingExpectedType = null;
        }

        CapabilityDeclaration declaration = capabilities.computeIfAbsent(
            capability, k -> new CapabilityDeclaration());

        Class<?> existingExpectedType = declaration.explicitType();
        if (existingExpectedType != null && incomingExpectedType != null
                && !existingExpectedType.equals(incomingExpectedType)) {
            throw new IllegalStateException(String.format(
                "Capability '%s' is declared with conflicting expectedType values: "
                    + "%s (declared via %s by [%s]) vs %s (declared via %s by %s). "
                    + "Align expectedType across every declaration site for this "
                    + "capability, or split into separate capability names.",
                capability,
                existingExpectedType.getName(),
                String.join("/", declaration.sourceLabels()),
                String.join(", ", declaration.declarerClassNames()),
                incomingExpectedType.getName(),
                sourceLabel,
                declarerClass.getName()));
        }
        // Upgrade-path: an earlier declaration omitted expectedType and a
        // later one supplies it. The non-null type wins so the registered
        // proxy bean gets typed deserialisation from the very first call.
        if (existingExpectedType == null && incomingExpectedType != null) {
            declaration.setExplicitType(incomingExpectedType);
        }
        if (incomingExpectedType == null && paramType != null) {
            declaration.addParamType(paramType);
        }
        declaration.addDeclarer(declarerClass.getName());
        declaration.addSourceLabel(sourceLabel);
    }

    /**
     * Resolve the target class from a bean definition. Returns null when the
     * class cannot be determined or loaded.
     *
     * <p>Resolution order:
     * <ol>
     *   <li>{@link BeanDefinition#getBeanClassName()} +
     *       {@link ClassUtils#forName(String, ClassLoader)} — works for
     *       component-scanned beans, where the bean class name IS the
     *       concrete user class. Preferred first because it preserves the
     *       concrete declarer class even when Spring's {@code ResolvableType}
     *       might report a supertype/interface for the bean.</li>
     *   <li>{@link BeanDefinition#getResolvableType()} — fallback for
     *       {@code @Bean} factory-method beans where {@code beanClassName}
     *       is null. Spring populates the resolvable type from the factory
     *       method's declared return type, which is the produced class.
     *       The {@code @MeshDependsOn} annotation discovery in
     *       {@link #collectCapabilities} relies on this fallback path to
     *       find class-level annotations on factory-produced beans.</li>
     * </ol>
     */
    private static Class<?> resolveBeanClass(ConfigurableListableBeanFactory beanFactory, BeanDefinition def) {
        String className = def.getBeanClassName();
        if (className != null) {
            try {
                return ClassUtils.forName(className, beanFactory.getBeanClassLoader());
            } catch (Throwable ignored) {
                // Fall through to ResolvableType.
            }
        }
        try {
            org.springframework.core.ResolvableType resolved = def.getResolvableType();
            if (resolved != org.springframework.core.ResolvableType.NONE) {
                Class<?> raw = resolved.resolve();
                if (raw != null) {
                    return raw;
                }
            }
        } catch (Exception ignored) {
            // Fall through to null.
        }
        return null;
    }

    /**
     * Bean-supplier callback: resolve the {@link MeshDependencyInjector} from
     * the bean factory (lazy — the injector is constructed by another
     * factory method in {@code MeshAutoConfiguration}) and return its proxy
     * for the given capability. When {@code expectedType} is non-null the
     * type-aware overload is used so the proxy deserialises responses to
     * that concrete type from the very first call (I4 in PR #1086 review).
     */
    private McpMeshTool<?> resolveProxy(ConfigurableListableBeanFactory beanFactory,
                                        String capability, Class<?> expectedType) {
        MeshDependencyInjector injector = injectorRef.get();
        if (injector == null) {
            injector = beanFactory.getBean(MeshDependencyInjector.class);
            injectorRef.compareAndSet(null, injector);
        }
        if (expectedType != null) {
            return injector.getToolProxy(capability, expectedType);
        }
        return injector.getToolProxy(capability);
    }

    /**
     * Per-capability accumulator: the explicit {@code expectedType} (if any
     * declarer set one), the {@code McpMeshTool<T>} types of handler parameters
     * bound to the capability, and every declaring class (for conflict
     * diagnostics).
     */
    private static final class CapabilityDeclaration {
        private Class<?> explicitType;
        private final Set<Class<?>> paramTypes = new LinkedHashSet<>();
        private final List<String> declarerClassNames = new ArrayList<>();
        private final Set<String> sourceLabels = new LinkedHashSet<>();

        void addDeclarer(String className) {
            if (!declarerClassNames.contains(className)) {
                declarerClassNames.add(className);
            }
        }

        void addSourceLabel(String label) {
            sourceLabels.add(label);
        }

        Class<?> explicitType() {
            return explicitType;
        }

        void setExplicitType(Class<?> explicitType) {
            this.explicitType = explicitType;
        }

        void addParamType(Class<?> type) {
            paramTypes.add(type);
        }

        /**
         * The default type of the capability's {@code @Qualifier} bean: the
         * explicit {@code expectedType} when set; else the handler parameter
         * type when every handler agrees; else {@code null} (dynamic).
         */
        Class<?> beanType() {
            if (explicitType != null) {
                return explicitType;
            }
            return paramTypes.size() == 1 ? paramTypes.iterator().next() : null;
        }

        Set<Class<?>> paramTypes() {
            return Set.copyOf(paramTypes);
        }

        List<String> declarerClassNames() {
            return List.copyOf(declarerClassNames);
        }

        Set<String> sourceLabels() {
            return Set.copyOf(sourceLabels);
        }
    }
}
