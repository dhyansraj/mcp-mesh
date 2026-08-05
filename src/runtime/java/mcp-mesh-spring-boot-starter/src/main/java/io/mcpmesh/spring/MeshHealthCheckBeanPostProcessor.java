package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthCheck;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.aop.framework.AopProxyUtils;
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
        // Reflect on, and invoke against, the SAME object (issue #1474 review).
        //
        // A Spring JDK dynamic proxy is TargetClassAware, so getTargetClass
        // returns the target class — but the proxy does not EXTEND it (it
        // implements the interface and extends java.lang.reflect.Proxy). A
        // Method resolved on the target class then cannot be invoked with the
        // proxy as receiver: Method.invoke throws "object is not an instance of
        // declaring class", which the registry records as DEGRADED on every
        // tick — a health check that silently never works. Spring produces JDK
        // proxies for any interface-implementing bean when proxyTargetClass is
        // false (@Transactional, @Async, @Validated, ...).
        //
        // Unwrapping to the singleton target fixes it and is also the right
        // receiver: a health check should run against the real object, not
        // through an advice chain that may open a transaction around it.
        // CGLIB proxies have no such mismatch (the proxy IS a subclass), but
        // unwrapping them is equally correct and keeps one code path.
        Object receiver = AopProxyUtils.getSingletonTarget(bean);
        if (receiver == null) {
            // No singleton target (a prototype-targeted or otherwise opaque
            // proxy). Reflect on the proxy's own runtime type instead, so the
            // Method we register is one the proxy can actually receive.
            receiver = bean;
        }
        Class<?> targetClass = AopUtils.getTargetClass(receiver);
        if (!targetClass.isInstance(receiver)) {
            targetClass = receiver.getClass();
        }

        Map<Method, MeshHealthCheck> annotated = MethodIntrospector.selectMethods(targetClass,
            (MethodIntrospector.MetadataLookup<MeshHealthCheck>) method ->
                AnnotationUtils.findAnnotation(method, MeshHealthCheck.class));

        Object registrationTarget = receiver;
        Class<?> registrationClass = targetClass;
        annotated.forEach((method, annotation) -> {
            validate(registrationClass, method, annotation);
            registry.register(registrationTarget, method, annotation.ttlSeconds());
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
