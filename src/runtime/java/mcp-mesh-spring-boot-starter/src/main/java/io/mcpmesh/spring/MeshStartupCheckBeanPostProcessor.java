package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshStartupCheck;
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
 * Discovers the {@link MeshStartupCheck} method (RFC #1502).
 *
 * <p>Same shape as {@link MeshHealthCheckBeanPostProcessor}, including the
 * proxy-unwrapping rule: reflect on, and invoke against, the SAME object, or a
 * JDK dynamic proxy's method cannot be invoked with the proxy as receiver.
 *
 * <h2>Boot-time validation</h2>
 *
 * <p>The signature is checked here rather than coerced at runtime — and it
 * matters more for this hook than for the health check. A startup check with a
 * wrong shape would fail its endpoint forever, and once the chart's
 * {@code startupProbe} points at {@code /startupz} (RFC #1502 step 2) that is a
 * {@code CrashLoopBackOff} whose only stated cause is "startup probe failed".
 * Failing the boot names the method instead.
 */
public class MeshStartupCheckBeanPostProcessor implements BeanPostProcessor, Ordered {

    private static final Logger log =
        LoggerFactory.getLogger(MeshStartupCheckBeanPostProcessor.class);

    private final MeshStartupCheckRegistry registry;

    public MeshStartupCheckBeanPostProcessor(MeshStartupCheckRegistry registry) {
        this.registry = registry;
    }

    @Override
    public int getOrder() {
        return Ordered.LOWEST_PRECEDENCE;
    }

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        Object receiver = AopProxyUtils.getSingletonTarget(bean);
        if (receiver == null) {
            receiver = bean;
        }
        Class<?> targetClass = AopUtils.getTargetClass(receiver);
        if (!targetClass.isInstance(receiver)) {
            targetClass = receiver.getClass();
        }

        Map<Method, MeshStartupCheck> annotated = MethodIntrospector.selectMethods(targetClass,
            (MethodIntrospector.MetadataLookup<MeshStartupCheck>) method ->
                AnnotationUtils.findAnnotation(method, MeshStartupCheck.class));

        Object registrationTarget = receiver;
        Class<?> registrationClass = targetClass;
        annotated.forEach((method, annotation) -> {
            validate(registrationClass, method);
            registry.register(registrationTarget, method);
        });

        return bean;
    }

    private static void validate(Class<?> targetClass, Method method) {
        String where = "@MeshStartupCheck on '" + targetClass.getName() + "#" + method.getName() + "'";

        if (method.getParameterCount() != 0) {
            throw new IllegalStateException(where + " must take no parameters — it is called by "
                + "the startup probe with nothing to pass it. Read what it needs from the "
                + "enclosing bean.");
        }

        Class<?> returnType = method.getReturnType();
        boolean supported = boolean.class.equals(returnType)
            || Boolean.class.equals(returnType)
            || MeshHealth.class.equals(returnType);
        if (!supported) {
            throw new IllegalStateException(where + " returns " + returnType.getName()
                + ", which the runtime cannot read as a startup verdict. Return boolean "
                + "(true = start, false = do not) or " + MeshHealth.class.getName()
                + " (only HEALTHY passes).");
        }

        log.debug("Found {} returning {}", where, returnType.getSimpleName());
    }
}
