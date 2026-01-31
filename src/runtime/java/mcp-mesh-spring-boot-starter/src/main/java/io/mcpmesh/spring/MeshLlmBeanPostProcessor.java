package io.mcpmesh.spring;

import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.util.ReflectionUtils;

import java.lang.reflect.Method;

/**
 * Bean post-processor that scans beans for {@code @MeshLlm} annotations.
 *
 * <p>This processor:
 * <ol>
 *   <li>Detects methods annotated with @MeshLlm</li>
 *   <li>Extracts configuration (provider, maxIterations, systemPrompt, etc.)</li>
 *   <li>Registers configuration with {@link MeshLlmRegistry}</li>
 * </ol>
 *
 * <p>The actual MeshLlmAgent injection happens in {@link MeshToolWrapper}
 * during method invocation.
 *
 * @see MeshLlm
 * @see MeshLlmRegistry
 * @see MeshToolWrapper
 */
public class MeshLlmBeanPostProcessor implements BeanPostProcessor {

    private static final Logger log = LoggerFactory.getLogger(MeshLlmBeanPostProcessor.class);

    private final MeshLlmRegistry llmRegistry;

    public MeshLlmBeanPostProcessor(MeshLlmRegistry llmRegistry) {
        this.llmRegistry = llmRegistry;
    }

    @Override
    public Object postProcessBeforeInitialization(Object bean, String beanName) throws BeansException {
        return bean;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        // Get the target class (unwrap CGLIB proxies)
        Class<?> targetClass = AopUtils.getTargetClass(bean);

        // Check all methods for @MeshLlm annotation
        ReflectionUtils.doWithMethods(targetClass, method -> {
            MeshLlm llmAnnotation = AnnotationUtils.findAnnotation(method, MeshLlm.class);
            if (llmAnnotation != null) {
                log.debug("Found @MeshLlm on {}.{}", targetClass.getSimpleName(), method.getName());

                // Verify method also has @MeshTool (required for MCP exposure)
                MeshTool toolAnnotation = AnnotationUtils.findAnnotation(method, MeshTool.class);
                if (toolAnnotation == null) {
                    log.warn("@MeshLlm on {}.{} without @MeshTool - method won't be exposed via MCP",
                        targetClass.getSimpleName(), method.getName());
                }

                // Register with LLM registry
                llmRegistry.register(targetClass, method, llmAnnotation);

                // Verify method has MeshLlmAgent parameter
                if (!hasMeshLlmAgentParameter(method)) {
                    log.warn("@MeshLlm on {}.{} has no MeshLlmAgent parameter - LLM won't be injected",
                        targetClass.getSimpleName(), method.getName());
                }
            }
        });

        return bean;
    }

    /**
     * Check if method has a MeshLlmAgent parameter.
     */
    private boolean hasMeshLlmAgentParameter(Method method) {
        for (Class<?> paramType : method.getParameterTypes()) {
            if (paramType.getName().equals("io.mcpmesh.types.MeshLlmAgent")) {
                return true;
            }
        }
        return false;
    }
}
