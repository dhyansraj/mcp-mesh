package io.mcpmesh.spring;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;
import io.mcpmesh.SchemaMode;
import io.mcpmesh.Selector;
import io.mcpmesh.core.MeshObjectMappers;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.annotation.AnnotatedBeanDefinition;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.beans.factory.config.ConfigurableListableBeanFactory;
import org.springframework.beans.factory.support.BeanDefinitionBuilder;
import org.springframework.beans.factory.support.BeanDefinitionRegistry;
import org.springframework.beans.factory.support.BeanDefinitionRegistryPostProcessor;
import org.springframework.boot.autoconfigure.AutoConfigurationPackages;
import org.springframework.context.annotation.ClassPathScanningCandidateComponentProvider;
import org.springframework.core.ResolvableType;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.core.type.filter.AnnotationTypeFilter;
import org.springframework.util.ClassUtils;
import tools.jackson.databind.ObjectMapper;

import java.beans.Introspector;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.lang.reflect.Parameter;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Proxy;
import java.lang.reflect.Type;
import java.time.temporal.Temporal;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Flow;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicReference;

/**
 * RFC #1280 (Phase 1): discovers consumer-owned <b>service view</b> interfaces
 * annotated with {@link McpMeshService} and registers one JDK-proxy bean per
 * interface. Each abstract method binds a single capability via a method-level
 * {@link Selector} and delegates to that capability's own resolved
 * {@link io.mcpmesh.types.McpMeshTool} proxy — so different methods may resolve
 * to different provider agents and rebind independently.
 *
 * <p>Mirrors {@link MeshCapabilityBeanRegistrar}: runs as a
 * {@link BeanDefinitionRegistryPostProcessor} so the facade beans exist BEFORE
 * user singletons are autowired, and shares the same lazy-injector /
 * name-conflict / conflicting-type / settle-declared policies.
 *
 * <p>Discovery follows the Spring-Data-repository pattern — service views are
 * bare interfaces with no implementation, so a
 * {@link ClassPathScanningCandidateComponentProvider} with an
 * {@code isCandidateComponent} override that accepts independent interfaces is
 * used, scoped to the {@link AutoConfigurationPackages} base packages. When the
 * auto-configuration packages are unavailable (e.g. no {@code @SpringBootApplication}
 * registered them), discovery is skipped with a WARN — same resilience posture
 * as the sibling registrar's non-{@code ConfigurableListableBeanFactory} guard.
 */
public class McpMeshServiceRegistrar implements BeanDefinitionRegistryPostProcessor {

    private static final Logger log = LoggerFactory.getLogger(McpMeshServiceRegistrar.class);

    /** Non-object-convertible reference types the single-POJO param rule rejects. */
    private static final Set<Class<?>> SCALAR_LIKE = Set.of(
        java.util.Date.class, java.util.Calendar.class, java.math.BigDecimal.class,
        java.math.BigInteger.class, UUID.class);

    /** Shared with every facade proxy so the injector lookup happens once. */
    private final AtomicReference<MeshDependencyInjector> injectorRef = new AtomicReference<>();

    /** Jackson mapper for the stream single-POJO → params-map conversion. */
    private final ObjectMapper objectMapper = MeshObjectMappers.create();

    /**
     * Views discovered + validated in {@link #postProcessBeanDefinitionRegistry}.
     * Read later by {@code MeshAutoConfiguration.addMcpMeshServiceDependencies}
     * to expand each method into a wire dependency edge. This is the
     * registrar-instance holder the auto-config reads (the registrar IS a bean),
     * so each application context gets its own fresh view set — no JVM-static
     * leakage across test contexts.
     */
    private final List<ServiceViewMetadata> discovered = new CopyOnWriteArrayList<>();

    /**
     * Directly-annotated {@code @McpMeshService} CLASS names found by the SAME
     * scan pass that discovers view interfaces (RFC #1280 phase-3 review, item
     * 3): producer candidates. A late {@link org.springframework.beans.factory.SmartInitializingSingleton}
     * WARNs for any of these the {@link MeshToolBeanPostProcessor} did NOT
     * actually see as a bean — ground-truth comparison, no false positives.
     */
    private final List<String> annotatedProducerClasses = new CopyOnWriteArrayList<>();

    /**
     * The validated views discovered in this context, sorted by interface name
     * for a deterministic dependency-expansion order.
     */
    public List<ServiceViewMetadata> discoveredServices() {
        List<ServiceViewMetadata> copy = new ArrayList<>(discovered);
        copy.sort(Comparator.comparing(v -> v.iface().getName()));
        return copy;
    }

    /** Directly-annotated @McpMeshService class names found during scanning. */
    public List<String> discoveredProducerClasses() {
        return List.copyOf(annotatedProducerClasses);
    }

    @Override
    public void postProcessBeanDefinitionRegistry(BeanDefinitionRegistry registry) throws BeansException {
        if (!(registry instanceof ConfigurableListableBeanFactory beanFactory)) {
            log.debug("BeanDefinitionRegistry is not a ConfigurableListableBeanFactory ({}); "
                + "skipping @McpMeshService discovery", registry.getClass().getName());
            return;
        }
        if (!AutoConfigurationPackages.has(beanFactory)) {
            log.warn("No @AutoConfigurationPackages registered — skipping @McpMeshService discovery. "
                + "Service views require a @SpringBootApplication (or @AutoConfigurationPackage) "
                + "to establish the base packages to scan.");
            return;
        }

        List<String> basePackages = AutoConfigurationPackages.get(beanFactory);
        ClassLoader classLoader = beanFactory.getBeanClassLoader();

        // Settling-window grace (#1193): every view method's capability is a
        // dependency edge in the capability key space (same as @MeshRoute /
        // @MeshDependsOn — NOT the funcId:dep_N composite tool-wrapper space),
        // so a facade call firing during the startup settling window performs a
        // bounded, capability-keyed wait instead of failing fast — parity with
        // MeshCapabilityBeanRegistrar. markResolved is counted down by
        // MeshDependencyInjector.updateToolDependency the moment an endpoint
        // lands. registerDeclared is a Set add: a capability also declared by a
        // route / @MeshDependsOn is idempotent.
        MeshSettleState settleState = MeshSettleState.getInstance();

        // ONE scan pass handles both roles (RFC #1280 phase-3 review, item 3):
        // directly-annotated INTERFACES become bean views here; directly-annotated
        // CLASSES are collected as producer candidates for the late non-bean WARN.
        //
        // Scanned bean views require @McpMeshService DIRECTLY on the interface.
        // Deliberate rule: a sub-interface that only INHERITS the annotation is
        // NOT co-discovered — co-discovery would always pull in the annotated
        // parent too (duplicate facades, parent-type injection ambiguity,
        // generic-narrowing type clashes). Sub-interface inheritance IS supported
        // for tool-parameter views ({@code isServiceView} uses findAnnotation),
        // where the user explicitly names the type so there is no ambiguity.
        // - useDefaultFilters=false + AnnotationTypeFilter(considerMeta=false,
        //   considerInterfaces=false): direct annotation only; composed/meta
        //   annotations and inherited-from-super-interface stay out of scope.
        ClassPathScanningCandidateComponentProvider scanner =
            new ClassPathScanningCandidateComponentProvider(false) {
                @Override
                protected boolean isCandidateComponent(AnnotatedBeanDefinition beanDefinition) {
                    return beanDefinition.getMetadata().isIndependent()
                        && !beanDefinition.getMetadata().isAnnotation();
                }
            };
        scanner.addIncludeFilter(new AnnotationTypeFilter(McpMeshService.class, false, false));
        scanner.setResourceLoader(new PathMatchingResourcePatternResolver(classLoader));

        // Cross-view conflicting-type detection: a capability bound by two view
        // methods (same or different views) must resolve to the same raw type.
        Map<String, CapabilityBinding> capabilityTypes = new LinkedHashMap<>();
        Set<String> seenClasses = new LinkedHashSet<>();

        int registered = 0;
        int conflicts = 0;
        for (String basePackage : basePackages) {
            for (BeanDefinition candidate : scanner.findCandidateComponents(basePackage)) {
                String className = candidate.getBeanClassName();
                if (className == null || !seenClasses.add(className)) {
                    continue;
                }
                Class<?> type;
                try {
                    type = ClassUtils.forName(className, classLoader);
                } catch (Throwable t) {
                    log.warn("Failed to load @McpMeshService candidate {} — skipping: {}",
                        className, t.getMessage());
                    continue;
                }
                // DIRECT annotation only (getAnnotation, not findAnnotation): a
                // sub-interface inheriting @McpMeshService is not a scanned view.
                McpMeshService annotation = type.getAnnotation(McpMeshService.class);
                if (annotation == null) {
                    continue;
                }
                if (!type.isInterface()) {
                    // Producer CLASS candidate — record for the late non-bean
                    // WARN (item 3); publication itself is the post-processor's job.
                    annotatedProducerClasses.add(className);
                    continue;
                }

                // Validation is boot-fail: an invalid view surfaces immediately
                // with a clear message, matching the @MeshTool missing-@Param
                // and conflicting-expectedType boot-fail style.
                ServiceViewMetadata metadata = buildMetadata(type, annotation, capabilityTypes);
                discovered.add(metadata);

                // Declare each view-method capability for the settle window,
                // independently of facade-bean registration below (a
                // name-conflicting view still contributes its dependency edges
                // to the spec, so its capabilities remain declared settle keys).
                for (ServiceMethodBinding binding : metadata.bindings()) {
                    settleState.registerDeclared(binding.capability());
                }

                String beanName = Introspector.decapitalize(type.getSimpleName());
                if (registry.containsBeanDefinition(beanName) || beanFactory.containsSingleton(beanName)) {
                    log.error("Cannot register @McpMeshService facade bean for '{}' — bean name '{}' "
                            + "already in use by a user-owned bean. Rename the interface OR the "
                            + "conflicting bean. The service view will not be injectable.",
                        type.getName(), beanName);
                    conflicts++;
                    continue;
                }

                @SuppressWarnings({"unchecked", "rawtypes"})
                BeanDefinitionBuilder builder = BeanDefinitionBuilder
                    .genericBeanDefinition((Class) type, () -> createFacade(beanFactory, metadata));
                registry.registerBeanDefinition(beanName, builder.getBeanDefinition());
                registered++;
            }
        }
        if (registered > 0 || conflicts > 0) {
            log.info("@McpMeshService: registered {} service-view facade bean(s) "
                + "(skipped {} due to name conflict)", registered, conflicts);
        }
    }

    @Override
    public void postProcessBeanFactory(ConfigurableListableBeanFactory beanFactory) throws BeansException {
        // No-op: all wiring is done in postProcessBeanDefinitionRegistry.
    }

    /** Build the JDK proxy backing a service-view facade bean. */
    private Object createFacade(ConfigurableListableBeanFactory beanFactory, ServiceViewMetadata metadata) {
        Class<?> iface = metadata.iface();
        return Proxy.newProxyInstance(
            iface.getClassLoader(),
            new Class<?>[] {iface},
            new McpMeshServiceInvocationHandler(
                iface, metadata.minAvailable(), metadata.bindings(),
                new InjectorViewProxyBinding(beanFactory, injectorRef), objectMapper));
    }

    /**
     * Reusable interface→bindings analysis (RFC #1280 phase 2). Both the
     * class-level bean path ({@link #postProcessBeanDefinitionRegistry}) and the
     * {@code @MeshTool} view-parameter path ({@link McpMeshServiceToolSupport})
     * call this so the bridge/synthetic filtering, {@link ResolvableType}
     * resolution, diamond dedupe, and per-method param/return validation are
     * defined exactly once. Uses a fresh conflicting-type map (a single view is
     * self-contained); the scanning path uses the shared-map overload to detect
     * conflicts across DIFFERENT discovered views.
     *
     * @param iface an interface annotated {@link McpMeshService}
     */
    static ServiceViewMetadata analyze(Class<?> iface) {
        McpMeshService annotation = AnnotationUtils.findAnnotation(iface, McpMeshService.class);
        return buildMetadata(iface, annotation, new LinkedHashMap<>());
    }

    /**
     * Validate every abstract method of a view and build its ordered binding
     * list. Methods are sorted deterministically (by name + parameter erasure) —
     * {@link Class#getMethods()} order is NOT guaranteed by the JVM, and the
     * downstream wire-dependency expansion must be reproducible.
     */
    static ServiceViewMetadata buildMetadata(Class<?> iface, McpMeshService annotation,
                                              Map<String, CapabilityBinding> capabilityTypes) {
        List<Method> methods = collectViewMethods(iface);

        List<ServiceMethodBinding> bindings = new ArrayList<>();
        for (Method method : methods) {
            Selector selector = method.getAnnotation(Selector.class);
            if (selector == null) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService interface %s: abstract method '%s' must be annotated with "
                        + "@Selector (each service-view method binds exactly one capability).",
                    iface.getName(), method.getName()));
            }
            String capability = selector.capability();
            if (capability == null || capability.isBlank()) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService interface %s: method '%s' has @Selector with an empty "
                        + "capability.", iface.getName(), method.getName()));
            }

            ReturnBinding returnBinding = analyzeReturn(iface, method);
            ParamBinding paramBinding = analyzeParams(iface, method);

            // Schema-matching expected type: an explicit @Selector.expectedType
            // wins; otherwise derive from the method's return type ONLY when a
            // schemaMode is requested (parity with the @MeshDependsOn path,
            // which never enables schema matching implicitly).
            Class<?> override = selector.expectedType();
            if (override == Void.class || override == void.class) {
                override = null;
            }
            boolean modeRequested = selector.schemaMode() != SchemaMode.NONE;
            Class<?> schemaExpectedType = override != null
                ? override
                : (modeRequested ? returnBinding.rawType() : null);

            // Cross-view conflicting-type policy: the same capability bound by
            // two methods must resolve to the same raw type — EXCEPT Object,
            // which is the dynamic/untyped marker in the proxy machinery
            // (collapses to "<dynamic>" in the type-keyed cache). Object coexists
            // with any concrete type; a conflict fires only between two DIFFERENT
            // concrete types. A concrete type wins the shared proxy typing (an
            // Object binding then reads dynamically — existing untyped-dep
            // semantics), so an annotated generic parent (T→Object) and a
            // narrowed sub both binding the capability boot and work.
            Class<?> incoming = returnBinding.rawType();
            CapabilityBinding prior = capabilityTypes.get(capability);
            if (prior == null || (prior.rawType() == Object.class && incoming != Object.class)) {
                // First binding, or upgrade Object → concrete.
                capabilityTypes.put(capability, new CapabilityBinding(
                    incoming, iface.getName(), method.getName()));
            } else if (incoming != Object.class && prior.rawType() != Object.class
                    && prior.rawType() != incoming) {
                throw new IllegalStateException(String.format(
                    "Capability '%s' is bound by @McpMeshService methods with conflicting resolved "
                        + "types: %s (%s.%s) vs %s (%s.%s). Align the return types or split into "
                        + "separate capabilities.",
                    capability,
                    prior.rawType().getName(), prior.viewName(), prior.methodName(),
                    incoming.getName(), iface.getName(), method.getName()));
            }

            bindings.add(new ServiceMethodBinding(
                method, capability, selector.tags(), selector.version(), selector.required(),
                selector.schemaMode(), schemaExpectedType, returnBinding.resolvedType(),
                returnBinding.rawType(), paramBinding.paramMode(), returnBinding.returnMode(),
                paramBinding.paramNames()));
        }

        // MED-7: a negative or unsatisfiable floor is a declaration mistake.
        int minAvailable = annotation.minAvailable();
        if (minAvailable < 0) {
            throw new IllegalStateException(String.format(
                "@McpMeshService interface %s: minAvailable must be >= 0 (got %d).",
                iface.getName(), minAvailable));
        }
        if (minAvailable > bindings.size()) {
            throw new IllegalStateException(String.format(
                "@McpMeshService interface %s: minAvailable=%d exceeds the number of "
                    + "dependency-bound methods (%d) — the floor can never be satisfied.",
                iface.getName(), minAvailable, bindings.size()));
        }
        if (bindings.isEmpty()) {
            log.warn("@McpMeshService interface {} declares no abstract methods — "
                + "the facade bean is a no-op view.", iface.getName());
        }
        return new ServiceViewMetadata(iface, minAvailable, List.copyOf(bindings));
    }

    /**
     * Collect the abstract view methods, skipping bridge/synthetic methods and
     * deduping diamond-inherited identical signatures (same name + erased
     * parameter types from multiple super-interfaces collapse to one binding).
     * Conflicting {@code @Selector} metadata on diamond duplicates is a
     * boot-fail. Covariant overrides keep the most-specific declaration; return
     * and parameter types are resolved against the concrete view interface by
     * {@link #analyzeReturn}/{@link #analyzeParams} via {@link ResolvableType}.
     */
    private static List<Method> collectViewMethods(Class<?> iface) {
        Map<String, Method> bySignature = new LinkedHashMap<>();
        for (Method method : iface.getMethods()) {
            if (method.isBridge() || method.isSynthetic()) {
                continue; // compiler-generated covariant/erasure bridges
            }
            if (method.isDefault() || Modifier.isStatic(method.getModifiers())) {
                continue; // default/static methods are not dependency edges
            }
            String signature = signatureKey(method);
            Method existing = bySignature.get(signature);
            if (existing == null) {
                bySignature.put(signature, method);
                continue;
            }
            Selector existingSel = existing.getAnnotation(Selector.class);
            Selector incomingSel = method.getAnnotation(Selector.class);
            if (existingSel != null && incomingSel != null
                    && !selectorsEquivalent(existingSel, incomingSel)) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService interface %s: diamond-inherited method '%s' carries "
                        + "conflicting @Selector metadata across super-interfaces. Declare a single "
                        + "consistent @Selector for this method.",
                    iface.getName(), method.getName()));
            }
            // Prefer the annotated / more-specific-return declaration.
            if (existingSel == null && incomingSel != null) {
                // Annotated incoming wins over an unannotated survivor.
                bySignature.put(signature, method);
            } else if (existingSel != null && incomingSel == null) {
                // Never replace an annotated survivor with an unannotated
                // duplicate — otherwise the outcome would depend on
                // Class#getMethods() iteration order (identical return types
                // make the covariant test below true either way).
                continue;
            } else if (existing.getReturnType().isAssignableFrom(method.getReturnType())) {
                // Both annotated (equivalent) or both unannotated: keep the
                // most-specific (covariant) return declaration.
                bySignature.put(signature, method);
            }
        }
        List<Method> methods = new ArrayList<>(bySignature.values());
        methods.sort(Comparator.comparing(Method::getName).thenComparing(McpMeshServiceRegistrar::signatureKey));
        return methods;
    }

    private static String signatureKey(Method method) {
        StringBuilder sb = new StringBuilder(method.getName()).append('(');
        Class<?>[] params = method.getParameterTypes();
        for (int i = 0; i < params.length; i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append(params[i].getName());
        }
        return sb.append(')').toString();
    }

    private static boolean selectorsEquivalent(Selector a, Selector b) {
        return a.capability().equals(b.capability())
            && Arrays.equals(a.tags(), b.tags())
            && a.version().equals(b.version())
            && a.required() == b.required()
            && a.expectedType() == b.expectedType()
            && a.schemaMode() == b.schemaMode();
    }

    /**
     * Resolve the return mode + the proxy type passed to {@code getToolProxy}.
     * Return type is resolved against the concrete view interface (MED-3), so
     * {@code interface View extends Base<Item>} binds {@code Item} rather than a
     * {@code TypeVariable} that silently deserializes to a {@code Map}.
     */
    private static ReturnBinding analyzeReturn(Class<?> iface, Method method) {
        ResolvableType returnType = ResolvableType.forMethodReturnType(method, iface);
        Class<?> raw = returnType.resolve(Object.class);

        if (raw == CompletableFuture.class) {
            ResolvableType arg = returnType.getGeneric(0);
            Class<?> argRaw = arg.resolve();
            if (arg == ResolvableType.NONE || argRaw == null) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService interface %s: method '%s' returns a raw CompletableFuture — "
                        + "declare CompletableFuture<T> with a concrete result type.",
                    iface.getName(), method.getName()));
            }
            return new ReturnBinding(ReturnMode.ASYNC, asReflectType(arg), argRaw);
        }
        // MED-8: any other Future / CompletionStage (incl. CompletableFuture
        // subclasses) is unsupported — the async contract is CompletableFuture<T>.
        if (Future.class.isAssignableFrom(raw) || CompletionStage.class.isAssignableFrom(raw)) {
            throw new IllegalStateException(String.format(
                "@McpMeshService interface %s: method '%s' returns %s — async view methods must "
                    + "return CompletableFuture<T>.",
                iface.getName(), method.getName(), raw.getName()));
        }
        if (Flow.Publisher.class.isAssignableFrom(raw)) {
            Class<?> chunk = returnType.getGeneric(0).resolve();
            if (chunk != String.class) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService interface %s: method '%s' returns Flow.Publisher<%s> — "
                        + "streaming views must return Flow.Publisher<String>.",
                    iface.getName(), method.getName(),
                    chunk == null ? "?" : chunk.getSimpleName()));
            }
            // Chunk type is String; the proxy return type is irrelevant to
            // stream() but keeping it String avoids clobbering the shared proxy.
            return new ReturnBinding(ReturnMode.STREAM, String.class, String.class);
        }
        return new ReturnBinding(ReturnMode.SYNC, asReflectType(returnType), raw);
    }

    /**
     * Resolve the parameter mode (mirrors the {@code @MeshTool} convention):
     * 0 params → no-arg; exactly 1 param without {@link Param} → single-POJO
     * (the type must be Jackson-object-convertible — MED-1); otherwise EVERY
     * param must carry {@code @Param("name")} — a mixed signature is a boot-fail.
     */
    private static ParamBinding analyzeParams(Class<?> iface, Method method) {
        Parameter[] params = method.getParameters();
        if (params.length == 0) {
            return new ParamBinding(ParamMode.NONE, new String[0]);
        }
        if (params.length == 1 && params[0].getAnnotation(Param.class) == null) {
            Class<?> paramType = ResolvableType.forMethodParameter(method, 0, iface).resolve(Object.class);
            if (!isObjectConvertible(paramType)) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService interface %s: method '%s' single unannotated parameter of type "
                        + "%s cannot be converted to a params object — single unannotated parameters "
                        + "must be a POJO/record; use @Param for scalar parameters.",
                    iface.getName(), method.getName(), paramType.getName()));
            }
            return new ParamBinding(ParamMode.SINGLE_POJO, new String[0]);
        }
        String[] names = new String[params.length];
        Set<String> seenNames = new LinkedHashSet<>();
        for (int i = 0; i < params.length; i++) {
            Param param = params[i].getAnnotation(Param.class);
            if (param == null || param.value().isBlank()) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService interface %s: method '%s' has %d parameters, so every "
                        + "parameter must carry @Param(\"name\") (parameter #%d does not). Use a "
                        + "single POJO parameter for object-style calls, or annotate all params.",
                    iface.getName(), method.getName(), params.length, i));
            }
            // Duplicate @Param names would silently overwrite in the params map.
            if (!seenNames.add(param.value())) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService interface %s: method '%s' declares duplicate @Param name "
                        + "'%s' (parameter #%d) — every parameter name must be unique.",
                    iface.getName(), method.getName(), param.value(), i));
            }
            names[i] = param.value();
        }
        return new ParamBinding(ParamMode.PARAM_MAP, names);
    }

    /**
     * Whether a lone unannotated parameter type can round-trip to a JSON object
     * (params map). {@link Map} is fine; scalars/collections/arrays are not —
     * they would blow up {@code McpMeshTool.call(Object...)} (odd-length
     * key-value handling) or Jackson's convert-to-map.
     */
    private static boolean isObjectConvertible(Class<?> type) {
        if (Map.class.isAssignableFrom(type)) {
            return true;
        }
        if (type.isPrimitive() || type.isArray() || type.isEnum()) {
            return false;
        }
        if (CharSequence.class.isAssignableFrom(type)
                || Number.class.isAssignableFrom(type)
                || Boolean.class == type || Character.class == type
                || Collection.class.isAssignableFrom(type)
                || Temporal.class.isAssignableFrom(type)
                || SCALAR_LIKE.contains(type)
                || type.getName().startsWith("java.time.")) {
            return false;
        }
        return true;
    }

    private static Type asReflectType(ResolvableType resolvable) {
        Type type = resolvable.getType();
        if (type instanceof Class<?>) {
            return type;
        }
        if (type instanceof ParameterizedType pt && allArgsConcrete(pt)) {
            return pt;
        }
        Class<?> resolved = resolvable.resolve();
        return resolved != null ? resolved : Object.class;
    }

    private static boolean allArgsConcrete(ParameterizedType pt) {
        for (Type arg : pt.getActualTypeArguments()) {
            if (arg instanceof Class<?>) {
                continue;
            }
            if (arg instanceof ParameterizedType nested && allArgsConcrete(nested)) {
                continue;
            }
            return false;
        }
        return true;
    }

    // ---- Metadata carriers ----------------------------------------------------

    /** Parameter-binding strategy for a view method. */
    public enum ParamMode { NONE, SINGLE_POJO, PARAM_MAP }

    /** Return-binding strategy for a view method. */
    public enum ReturnMode { SYNC, ASYNC, STREAM }

    private record ReturnBinding(ReturnMode returnMode, Type resolvedType, Class<?> rawType) {}

    private record ParamBinding(ParamMode paramMode, String[] paramNames) {}

    private record CapabilityBinding(Class<?> rawType, String viewName, String methodName) {}

    /**
     * A single validated view method → capability binding. Carries both the
     * call-time delegation metadata (used by
     * {@link McpMeshServiceInvocationHandler}) and the wire-expansion metadata
     * (used by {@code MeshAutoConfiguration.addMcpMeshServiceDependencies}).
     */
    public record ServiceMethodBinding(
        Method method,
        String capability,
        String[] tags,
        String version,
        boolean required,
        SchemaMode schemaMode,
        Class<?> schemaExpectedType,
        Type resolvedProxyType,
        Class<?> resolvedRawType,
        ParamMode paramMode,
        ReturnMode returnMode,
        String[] paramNames) {
    }

    /** A discovered + validated service view. */
    public record ServiceViewMetadata(
        Class<?> iface,
        int minAvailable,
        List<ServiceMethodBinding> bindings) {
    }
}
