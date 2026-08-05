package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthCheck;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.MethodIntrospector;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.AnnotationUtils;

import java.lang.reflect.Method;
import java.util.Map;

/**
 * Discovers the {@link MeshHealthCheck} method (issue #1474).
 *
 * <p>Same shape as {@link MeshToolBeanPostProcessor} and
 * {@link io.mcpmesh.spring.web.MeshRouteBeanPostProcessor}: scan every bean,
 * unwrap CGLIB proxies, select methods with {@link MethodIntrospector} so an
 * inherited or bridged declaration is visited once, and register into a
 * registry the rest of the starter reads.
 *
 * <p>Spring Actuator's {@code HealthIndicator} was considered and rejected: it
 * is not a dependency of the starter, and it AGGREGATES every registered
 * indicator (datasource, disk, mail, ...), so mesh routing would start gating
 * on conditions the author never intended to affect it. Mesh gates on what the
 * developer says gates traffic.
 *
 * <h2>Boot-time validation</h2>
 *
 * <p>The signature is checked here rather than coerced at runtime. A health
 * check whose shape is wrong is a check that does not work, and finding that
 * out from a {@code degraded} verdict on a running provider is the failure mode
 * this whole feature exists to avoid.
 */
public class MeshHealthCheckBeanPostProcessor implements BeanPostProcessor, Ordered {

    private static final Logger log =
        LoggerFactory.getLogger(MeshHealthCheckBeanPostProcessor.class);

    private final MeshHealthCheckRegistry registry;

    public MeshHealthCheckBeanPostProcessor(MeshHealthCheckRegistry registry) {
        this.registry = registry;
    }

    @Override
    public int getOrder() {
        return Ordered.LOWEST_PRECEDENCE;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        Class<?> targetClass = AopUtils.getTargetClass(bean);

        Map<Method, MeshHealthCheck> annotated = MethodIntrospector.selectMethods(targetClass,
            (MethodIntrospector.MetadataLookup<MeshHealthCheck>) method ->
                AnnotationUtils.findAnnotation(method, MeshHealthCheck.class));

        annotated.forEach((method, annotation) -> {
            validate(targetClass, method, annotation);
            registry.register(bean, method, annotation.ttlSeconds());
        });

        return bean;
    }

    private static void validate(Class<?> targetClass, Method method, MeshHealthCheck annotation) {
        String where = "@MeshHealthCheck on '" + targetClass.getName() + "#" + method.getName() + "'";

        if (method.getParameterCount() != 0) {
            throw new IllegalStateException(where + " must take no parameters — it is called on a "
                + "timer with nothing to pass it. Read what it needs from the enclosing bean.");
        }

        Class<?> returnType = method.getReturnType();
        boolean supported = MeshHealth.class.equals(returnType)
            || boolean.class.equals(returnType)
            || Boolean.class.equals(returnType);
        if (!supported) {
            throw new IllegalStateException(where + " returns " + returnType.getName()
                + ", which the runtime cannot read as a health verdict. Return "
                + MeshHealth.class.getName() + " (status + checks + errors) or boolean "
                + "(true = healthy, false = unhealthy).");
        }

        if (annotation.ttlSeconds() < 1) {
            throw new IllegalStateException(where + " has ttlSeconds=" + annotation.ttlSeconds()
                + "; it must be at least 1 second.");
        }

        log.debug("Found {} returning {} (ttl={}s)", where, returnType.getSimpleName(),
            annotation.ttlSeconds());
    }
}
