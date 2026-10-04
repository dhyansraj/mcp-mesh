package io.mcpmesh.spring.web;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.MethodIntrospector;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.util.ClassUtils;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/**
 * Scans Spring beans for methods annotated with {@link MeshA2A} and registers
 * them in {@link MeshA2ARegistry}.
 *
 * <p>Runs during application startup as a {@link BeanPostProcessor}. For every
 * candidate bean it inspects declared methods; on each {@code @MeshA2A} hit it
 * captures the annotation metadata + handler reference into a
 * {@link MeshA2ARegistry.SurfaceMetadata} record. The dispatcher
 * ({@link MeshA2ADispatcher}) and card builder ({@link MeshA2ACardBuilder})
 * consult the registry at request time.
 *
 * <p>Unlike {@link MeshRouteBeanPostProcessor} this processor does not gate on
 * {@code @RestController} / {@code @Controller} class-level annotations:
 * {@code @MeshA2A} methods can live on any Spring bean (e.g. {@code @Component},
 * {@code @Service}). The dispatch path is entirely framework-mounted, so the
 * user's bean type is irrelevant.
 */
public class MeshA2ABeanPostProcessor implements BeanPostProcessor {

    private static final Logger log = LoggerFactory.getLogger(MeshA2ABeanPostProcessor.class);

    private final MeshA2ARegistry registry;

    public MeshA2ABeanPostProcessor(MeshA2ARegistry registry) {
        this.registry = registry;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        Class<?> targetClass = ClassUtils.getUserClass(AopUtils.getTargetClass(bean));

        // Issue #1569: select over the full method set, inherited handlers
        // included — getDeclaredMethods() missed a @MeshA2A declared on a base
        // class. MethodIntrospector (as for @MeshTool, #1164) collapses an
        // override annotated on both levels, and generic bridge methods, onto
        // the single most-derived declaration, so nothing registers twice and
        // trips the duplicate-path guard in MeshA2ARegistry.
        //
        // This runs for every singleton, so — like Spring's own
        // EventListenerMethodProcessor — skip classes that cannot carry the
        // annotation, and treat an unresolvable signature (a type missing from
        // the classpath) as "no handlers" rather than failing the boot.
        if (!AnnotationUtils.isCandidateClass(targetClass, MeshA2A.class)) {
            return bean;
        }
        Map<Method, MeshA2A> annotated;
        try {
            annotated = MethodIntrospector.selectMethods(targetClass,
                (MethodIntrospector.MetadataLookup<MeshA2A>) method ->
                    method.isBridge() || method.isSynthetic()
                        ? null
                        : AnnotationUtils.findAnnotation(method, MeshA2A.class));
        } catch (Exception | LinkageError ex) {
            log.debug("Could not resolve methods of bean '{}' ({}) for @MeshA2A scanning",
                beanName, targetClass.getName(), ex);
            return bean;
        }

        for (Map.Entry<Method, MeshA2A> entry : annotated.entrySet()) {
            Method method = entry.getKey();
            MeshA2A annotation = entry.getValue();

            String auth = annotation.auth() == null ? "" : annotation.auth();
            if (!auth.isEmpty() && !"bearer".equals(auth)) {
                throw new IllegalStateException(
                    "@MeshA2A on " + targetClass.getName() + "#" + method.getName()
                        + ": auth must be \"\" or \"bearer\" (got '" + auth + "'). "
                        + "Spec §6 only defines the bearer scheme in Phase 1.");
            }

            List<MeshRouteRegistry.DependencySpec> deps = new ArrayList<>();
            for (MeshDependency dep : annotation.dependencies()) {
                // Issue #1572: a malformed "a|b" selector tag fails the boot here.
                io.mcpmesh.spring.MeshTagSpecs.validate(dep.tags(), "@MeshA2A '"
                    + targetClass.getName() + "#" + method.getName() + "' dependency '"
                    + dep.capability() + "'");
                deps.add(MeshRouteRegistry.DependencySpec.fromAnnotation(dep));
            }

            // Issue #1401: @MeshA2A binds positionally. Fail the boot on a
            // @MeshInject value that contradicts the position, and warn on a
            // handler still shaped for the pre-3.4 name-based binding.
            MeshLegacyBindingDetector.inspectA2A(method, deps);

            // Issue #1568: the McpMeshTool<T> argument of the parameter each
            // dependency positionally binds to types that dependency's proxy.
            MeshRouteBeanPostProcessor.applySlotReturnTypes(
                method, targetClass, MeshInjectableSlots.a2aSlots(method), deps);

            String handlerMethodId = targetClass.getName() + "." + method.getName();
            MeshA2ARegistry.SurfaceMetadata metadata = new MeshA2ARegistry.SurfaceMetadata(
                annotation.path(),
                annotation.skillId(),
                annotation.skillName(),
                annotation.description(),
                Arrays.asList(annotation.tags()),
                deps,
                auth,
                handlerMethodId,
                bean,
                method
            );

            registry.register(metadata);
            log.debug("@MeshA2A: {} → {} (auth='{}', deps={})",
                metadata.path(), handlerMethodId, auth, deps.size());
        }

        return bean;
    }
}
