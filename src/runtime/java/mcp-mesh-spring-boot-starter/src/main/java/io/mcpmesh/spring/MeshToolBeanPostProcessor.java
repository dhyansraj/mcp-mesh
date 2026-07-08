package io.mcpmesh.spring;

import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.MeshService;
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
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

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

            // RFC #1280 phase 2 (item 7b): analyze @MeshService view params
            // ONCE and hand the result to both the registry and the wrapper.
            List<MeshServiceToolSupport.ViewParamInfo> viewParams =
                MeshServiceToolSupport.analyzeViewParams(method);

            // Register with legacy registry (for agent spec generation)
            registry.registerTool(bean, method, annotation, viewParams);

            // Create wrapper for MCP SDK integration
            createAndRegisterWrapper(bean, targetClass, method, annotation, viewParams);
        });

        // Issue #1320: the @MeshService("prefix") producer sugar — a class
        // that published each method as "<prefix>.<methodName>" — was withdrawn.
        // The annotation TYPE is shared with the consumer service-view form (on
        // an INTERFACE), so it stays; but producer usage (non-blank value() on a
        // CLASS) now fast-fails at boot with an actionable message. Resolve the
        // USER class first (ClassUtils.getUserClass strips a CGLIB $$-enhanced
        // subclass; a no-op for JDK proxy classes). Use the DIRECT class
        // annotation (getAnnotation), NOT findAnnotation: a consumer facade bean
        // is a JDK proxy whose CLASS implements a @MeshService INTERFACE —
        // findAnnotation would see that inherited annotation and mis-classify the
        // consumer facade. A producer carried @MeshService directly on its
        // @Component class (proxy classes carry no declared annotations).
        Class<?> userClass = ClassUtils.getUserClass(targetClass);
        MeshService service = userClass.getAnnotation(MeshService.class);
        if (service != null && !userClass.isInterface()
                && service.value() != null && !service.value().isBlank()) {
            String prefix = service.value();
            throw new IllegalStateException(
                "@MeshService(\"" + prefix + "\") producer sugar was removed in v3.1.0 — "
                + "it derived the wire capability from the method name (coupling the cross-runtime "
                + "contract to a language identifier) and could not express tags/version/dependencies. "
                + "Declare each tool explicitly with @MeshTool(capability=\"" + prefix + ".<method>\"). "
                + "See https://github.com/dhyansraj/mcp-mesh/issues/1320");
        }

        return bean;
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
            List<MeshServiceToolSupport.ViewParamInfo> viewParams) {

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
