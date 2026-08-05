package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthCheck;
import io.mcpmesh.MeshHealthStatus;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Verdict conversion and storage for {@code @MeshHealthCheck} (issue #1474).
 *
 * <p>The load-bearing assertion here is the asymmetry #1472 established and
 * this change had to mirror: only an EXPLICIT unhealthy result withdraws an
 * agent. A check that throws, or whose verdict cannot be read, is DEGRADED —
 * it keeps heartbeating.
 */
class MeshHealthCheckRegistryTest {

    static class Checks {
        boolean fail = false;

        @MeshHealthCheck
        public MeshHealth detailed() {
            return fail
                ? MeshHealth.unhealthy("vendor down").withCheck("vendor_reachable", false)
                : MeshHealth.healthy().withCheck("vendor_reachable", true);
        }

        @MeshHealthCheck
        public boolean terse() {
            return !fail;
        }

        @MeshHealthCheck
        public MeshHealth explodes() {
            throw new IllegalStateException("connection pool is null");
        }

        @MeshHealthCheck(ttlSeconds = 30)
        public MeshHealth withTtl() {
            return MeshHealth.healthy();
        }
    }

    private static MeshHealthCheckRegistry registryFor(Checks bean, String methodName) {
        try {
            Method method = Checks.class.getMethod(methodName);
            MeshHealthCheckRegistry registry = new MeshHealthCheckRegistry();
            MeshHealthCheck annotation = method.getAnnotation(MeshHealthCheck.class);
            registry.register(bean, method, annotation.ttlSeconds());
            return registry;
        } catch (NoSuchMethodException e) {
            throw new AssertionError(e);
        }
    }

    @Test
    void meshHealthResultPassesThroughWithItsDetail() {
        Checks bean = new Checks();
        MeshHealthCheckRegistry registry = registryFor(bean, "detailed");

        MeshHealth healthy = registry.execute();
        assertEquals(MeshHealthStatus.HEALTHY, healthy.status());
        assertEquals(Boolean.TRUE, healthy.checks().get("vendor_reachable"));
        assertTrue(healthy.errors().isEmpty());

        bean.fail = true;
        MeshHealth unhealthy = registry.execute();
        assertEquals(MeshHealthStatus.UNHEALTHY, unhealthy.status());
        assertEquals(Boolean.FALSE, unhealthy.checks().get("vendor_reachable"));
        assertEquals(java.util.List.of("vendor down"), unhealthy.errors());
    }

    @Test
    void booleanReturnMapsTrueToHealthyAndFalseToUnhealthy() {
        // Python parity: bool True → HEALTHY, False → UNHEALTHY.
        Checks bean = new Checks();
        MeshHealthCheckRegistry registry = registryFor(bean, "terse");

        assertEquals(MeshHealthStatus.HEALTHY, registry.execute().status());

        bean.fail = true;
        MeshHealth unhealthy = registry.execute();
        assertEquals(MeshHealthStatus.UNHEALTHY, unhealthy.status());
        assertEquals(Boolean.FALSE, unhealthy.checks().get("health_check"));
        assertFalse(unhealthy.errors().isEmpty());
    }

    @Test
    void aCheckThatThrowsIsDegradedNotUnhealthy() {
        // The crux: a buggy health check must not nuke a working agent. DEGRADED
        // keeps heartbeating; UNHEALTHY would withdraw it from resolution.
        MeshHealthCheckRegistry registry = registryFor(new Checks(), "explodes");

        MeshHealth health = registry.execute();
        assertEquals(MeshHealthStatus.DEGRADED, health.status(),
            "an exception must not withdraw the agent");
        assertEquals(Boolean.FALSE, health.checks().get("health_check_execution"));
        assertEquals(1, health.errors().size());
        assertTrue(health.errors().get(0).contains("connection pool is null"));
    }

    @Test
    void anUnreadableReturnValueIsDegradedNotUnhealthy() {
        // Unreachable through the annotation (the post-processor rejects the
        // shape at boot) — asserted so the defensive branch cannot drift into
        // withdrawing an agent over a reporting defect.
        MeshHealth health = MeshHealthCheckRegistry.coerce("healthy-ish");
        assertEquals(MeshHealthStatus.DEGRADED, health.status());
        assertEquals(Boolean.FALSE, health.checks().get("health_check_return_type"));

        assertEquals(MeshHealthStatus.DEGRADED, MeshHealthCheckRegistry.coerce(null).status());
    }

    @Test
    void executeReturnsNullWithNoRegisteredCheck() {
        assertNull(new MeshHealthCheckRegistry().execute());
        assertFalse(new MeshHealthCheckRegistry().hasHealthCheck());
        assertNull(new MeshHealthCheckRegistry().latest());
    }

    @Test
    void aSecondHealthCheckFailsFastRatherThanPickingOne() {
        Checks bean = new Checks();
        MeshHealthCheckRegistry registry = registryFor(bean, "detailed");

        Method second;
        try {
            second = Checks.class.getMethod("terse");
        } catch (NoSuchMethodException e) {
            throw new AssertionError(e);
        }
        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> registry.register(bean, second, 15));
        assertTrue(e.getMessage().contains("Two @MeshHealthCheck methods"));
    }

    @Test
    void ttlComesFromTheAnnotation() {
        assertEquals(30, registryFor(new Checks(), "withTtl").ttlSeconds());
        assertEquals(15, registryFor(new Checks(), "detailed").ttlSeconds(),
            "default must match Python's health_check_ttl");
        assertEquals(MeshHealthCheckRegistry.DEFAULT_TTL_SECONDS,
            new MeshHealthCheckRegistry().ttlSeconds());
    }

    @Test
    void storeAndLatestRoundTripWithATimestamp() {
        MeshHealthCheckRegistry registry = registryFor(new Checks(), "detailed");
        assertNull(registry.latest());

        MeshHealth health = MeshHealth.degraded("slow");
        registry.store(health);

        assertSame(health, registry.latest().health());
        assertNotNull(registry.latest().timestamp());
    }
}
