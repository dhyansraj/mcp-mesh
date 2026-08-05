package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthCheck;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Discovery and boot-time validation of {@code @MeshHealthCheck} (issue #1474).
 *
 * <p>The shape is rejected at BOOT, not coerced at runtime: a health check with
 * the wrong signature is a health check that does not work, and learning that
 * from a permanently-degraded verdict on a live provider is exactly the failure
 * this feature exists to prevent.
 */
class MeshHealthCheckBeanPostProcessorTest {

    static class Valid {
        @MeshHealthCheck(ttlSeconds = 30)
        public MeshHealth check() {
            return MeshHealth.healthy();
        }
    }

    static class ValidBoolean {
        @MeshHealthCheck
        public boolean check() {
            return true;
        }
    }

    static class TakesParameters {
        @MeshHealthCheck
        public MeshHealth check(String why) {
            return MeshHealth.healthy();
        }
    }

    static class WrongReturnType {
        @MeshHealthCheck
        public String check() {
            return "healthy";
        }
    }

    static class VoidReturn {
        @MeshHealthCheck
        public void check() {
        }
    }

    static class ZeroTtl {
        @MeshHealthCheck(ttlSeconds = 0)
        public MeshHealth check() {
            return MeshHealth.healthy();
        }
    }

    static class TwoChecks {
        @MeshHealthCheck
        public MeshHealth first() {
            return MeshHealth.healthy();
        }

        @MeshHealthCheck
        public boolean second() {
            return true;
        }
    }

    abstract static class Base {
        @MeshHealthCheck
        public MeshHealth check() {
            return MeshHealth.healthy();
        }
    }

    static class Derived extends Base {
        @Override
        public MeshHealth check() {
            return MeshHealth.degraded("overridden");
        }
    }

    static class NoAnnotation {
        public MeshHealth check() {
            return MeshHealth.healthy();
        }
    }

    /** A JDK-proxyable health check: the annotation lives on the interface. */
    public interface ProxyableCheck {
        @MeshHealthCheck
        MeshHealth check();
    }

    public static class ProxyableCheckImpl implements ProxyableCheck {
        @Override
        public MeshHealth check() {
            return MeshHealth.degraded("from the real target");
        }
    }

    private static MeshHealthCheckRegistry process(Object bean) {
        MeshHealthCheckRegistry registry = new MeshHealthCheckRegistry();
        new MeshHealthCheckBeanPostProcessor(registry)
            .postProcessAfterInitialization(bean, "bean");
        return registry;
    }

    @Test
    void discoversTheAnnotatedMethodAndItsTtl() {
        MeshHealthCheckRegistry registry = process(new Valid());

        assertTrue(registry.hasHealthCheck());
        assertEquals("check", registry.registration().method().getName());
        assertEquals(30, registry.ttlSeconds());
    }

    @Test
    void acceptsABooleanCheck() {
        assertTrue(process(new ValidBoolean()).hasHealthCheck());
    }

    @Test
    void ignoresBeansWithoutTheAnnotation() {
        assertFalse(process(new NoAnnotation()).hasHealthCheck());
    }

    @Test
    void rejectsAMethodWithParameters() {
        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> process(new TakesParameters()));
        assertTrue(e.getMessage().contains("must take no parameters"), e.getMessage());
    }

    @Test
    void rejectsAnUnreadableReturnType() {
        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> process(new WrongReturnType()));
        assertTrue(e.getMessage().contains("cannot read as a health verdict"), e.getMessage());

        // void is the one worth naming: it compiles, reads like a check, and
        // could never report anything.
        assertThrows(IllegalStateException.class, () -> process(new VoidReturn()));
    }

    @Test
    void rejectsANonPositiveTtl() {
        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> process(new ZeroTtl()));
        assertTrue(e.getMessage().contains("at least 1 second"), e.getMessage());
    }

    @Test
    void rejectsTwoChecksOnOneBean() {
        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> process(new TwoChecks()));
        assertTrue(e.getMessage().contains("Two @MeshHealthCheck methods"), e.getMessage());
    }

    @Test
    void rejectsTwoChecksAcrossBeans() {
        MeshHealthCheckRegistry registry = new MeshHealthCheckRegistry();
        MeshHealthCheckBeanPostProcessor processor = new MeshHealthCheckBeanPostProcessor(registry);
        processor.postProcessAfterInitialization(new Valid(), "a");

        assertThrows(IllegalStateException.class,
            () -> processor.postProcessAfterInitialization(new ValidBoolean(), "b"));
    }

    @Test
    void aSpringJdkDynamicProxyBeanIsStillInvocable() {
        // A Spring JDK proxy is TargetClassAware, so AopUtils.getTargetClass
        // returns ProxyableCheckImpl — but the proxy itself does NOT extend it
        // (it implements the interface and extends java.lang.reflect.Proxy).
        // Registering the PROXY alongside a Method resolved on the TARGET CLASS
        // makes Method.invoke throw "object is not an instance of declaring
        // class", which the registry reports as DEGRADED forever: an agent
        // whose health check silently never works. Spring produces JDK proxies
        // for any interface-implementing bean under proxyTargetClass=false
        // (@Transactional, @Async, @Validated, ...).
        org.springframework.aop.framework.ProxyFactory factory =
            new org.springframework.aop.framework.ProxyFactory(new ProxyableCheckImpl());
        factory.setInterfaces(ProxyableCheck.class);
        factory.setProxyTargetClass(false);
        Object proxy = factory.getProxy();

        assertTrue(java.lang.reflect.Proxy.isProxyClass(proxy.getClass()),
            "fixture must produce a JDK proxy, not CGLIB");
        assertEquals(ProxyableCheckImpl.class,
            org.springframework.aop.support.AopUtils.getTargetClass(proxy),
            "fixture must be TargetClassAware — that is what creates the mismatch");

        MeshHealthCheckRegistry registry = new MeshHealthCheckRegistry();
        new MeshHealthCheckBeanPostProcessor(registry)
            .postProcessAfterInitialization(proxy, "proxied");

        assertTrue(registry.hasHealthCheck());
        MeshHealth health = registry.execute();
        assertEquals(io.mcpmesh.MeshHealthStatus.DEGRADED, health.status());
        assertEquals(java.util.List.of("from the real target"), health.errors(),
            "the check must actually run, not fail into a DEGRADED placeholder");
    }

    @Test
    void aCglibProxyBeanIsStillInvocable() {
        org.springframework.aop.framework.ProxyFactory factory =
            new org.springframework.aop.framework.ProxyFactory(new ProxyableCheckImpl());
        factory.setProxyTargetClass(true);
        Object proxy = factory.getProxy();

        MeshHealthCheckRegistry registry = new MeshHealthCheckRegistry();
        new MeshHealthCheckBeanPostProcessor(registry)
            .postProcessAfterInitialization(proxy, "proxied");

        assertEquals(java.util.List.of("from the real target"), registry.execute().errors());
    }

    @Test
    void anInheritedCheckRegistersOnceAndInvokesTheOverride() {
        // A bare ReflectionUtils walk visits an overridden method once per
        // declaring class plus bridges — which here would trip the
        // "two health checks" guard on a single legitimate check.
        MeshHealthCheckRegistry registry = process(new Derived());

        assertTrue(registry.hasHealthCheck());
        assertEquals(io.mcpmesh.MeshHealthStatus.DEGRADED, registry.execute().status(),
            "must dispatch to the most-derived declaration");
    }
}
