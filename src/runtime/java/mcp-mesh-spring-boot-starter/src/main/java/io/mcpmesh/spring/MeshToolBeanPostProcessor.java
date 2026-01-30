package io.mcpmesh.spring;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
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
public class MeshToolBeanPostProcessor implements BeanPostProcessor {

    private static final Logger log = LoggerFactory.getLogger(MeshToolBeanPostProcessor.class);

    private final MeshToolRegistry registry;
    private final MeshToolWrapperRegistry wrapperRegistry;
    private final ObjectMapper objectMapper;

    public MeshToolBeanPostProcessor(
            MeshToolRegistry registry,
            MeshToolWrapperRegistry wrapperRegistry,
            ObjectMapper objectMapper) {
        this.registry = registry;
        this.wrapperRegistry = wrapperRegistry;
        this.objectMapper = objectMapper;
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

        // Create wrapper
        MeshToolWrapper wrapper = new MeshToolWrapper(
            funcId,
            annotation.capability(),
            annotation.description(),
            bean,
            method,
            dependencyNames,
            objectMapper
        );

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
