package io.mcpmesh.spring;

import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.util.ReflectionUtils;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

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

        // Check all methods for @MeshTool annotation
        ReflectionUtils.doWithMethods(targetClass, method -> {
            MeshTool annotation = AnnotationUtils.findAnnotation(method, MeshTool.class);
            if (annotation != null) {
                log.debug("Found @MeshTool on {}.{}", targetClass.getSimpleName(), method.getName());

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

                // Register with legacy registry (for agent spec generation)
                registry.registerTool(bean, method, annotation);

                // Create wrapper for MCP SDK integration
                createAndRegisterWrapper(bean, targetClass, method, annotation);
            }
        });

        return bean;
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
            MeshTool annotation) {

        // Generate funcId: "com.example.ClassName.methodName"
        String funcId = targetClass.getName() + "." + method.getName();

        // Extract dependency names from @MeshTool(dependencies=...)
        List<String> dependencyNames = extractDependencyNames(annotation);

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
            annotation.retryOn()
        );

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
}
