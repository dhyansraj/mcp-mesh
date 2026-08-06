package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshStartupCheck;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Discovery and boot-time validation of {@code @MeshStartupCheck} (RFC #1502).
 *
 * <p>The shape is rejected at BOOT, not coerced at runtime — and it matters
 * more here than for the health check: a startup check with the wrong shape
 * fails its probe forever, which is a CrashLoopBackOff whose only stated cause
 * is "startup probe failed".
 */
class MeshStartupCheckBeanPostProcessorTest {

    static class ValidBoolean {
        @MeshStartupCheck
        public boolean check() {
            return true;
        }
    }

    static class ValidMeshHealth {
        @MeshStartupCheck
        public MeshHealth check() {
            return MeshHealth.healthy();
        }
    }

    static class TakesParameters {
        @MeshStartupCheck
        public boolean check(String why) {
            return true;
        }
    }

    static class WrongReturnType {
        @MeshStartupCheck
        public String check() {
            return "ok";
        }
    }

    static class VoidReturn {
        @MeshStartupCheck
        public void check() {
        }
    }

    static class TwoChecks {
        @MeshStartupCheck
        public boolean first() {
            return true;
        }

        @MeshStartupCheck
        public MeshHealth second() {
            return MeshHealth.healthy();
        }
    }

    static class NoAnnotation {
        public boolean check() {
            return true;
        }
    }

    /** Both hooks on one bean: they are independent verdicts. */
    static class BothHooks {
        @io.mcpmesh.MeshHealthCheck
        public boolean health() {
            return true;
        }

        @MeshStartupCheck
        public boolean startup() {
            return true;
        }
    }

    private static MeshStartupCheckRegistry process(Object bean) {
        MeshStartupCheckRegistry registry = new MeshStartupCheckRegistry();
        new MeshStartupCheckBeanPostProcessor(registry)
            .postProcessAfterInitialization(bean, "bean");
        return registry;
    }

    @Test
    void discoversABooleanCheck() {
        MeshStartupCheckRegistry registry = process(new ValidBoolean());
        assertTrue(registry.hasStartupCheck());
        assertEquals("check", registry.registration().method().getName());
    }

    @Test
    void discoversAMeshHealthCheck() {
        assertTrue(process(new ValidMeshHealth()).hasStartupCheck());
    }

    @Test
    void ignoresBeansWithoutTheAnnotation() {
        assertFalse(process(new NoAnnotation()).hasStartupCheck());
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
        assertTrue(e.getMessage().contains("cannot read as a startup verdict"), e.getMessage());
        assertThrows(IllegalStateException.class, () -> process(new VoidReturn()));
    }

    @Test
    void rejectsTwoChecksOnOneBean() {
        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> process(new TwoChecks()));
        assertTrue(e.getMessage().contains("Two @MeshStartupCheck methods"), e.getMessage());
    }

    @Test
    void theTwoHooksAreIndependent() {
        BothHooks bean = new BothHooks();

        MeshStartupCheckRegistry startup = new MeshStartupCheckRegistry();
        new MeshStartupCheckBeanPostProcessor(startup)
            .postProcessAfterInitialization(bean, "bean");
        MeshHealthCheckRegistry health = new MeshHealthCheckRegistry();
        new MeshHealthCheckBeanPostProcessor(health)
            .postProcessAfterInitialization(bean, "bean");

        assertEquals("startup", startup.registration().method().getName());
        assertEquals("health", health.registration().method().getName());
    }
}
