package io.mcpmesh.spring.web;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.annotation.AnnotationUtils;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

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
        Class<?> targetClass = AopUtils.getTargetClass(bean);

        for (Method method : targetClass.getDeclaredMethods()) {
            // Skip compiler-generated bridge/synthetic methods. Generic erasure
            // causes javac to emit a bridge method alongside the real handler,
            // and AnnotationUtils#findAnnotation returns the same annotation
            // on both — double-registering the surface (and tripping the
            // duplicate-path guard in MeshA2ARegistry).
            if (method.isBridge() || method.isSynthetic()) {
                continue;
            }
            MeshA2A annotation = AnnotationUtils.findAnnotation(method, MeshA2A.class);
            if (annotation == null) {
                continue;
            }

            String auth = annotation.auth() == null ? "" : annotation.auth();
            if (!auth.isEmpty() && !"bearer".equals(auth)) {
                throw new IllegalStateException(
                    "@MeshA2A on " + targetClass.getName() + "#" + method.getName()
                        + ": auth must be \"\" or \"bearer\" (got '" + auth + "'). "
                        + "Spec §6 only defines the bearer scheme in Phase 1.");
            }

            List<MeshRouteRegistry.DependencySpec> deps = new ArrayList<>();
            for (MeshDependency dep : annotation.dependencies()) {
                deps.add(MeshRouteRegistry.DependencySpec.fromAnnotation(dep));
            }

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
