package io.mcpmesh.spring;

import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.McpMeshService;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.MethodIntrospector;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.util.ClassUtils;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Bean post-processor that scans beans for {@code @MeshTool} annotations.
 *
 * <p>This processor is invoked for every bean created by Spring and:
 * <ol>
 *   <li>Registers tool metadata with {@link MeshToolRegistry} for agent registration</li>
 *   <li>Creates {@link MeshToolWrapper} instances for MCP SDK integration</li>
 * </ol>
 *
 * <p>Handles CGLIB proxies by looking at the target class for annotations.
 *
 * @see MeshToolWrapper
 * @see MeshToolWrapperRegistry
 */
public class MeshToolBeanPostProcessor implements BeanPostProcessor, Ordered {

    private static final Logger log = LoggerFactory.getLogger(MeshToolBeanPostProcessor.class);

    /**
     * RFC #1280 phase 3: a capability name (and a producer prefix) is one or more
     * dot-separated segments, each following the flat rule. MUST stay in lock-step
     * with the registry's segment-wise capability pattern
     * (src/core/registry/validation.go, support_types.py).
     */
    private static final Pattern CAPABILITY_NAME_PATTERN =
        Pattern.compile("^[a-zA-Z][a-zA-Z0-9_-]*(\\.[a-zA-Z][a-zA-Z0-9_-]*)*$");

    /**
     * Whether {@code name} is a valid mesh capability name (segment-wise).
     * Package-private + static so the producer capability derivation can be unit
     * tested without a real {@link Method} — Java method names may legally
     * contain {@code $} or Unicode letters that the capability grammar rejects.
     */
    static boolean isValidCapabilityName(String name) {
        return name != null && CAPABILITY_NAME_PATTERN.matcher(name).matches();
    }

    /**
     * Producer classes the post-processor actually SAW as beans (RFC #1280
     * phase-3 review, item 2): the ground-truth set the late non-bean WARN
     * compares the registrar's scanned producer classes against, so a producer
     * registered via a @Bean factory method (declared return type = an
     * interface/supertype) is never falsely flagged.
     */
    private final java.util.Set<String> seenProducerClassNames =
        java.util.concurrent.ConcurrentHashMap.newKeySet();

    /** Producer class names this post-processor saw as beans (ground truth). */
    public java.util.Set<String> seenProducerClassNames() {
        return java.util.Collections.unmodifiableSet(seenProducerClassNames);
    }

    private final MeshToolRegistry registry;
    private final MeshToolWrapperRegistry wrapperRegistry;
    private final ObjectMapper objectMapper;
    private final A2AConsumerBeanPostProcessor a2aProcessor;

    public MeshToolBeanPostProcessor(
            MeshToolRegistry registry,
            MeshToolWrapperRegistry wrapperRegistry,
            ObjectMapper objectMapper) {
        this(registry, wrapperRegistry, objectMapper, null);
    }

    /**
     * Issue #923: includes the {@link A2AConsumerBeanPostProcessor} so
     * each created {@link MeshToolWrapper} can be told which method
     * has an A2AClient injection slot (and which client to inject).
     * Pass {@code null} for environments without A2A consumer support.
     */
    public MeshToolBeanPostProcessor(
            MeshToolRegistry registry,
            MeshToolWrapperRegistry wrapperRegistry,
            ObjectMapper objectMapper,
            A2AConsumerBeanPostProcessor a2aProcessor) {
        this.registry = registry;
        this.wrapperRegistry = wrapperRegistry;
        this.objectMapper = objectMapper;
        this.a2aProcessor = a2aProcessor;
    }

    /**
     * Issue #923: run AFTER {@link A2AConsumerBeanPostProcessor} so that
     * {@link A2AConsumerBeanPostProcessor#bindingFor(Method)} returns a
     * non-null binding for {@code @A2AConsumer} methods by the time we
     * construct the {@link MeshToolWrapper} and call
     * {@link MeshToolWrapper#setA2AClientBinding}. Lowest precedence (= last)
     * is the safe default — no other framework BPP needs to run after us.
     */
    @Override
    public int getOrder() {
        return Ordered.LOWEST_PRECEDENCE;
    }

    @Override
    public Object postProcessBeforeInitialization(Object bean, String beanName) throws BeansException {
        return bean;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        // Get the target class (unwrap CGLIB proxies)
        Class<?> targetClass = AopUtils.getTargetClass(bean);

        // Select @MeshTool methods, one entry per LOGICAL method. A bare
        // ReflectionUtils.doWithMethods walk (no MethodFilter) visited an
        // overridden/inherited @MeshTool method MULTIPLE times — once per
        // declaring class in the hierarchy, plus generic bridge methods —
        // and each visit re-registered the same capability, tripping the
        // duplicate-capability boot error (#1164 review). MethodIntrospector
        // dedups via getMostSpecificMethod + BridgeMethodResolver: superclass
        // declarations and bridges collapse onto the single most-derived
        // user-declared Method, which is also the right invocation target.
        Map<Method, MeshTool> annotatedMethods = MethodIntrospector.selectMethods(targetClass,
            (MethodIntrospector.MetadataLookup<MeshTool>) method ->
                AnnotationUtils.findAnnotation(method, MeshTool.class));

        annotatedMethods.forEach((specificMethod, annotation) -> {
            Method method = selectRegistrationTarget(specificMethod);
            log.debug("Found @MeshTool on {}.{} (registering declaration {})",
                targetClass.getSimpleName(), specificMethod.getName(), method);

            // Issue #895: retryOn requires task=true (no controller without it,
            // so release-and-retry has no meaning). The Throwable-subclass
            // bound is enforced at compile-time by the annotation field
            // type (Class<? extends Throwable>), so no runtime check needed.
            Class<? extends Throwable>[] retryOn = annotation.retryOn();
            if (retryOn.length > 0 && !annotation.task()) {
                throw new IllegalStateException(
                    "@MeshTool(retryOn = ...) on '" + targetClass.getName() +
                    "#" + method.getName() + "' requires task = true; " +
                    "remove retryOn or set task = true.");
            }

            // Issue #1277: resumeCursor requires task=true (no controller
            // without it, so a resume cursor has no meaning).
            if (annotation.resumeCursor() && !annotation.task()) {
                throw new IllegalStateException(
                    "@MeshTool(resumeCursor = true) on '" + targetClass.getName() +
                    "#" + method.getName() + "' requires task = true; " +
                    "remove resumeCursor or set task = true.");
            }

            // RFC #1280 phase 2 (item 7b): analyze @McpMeshService view params
            // ONCE and hand the result to both the registry and the wrapper.
            List<McpMeshServiceToolSupport.ViewParamInfo> viewParams =
                McpMeshServiceToolSupport.analyzeViewParams(method);

            // Register with legacy registry (for agent spec generation)
            registry.registerTool(bean, method, annotation, viewParams);

            // Create wrapper for MCP SDK integration
            createAndRegisterWrapper(bean, targetClass, method, annotation, viewParams);
        });

        // RFC #1280 phase 3: producer sugar — a class annotated @McpMeshService
        // publishes each eligible method as a tool under "<prefix>.<methodName>".
        // Resolve the USER class first (ClassUtils.getUserClass strips a CGLIB
        // $$-enhanced subclass regardless of TargetClassAware; a no-op for JDK
        // proxy classes). Use the DIRECT class annotation (getAnnotation), NOT
        // findAnnotation: a phase-1 facade bean is a JDK proxy whose CLASS
        // implements a @McpMeshService INTERFACE — findAnnotation would see that
        // inherited annotation and mis-classify the consumer facade as a
        // producer. A genuine producer carries @McpMeshService directly on its
        // @Component class (proxy classes carry no declared annotations).
        Class<?> userClass = ClassUtils.getUserClass(targetClass);
        McpMeshService service = userClass.getAnnotation(McpMeshService.class);
        if (service != null && !userClass.isInterface()) {
            // Ground truth for the late non-bean WARN: this annotated class WAS
            // seen as a bean (item 2), regardless of how many methods it publishes.
            seenProducerClassNames.add(userClass.getName());
            publishServiceMethods(bean, userClass, service);
        }

        return bean;
    }

    /**
     * RFC #1280 phase 3: publish each eligible method of a producer class
     * annotated {@code @McpMeshService("prefix")} as an ordinary mesh tool with
     * capability {@code "prefix.<methodName>"}. Pure sugar: each method is routed
     * through the SAME {@code registerTool} + {@code createAndRegisterWrapper}
     * path a hand-written {@code @MeshTool} takes (schemas, duplicate-capability
     * boot-fail, injectable slots, {@code @McpMeshService} view params — all fall
     * out unchanged). A method carrying its own {@code @MeshTool} wins.
     */
    private void publishServiceMethods(Object bean, Class<?> targetClass, McpMeshService service) {
        String prefix = service.value();
        if (prefix == null || prefix.isBlank()) {
            throw new IllegalStateException("@McpMeshService on producer class "
                + targetClass.getName() + " needs a name prefix: @McpMeshService(\"<prefix>\"). "
                + "The blank default is only valid on a consumer interface (service view).");
        }
        validatePrefix(prefix, targetClass);
        if (service.minAvailable() != 0) {
            log.warn("@McpMeshService on producer class {} sets minAvailable={} — ignored "
                + "(minAvailable is a consumer-view attribute, not a producer one).",
                targetClass.getName(), service.minAvailable());
        }

        // Sort by method name (then erased signature) for deterministic
        // publication order — same determinism rule as the view analyzer.
        List<Method> eligible = new ArrayList<>();
        for (Method method : targetClass.getDeclaredMethods()) {
            if (isEligibleProducerMethod(method)
                    // Explicit @MeshTool wins — that method already published
                    // under its own declaration above; no auto-publish, no double.
                    && AnnotationUtils.findAnnotation(method, MeshTool.class) == null) {
                eligible.add(method);
            }
        }
        eligible.sort(java.util.Comparator.comparing(Method::getName)
            .thenComparing(m -> java.util.Arrays.toString(m.getParameterTypes())));

        int published = 0;
        Map<String, Method> byName = new HashMap<>();
        for (Method method : eligible) {
            // Overloaded public methods collide on prefix.<name> — fail fast
            // with an explicit message (clearer than the generic
            // duplicate-capability error the synthesized tools would trip).
            Method clash = byName.putIfAbsent(method.getName(), method);
            if (clash != null) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService producer '%s' on %s: overloaded public methods '%s' both map to "
                        + "capability '%s.%s' — a producer capability name is prefix + method name, so "
                        + "overloads collide. Rename one, make one non-public, or give one an explicit "
                        + "@MeshTool(capability=...).",
                    prefix, targetClass.getName(), method.getName(), prefix, method.getName()));
            }
            String capability = prefix + "." + method.getName();
            // Validate the FULL derived capability, not just the prefix: Java
            // method names may legally contain '$' (generated/interop code) or
            // Unicode letters that the capability grammar rejects — catch it at
            // BOOT with the declaration site, not as a remote registry 4xx later.
            if (!isValidCapabilityName(capability)) {
                throw new IllegalStateException(String.format(
                    "@McpMeshService producer '%s' on %s: method '%s' derives capability '%s', which "
                        + "is not a valid capability name (each dot-separated segment must start with "
                        + "a letter and contain only letters, numbers, underscores, and hyphens). "
                        + "Rename the method or give it an explicit @MeshTool(capability=...).",
                    prefix, targetClass.getName(), method.getName(), capability));
            }
            MeshTool synth = synthesizeMeshTool(capability, method);
            List<McpMeshServiceToolSupport.ViewParamInfo> viewParams =
                McpMeshServiceToolSupport.analyzeViewParams(method);
            registry.registerTool(bean, method, synth, viewParams);
            createAndRegisterWrapper(bean, targetClass, method, synth, viewParams);
            log.debug("@McpMeshService producer: published {}.{} as capability '{}'",
                targetClass.getSimpleName(), method.getName(), capability);
            published++;
        }
        log.info("@McpMeshService producer '{}' on {}: published {} method(s)",
            prefix, targetClass.getName(), published);
    }

    /**
     * Validate the producer prefix against the same segment-wise capability rule
     * the registry enforces (each dot-separated segment {@code ^[a-zA-Z][a-zA-Z0-9_-]*$}).
     * This is an early, prefix-specific error; the FULL derived capability
     * (prefix + "." + methodName) is validated per method in
     * {@link #publishServiceMethods} because a method name is NOT guaranteed to
     * be a valid segment (it may contain {@code $} or Unicode letters).
     */
    private static void validatePrefix(String prefix, Class<?> targetClass) {
        if (!CAPABILITY_NAME_PATTERN.matcher(prefix).matches()) {
            throw new IllegalStateException(String.format(
                "@McpMeshService prefix '%s' on producer class %s is invalid — it must be one or more "
                    + "dot-separated segments, each starting with a letter and containing only letters, "
                    + "numbers, underscores, and hyphens (e.g. \"media\" or \"media.v2\").",
                prefix, targetClass.getName()));
        }
    }

    /**
     * Eligible producer method: public, instance (non-static), declared on the
     * class itself, and not a compiler bridge/synthetic or an {@link Object}
     * override (equals/hashCode/toString). Non-public methods are ignored
     * silently (normal Java visibility semantics).
     */
    private static boolean isEligibleProducerMethod(Method method) {
        int mods = method.getModifiers();
        return Modifier.isPublic(mods)
            && !Modifier.isStatic(mods)
            && !method.isBridge()
            && !method.isSynthetic()
            && !isObjectMethod(method);
    }

    /** Whether {@code method} overrides a public {@link Object} method. */
    private static boolean isObjectMethod(Method method) {
        String name = method.getName();
        Class<?>[] p = method.getParameterTypes();
        return switch (name) {
            case "toString", "hashCode" -> p.length == 0;
            case "equals" -> p.length == 1 && p[0] == Object.class;
            default -> false;
        };
    }

    /**
     * Synthesize a {@link MeshTool} with the derived capability; all other
     * attributes take their annotation defaults (description="", version="1.0.0",
     * empty tags/dependencies/retryOn, no outputType, task=false). Producer sugar
     * is intentionally minimal — a method needing tags/version/description uses
     * an explicit {@code @MeshTool}.
     */
    private static MeshTool synthesizeMeshTool(String capability, Method method) {
        Map<String, Object> attributes = new HashMap<>();
        attributes.put("capability", capability);
        return AnnotationUtils.synthesizeAnnotation(attributes, MeshTool.class, method);
    }

    /**
     * Choose the {@link Method} object to register for one logical tool.
     *
     * <p>Usually the most-derived declaration ({@code specificMethod}, as
     * selected by {@link MethodIntrospector}). EXCEPT: parameter annotations
     * are not inherited in Java, so when the override declares neither
     * {@code @MeshTool} nor any {@code @Param} itself, the metadata lives on
     * an ancestor declaration with the same signature (the common
     * "fully-annotated abstract contract, bare subclass implementation"
     * pattern) — register that ancestor instead. {@code Method.invoke}
     * dispatches virtually, so the subclass override still runs either way;
     * what this choice controls is which declaration's {@code @Param} /
     * schema metadata describes the tool.
     *
     * <p>Ancestors include INTERFACES, not just superclasses (#1164 review
     * follow-up): an annotated default/abstract interface method implemented
     * bare in a class is the same contract pattern, and
     * {@link org.springframework.core.annotation.AnnotationUtils#findAnnotation}
     * already discovers the {@code @MeshTool} through the interface — only
     * the {@code @Param} metadata lookup was superclass-only, boot-failing
     * with "must have @Param annotation". Superclasses are searched first
     * (mirroring Java's class-beats-interface resolution), then the
     * interface hierarchies of every class in the chain.
     *
     * <p>An override that RE-DECLARES {@code @MeshTool} but no {@code @Param}
     * (#1164 review follow-up) is the same pattern with a twist: the schema
     * metadata still lives on the ancestor declaration, so registering the
     * override would boot-fail in {@link MeshToolWrapper} with "must have
     * {@code @Param} annotation" (or register an empty schema for
     * injectable-only signatures). The param-annotated ancestor is preferred
     * as the registration target; the override's {@code @MeshTool} values
     * still apply because the caller resolves the annotation from the
     * most-derived declaration before this selection runs.
     *
     * <p>Generic specializations (the override's parameter types differ from
     * the generic ancestor's erasure) always register the most-derived
     * declaration — the specialized types are what the schema must describe.
     * Annotate {@code @Param} on the specialized override in that case.
     */
    private static Method selectRegistrationTarget(Method specificMethod) {
        if (hasAnyParamAnnotation(specificMethod)) {
            return specificMethod;
        }
        // No @Param on the most-derived declaration. When it re-declares
        // @MeshTool itself, only an ancestor that carries @Param is worth
        // switching to; when it declares nothing, any ancestor with tool
        // metadata is the schema source.
        boolean redeclaresMeshTool = specificMethod.isAnnotationPresent(MeshTool.class);
        java.util.function.Predicate<Method> carriesMetadata = redeclaresMeshTool
            ? MeshToolBeanPostProcessor::hasAnyParamAnnotation
            : m -> m.isAnnotationPresent(MeshTool.class) || hasAnyParamAnnotation(m);
        Method ancestor = findAncestorDeclaration(specificMethod, carriesMetadata);
        if (ancestor == null) {
            return specificMethod;
        }
        if (redeclaresMeshTool) {
            log.warn("@MeshTool re-declared on override {} without @Param annotations — "
                + "registering ancestor declaration {} as the schema source (the override's "
                + "@MeshTool values still apply). Annotate @Param on the override to make "
                + "it the schema source.", specificMethod, ancestor);
        }
        return ancestor;
    }

    /** Same-signature ancestor declaration matching {@code carriesMetadata}, or null. */
    private static Method findAncestorDeclaration(
            Method specificMethod, java.util.function.Predicate<Method> carriesMetadata) {
        Class<?> declaring = specificMethod.getDeclaringClass();
        for (Class<?> c = declaring.getSuperclass(); c != null && c != Object.class;
                c = c.getSuperclass()) {
            Method ancestor = matchingDeclaration(c, specificMethod, carriesMetadata);
            if (ancestor != null) {
                return ancestor;
            }
        }
        java.util.Set<Class<?>> visited = new java.util.HashSet<>();
        for (Class<?> c = declaring; c != null && c != Object.class; c = c.getSuperclass()) {
            for (Class<?> iface : c.getInterfaces()) {
                Method ancestor = searchInterfaceHierarchy(iface, specificMethod, visited, carriesMetadata);
                if (ancestor != null) {
                    return ancestor;
                }
            }
        }
        return null;
    }

    /** Depth-first walk of one interface and its super-interfaces. */
    private static Method searchInterfaceHierarchy(
            Class<?> iface, Method specificMethod, java.util.Set<Class<?>> visited,
            java.util.function.Predicate<Method> carriesMetadata) {
        if (!visited.add(iface)) {
            return null;
        }
        Method declaration = matchingDeclaration(iface, specificMethod, carriesMetadata);
        if (declaration != null) {
            return declaration;
        }
        for (Class<?> superIface : iface.getInterfaces()) {
            Method found = searchInterfaceHierarchy(superIface, specificMethod, visited, carriesMetadata);
            if (found != null) {
                return found;
            }
        }
        return null;
    }

    /**
     * The same-signature declaration on {@code type} when it satisfies
     * {@code carriesMetadata}; {@code null} when absent or bare (generic
     * specializations have no same-signature ancestor).
     */
    private static Method matchingDeclaration(
            Class<?> type, Method specificMethod, java.util.function.Predicate<Method> carriesMetadata) {
        try {
            Method declaration = type.getDeclaredMethod(
                specificMethod.getName(), specificMethod.getParameterTypes());
            if (carriesMetadata.test(declaration)) {
                return declaration;
            }
        } catch (NoSuchMethodException ignored) {
            // No same-signature declaration on this ancestor.
        }
        return null;
    }

    private static boolean hasAnyParamAnnotation(Method method) {
        for (java.lang.reflect.Parameter p : method.getParameters()) {
            if (p.isAnnotationPresent(io.mcpmesh.Param.class)) {
                return true;
            }
        }
        return false;
    }

    /**
     * Create a MeshToolWrapper and register it with the wrapper registry.
     *
     * @param bean        The Spring bean instance
     * @param targetClass The target class (unwrapped from proxy)
     * @param method      The annotated method
     * @param annotation  The @MeshTool annotation
     */
    private void createAndRegisterWrapper(
            Object bean,
            Class<?> targetClass,
            Method method,
            MeshTool annotation,
            List<McpMeshServiceToolSupport.ViewParamInfo> viewParams) {

        // Generate funcId: "com.example.ClassName.methodName"
        String funcId = targetClass.getName() + "." + method.getName();

        // Extract dependency names from @MeshTool(dependencies=...)
        List<String> dependencyNames = extractDependencyNames(annotation);

        // RFC #1280 phase 2 (item 7b): view params are pre-computed ONCE by the
        // caller (postProcessAfterInitialization) and shared with MeshToolRegistry.
        // Their method edges are appended to the tool's declared dependency list
        // by the wrapper, in the SAME order the wire spec
        // (MeshToolRegistry.extractAllDependencies) uses.

        // Create wrapper. Phase B MeshJob substrate: the `task` flag controls
        // whether inbound calls bearing X-Mesh-Job-Id dispatch through the
        // job pipeline (JobController injection + auto-complete).
        // Issue #895: retryOn whitelist drives release-and-retry on the
        // task-dispatch path inside the wrapper.
        MeshToolWrapper wrapper = new MeshToolWrapper(
            funcId,
            annotation.capability(),
            annotation.description(),
            bean,
            method,
            dependencyNames,
            objectMapper,
            annotation.task(),
            annotation.retryOn(),
            viewParams
        );

        // Issue #1268: thread the per-declared-dependency required flags so
        // the claim gate (pre-claim skip + pre-invoke guard) knows which
        // dependency slots must be resolved before a job may run. Aligned to
        // the same filtered declaration order as dependencyNames.
        wrapper.setDependencyRequired(extractDependencyRequired(annotation));

        // Issue #923: when @A2AConsumer wired this method, hand the
        // wrapper the cached A2AClient + slot index so dispatch
        // populates the parameter at invoke time.
        if (a2aProcessor != null) {
            A2AConsumerBeanPostProcessor.MethodBinding binding = a2aProcessor.bindingFor(method);
            if (binding != null) {
                wrapper.setA2AClientBinding(binding.a2aParamIndex(), binding.client());
            }
        }

        // Register with wrapper registry
        wrapperRegistry.registerWrapper(wrapper);

        log.debug("Created wrapper for {} with {} dependencies",
            funcId, dependencyNames.size());
    }

    /**
     * Extract dependency capability names from the annotation.
     * These names are used for error messages when dependencies are unavailable.
     *
     * @param annotation The @MeshTool annotation
     * @return List of dependency capability names (in declaration order)
     */
    private List<String> extractDependencyNames(MeshTool annotation) {
        List<String> names = new ArrayList<>();
        for (Selector selector : annotation.dependencies()) {
            if (!selector.capability().isEmpty()) {
                names.add(selector.capability());
            }
        }
        return names;
    }

    /**
     * Extract the per-declared-dependency {@code required} flags (issue #1268)
     * in the SAME filtered order as {@link #extractDependencyNames} — only
     * selectors with a non-empty capability contribute — so the two lists are
     * positionally aligned.
     *
     * @param annotation The @MeshTool annotation
     * @return required flags in declaration order (parallel to dependency names)
     */
    private List<Boolean> extractDependencyRequired(MeshTool annotation) {
        List<Boolean> required = new ArrayList<>();
        for (Selector selector : annotation.dependencies()) {
            if (!selector.capability().isEmpty()) {
                required.add(selector.required());
            }
        }
        return required;
    }
}
