package io.mcpmesh.spring;

import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshDependsOn;
import io.mcpmesh.spring.web.MeshInject;
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
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.util.ClassUtils;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
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
 * <p>Issue #1088: additionally scans each resolved bean class's declared
 * methods for {@link MeshRoute} and {@link MeshA2A} annotations and feeds
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
 * injector mutates the same proxy in place.
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

            Class<?> expectedType = declaration.expectedType();
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
                    mergeDependency(capabilities, dep, beanClass, "@MeshDependsOn", null);
                }
            }
            // Issue #1088: also scan method-level @MeshRoute / @MeshA2A
            // dependencies. The registries are not yet populated this early
            // (their BeanPostProcessors run later), so we read the annotations
            // straight off the bean class via reflection — mirroring
            // MeshRouteBeanPostProcessor / MeshA2ABeanPostProcessor.
            for (Method method : beanClass.getDeclaredMethods()) {
                MeshRoute meshRoute = AnnotationUtils.findAnnotation(method, MeshRoute.class);
                if (meshRoute != null) {
                    for (MeshDependency dep : meshRoute.dependencies()) {
                        mergeDependency(capabilities, dep, beanClass, "@MeshRoute", method);
                    }
                }
                MeshA2A meshA2A = AnnotationUtils.findAnnotation(method, MeshA2A.class);
                if (meshA2A != null) {
                    for (MeshDependency dep : meshA2A.dependencies()) {
                        mergeDependency(capabilities, dep, beanClass, "@MeshA2A", method);
                    }
                }
            }
        }
        return capabilities;
    }

    /**
     * Merge a single {@link MeshDependency} into the capability map, applying
     * the shared dedup / expectedType upgrade / conflict-detection logic used
     * by every source ({@code @MeshDependsOn}, {@code @MeshRoute},
     * {@code @MeshA2A}).
     *
     * <p>{@code expectedType} resolution: an explicit non-{@code Void}
     * {@link MeshDependency#expectedType()} always wins. When the attribute is
     * left at its {@code Void.class} default AND the declaration originates
     * from a {@code @MeshRoute} / {@code @MeshA2A} method (i.e. {@code method}
     * is non-null), we replicate {@code MeshRouteBeanPostProcessor.enrichDependencyReturnTypes}
     * by reading the generic type argument from a matching
     * {@code McpMeshTool<Foo>} parameter (matched by {@code @MeshInject} value
     * or parameter name against the capability / parameter name) — but only
     * when {@code Foo} is a concrete {@code Class<?>}.
     */
    private void mergeDependency(Map<String, CapabilityDeclaration> capabilities,
                                 MeshDependency dep, Class<?> declarerClass,
                                 String sourceLabel, Method method) {
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
        // Param-generic enrichment only when the attribute was left at default
        // and we have a @MeshRoute/@MeshA2A method to inspect.
        if (incomingExpectedType == null && method != null) {
            incomingExpectedType = resolveParamGenericType(method, dep, capability);
        }

        CapabilityDeclaration existing = capabilities.get(capability);
        if (existing == null) {
            CapabilityDeclaration fresh = new CapabilityDeclaration(incomingExpectedType);
            fresh.addDeclarer(declarerClass.getName());
            fresh.addSourceLabel(sourceLabel);
            capabilities.put(capability, fresh);
            return;
        }

        Class<?> existingExpectedType = existing.expectedType();
        if (existingExpectedType != null && incomingExpectedType != null
                && !existingExpectedType.equals(incomingExpectedType)) {
            throw new IllegalStateException(String.format(
                "Capability '%s' is declared with conflicting expectedType values: "
                    + "%s (declared via %s by [%s]) vs %s (declared via %s by %s). "
                    + "Align expectedType across every declaration site for this "
                    + "capability, or split into separate capability names.",
                capability,
                existingExpectedType.getName(),
                String.join("/", existing.sourceLabels()),
                String.join(", ", existing.declarerClassNames()),
                incomingExpectedType.getName(),
                sourceLabel,
                declarerClass.getName()));
        }
        // Upgrade-path: an earlier declaration omitted expectedType and a
        // later one supplies it. The non-null type wins so the registered
        // proxy bean gets typed deserialisation from the very first call.
        if (existingExpectedType == null && incomingExpectedType != null) {
            existing.setExpectedType(incomingExpectedType);
        }
        existing.addDeclarer(declarerClass.getName());
        existing.addSourceLabel(sourceLabel);
    }

    /**
     * Replicate {@code MeshRouteBeanPostProcessor.enrichDependencyReturnTypes}:
     * scan ALL {@code McpMeshTool<Foo>} parameters on {@code method} that match
     * {@code dep} (by {@code @MeshInject} value or parameter name against the
     * capability or {@link MeshDependency#name()}), and return the concrete
     * generic type argument {@code Foo} of the first match that has one.
     * A matched parameter whose generic argument is not a concrete
     * {@code Class<?>} (raw {@code McpMeshTool} / type variable / wildcard) is
     * skipped and the scan continues. Returns {@code null} only when no matching
     * parameter with a concrete {@code Class<?>} generic argument exists.
     */
    private Class<?> resolveParamGenericType(Method method, MeshDependency dep, String capability) {
        Type[] genericTypes = method.getGenericParameterTypes();
        Parameter[] params = method.getParameters();
        String depName = dep.name();
        for (int i = 0; i < params.length; i++) {
            if (!McpMeshTool.class.isAssignableFrom(params[i].getType())) {
                continue;
            }
            MeshInject meshInject = params[i].getAnnotation(MeshInject.class);
            String matchKey;
            if (meshInject != null && !meshInject.value().isEmpty()) {
                matchKey = meshInject.value();
            } else {
                matchKey = params[i].getName();
            }
            boolean matches = capability.equals(matchKey)
                || (depName != null && !depName.isBlank() && depName.equals(matchKey));
            if (!matches) {
                continue;
            }
            if (genericTypes[i] instanceof ParameterizedType pt) {
                Type[] typeArgs = pt.getActualTypeArguments();
                if (typeArgs.length > 0 && typeArgs[0] instanceof Class<?> concrete) {
                    return concrete;
                }
            }
            continue;
        }
        return null;
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
     * Per-capability accumulator: tracks the accumulated expected type and
     * every {@code @MeshDependsOn}-annotated class that mentions the
     * capability (for conflict-diagnostic log messages).
     *
     * <p>{@code expectedType} is mutable so the upgrade path in
     * {@link #collectCapabilities} can replace an initial {@code null}
     * (a declarer that omitted {@code expectedType}) with a non-null type
     * supplied by a later declarer for the same capability. Conflicts
     * between two non-null types fail fast — see the caller.
     */
    private static final class CapabilityDeclaration {
        private Class<?> expectedType;
        private final List<String> declarerClassNames = new ArrayList<>();
        private final Set<String> sourceLabels = new LinkedHashSet<>();

        CapabilityDeclaration(Class<?> expectedType) {
            this.expectedType = expectedType;
        }

        void addDeclarer(String className) {
            if (!declarerClassNames.contains(className)) {
                declarerClassNames.add(className);
            }
        }

        void addSourceLabel(String label) {
            sourceLabels.add(label);
        }

        Class<?> expectedType() {
            return expectedType;
        }

        void setExpectedType(Class<?> expectedType) {
            this.expectedType = expectedType;
        }

        List<String> declarerClassNames() {
            return List.copyOf(declarerClassNames);
        }

        Set<String> sourceLabels() {
            return Set.copyOf(sourceLabels);
        }
    }
}
