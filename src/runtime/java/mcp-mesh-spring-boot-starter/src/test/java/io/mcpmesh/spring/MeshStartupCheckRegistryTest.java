package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshStartupCheck;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.*;

/**
 * The startup verdict rules (RFC #1502).
 *
 * <p>Each is the OPPOSITE of the corresponding {@code @MeshHealthCheck} rule,
 * and that is the point of the file: a throw FAILS here (it degrades there),
 * and there is no partial credit for {@code DEGRADED}. See
 * {@link MeshStartupCheckRegistry} for why.
 */
class MeshStartupCheckRegistryTest {

    static class Checks {

        @MeshStartupCheck
        public boolean passes() {
            return true;
        }

        @MeshStartupCheck
        public boolean fails() {
            return false;
        }

        @MeshStartupCheck
        public boolean throwsUp() {
            throw new IllegalStateException("ANTHROPIC_API_KEY is not set");
        }

        @MeshStartupCheck
        public MeshHealth healthy() {
            return MeshHealth.healthy().withCheck("api_key_present", true);
        }

        @MeshStartupCheck
        public MeshHealth unhealthy() {
            return MeshHealth.unhealthy("no key").withCheck("api_key_present", false);
        }

        @MeshStartupCheck
        public MeshHealth degraded() {
            return new MeshHealth(io.mcpmesh.MeshHealthStatus.DEGRADED, null, null);
        }
    }

    private static MeshStartupCheckRegistry registryFor(String methodName) throws Exception {
        MeshStartupCheckRegistry registry = new MeshStartupCheckRegistry();
        Method method = Checks.class.getMethod(methodName);
        registry.register(new Checks(), method);
        return registry;
    }

    @Test
    void noCheckDeclared_passes() {
        MeshStartupCheckRegistry registry = new MeshStartupCheckRegistry();
        assertFalse(registry.hasStartupCheck());
        assertTrue(registry.execute().passed(),
            "an agent that declares no startup check must behave exactly as it does today");
    }

    @Test
    void trueReturn_passes() throws Exception {
        MeshStartupCheckRegistry.Verdict verdict = registryFor("passes").execute();
        assertTrue(verdict.passed());
        assertTrue(verdict.errors().isEmpty());
    }

    @Test
    void falseReturn_fails() throws Exception {
        MeshStartupCheckRegistry.Verdict verdict = registryFor("fails").execute();
        assertFalse(verdict.passed());
        assertEquals("Startup check returned false", verdict.errors().get(0));
        assertEquals(Boolean.FALSE, verdict.checks().get("startup_check"));
    }

    @Test
    void aThrow_failsRatherThanDegrading() throws Exception {
        // The opposite of MeshHealthCheckRegistry.execute(), where a throw is
        // DEGRADED so a buggy probe cannot withdraw a working provider. At boot
        // an indeterminate answer is not a reason to let a possibly
        // misconfigured agent through.
        MeshStartupCheckRegistry.Verdict verdict = registryFor("throwsUp").execute();
        assertFalse(verdict.passed());
        assertEquals(Boolean.FALSE, verdict.checks().get("startup_check_execution"));
        assertTrue(verdict.errors().get(0).contains("ANTHROPIC_API_KEY is not set"));
    }

    @Test
    void meshHealthHealthy_passesAndCarriesItsChecks() throws Exception {
        MeshStartupCheckRegistry.Verdict verdict = registryFor("healthy").execute();
        assertTrue(verdict.passed());
        assertEquals(Boolean.TRUE, verdict.checks().get("api_key_present"));
    }

    @Test
    void meshHealthUnhealthy_fails() throws Exception {
        MeshStartupCheckRegistry.Verdict verdict = registryFor("unhealthy").execute();
        assertFalse(verdict.passed());
        assertEquals("no key", verdict.errors().get(0));
    }

    @Test
    void degraded_failsThereIsNoPartialCredit() throws Exception {
        MeshStartupCheckRegistry.Verdict verdict = registryFor("degraded").execute();
        assertFalse(verdict.passed());
        assertEquals("Startup check reported 'degraded'", verdict.errors().get(0));
    }

    @Test
    void anUnrecognizedReturn_fails() {
        MeshStartupCheckRegistry.Verdict verdict = MeshStartupCheckRegistry.coerce("yes");
        assertFalse(verdict.passed());
        assertEquals(Boolean.FALSE, verdict.checks().get("startup_check_return_type"));
        assertTrue(verdict.errors().get(0).contains("java.lang.String"));
    }

    @Test
    void nullReturn_fails() {
        assertFalse(MeshStartupCheckRegistry.coerce(null).passed());
    }

    @Test
    void theCheckRunsOnEveryCall_thereIsNoCache() throws Exception {
        class Counting {
            int calls;

            @MeshStartupCheck
            public boolean check() {
                calls++;
                return true;
            }
        }
        Counting bean = new Counting();
        MeshStartupCheckRegistry registry = new MeshStartupCheckRegistry();
        registry.register(bean, Counting.class.getMethod("check"));

        registry.execute();
        registry.execute();
        registry.execute();
        assertEquals(3, bean.calls,
            "startupProbe stops polling on first success — there is nothing to cache");
    }

    @Test
    void twoChecks_isRejected() throws Exception {
        MeshStartupCheckRegistry registry = registryFor("passes");
        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> registry.register(new Checks(), Checks.class.getMethod("fails")));
        assertTrue(e.getMessage().contains("Two @MeshStartupCheck methods"));
    }
}
