package io.mcpmesh.spring;

import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.core.MethodIntrospector;

import java.lang.reflect.Method;
import java.util.Map;

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

        // One entry per logical method, inherited declarations included, bridge
        // and synthetic methods excluded — the same selection
        // MeshToolBeanPostProcessor makes. An unfiltered doWithMethods walk
        // visited an overridden @MeshLlm method once per declaring class.
        Map<Method, MeshLlm> annotated = MethodIntrospector.selectMethods(targetClass,
            (MethodIntrospector.MetadataLookup<MeshLlm>) m ->
                m.isBridge() || m.isSynthetic() ? null : AnnotationUtils.findAnnotation(m, MeshLlm.class));

        annotated.forEach((specificMethod, llmAnnotation) -> {
            log.debug("Found @MeshLlm on {}.{}", targetClass.getSimpleName(), specificMethod.getName());

            // Verify method also has @MeshTool (required for MCP exposure)
            MeshTool toolAnnotation = AnnotationUtils.findAnnotation(specificMethod, MeshTool.class);
            if (toolAnnotation == null) {
                log.warn("@MeshLlm on {}.{} without @MeshTool - method won't be exposed via MCP",
                    targetClass.getSimpleName(), specificMethod.getName());
            }

            // Register under the same Method MeshToolBeanPostProcessor registers
            // the tool with, so a Method-keyed lookup agrees across the two.
            Method method = toolAnnotation != null
                ? MeshToolBeanPostProcessor.selectRegistrationTarget(specificMethod)
                : specificMethod;
            llmRegistry.register(targetClass, method, llmAnnotation);

            // Verify method has MeshLlmAgent parameter
            if (!hasMeshLlmAgentParameter(method)) {
                log.warn("@MeshLlm on {}.{} has no MeshLlmAgent parameter - LLM won't be injected",
                    targetClass.getSimpleName(), method.getName());
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
