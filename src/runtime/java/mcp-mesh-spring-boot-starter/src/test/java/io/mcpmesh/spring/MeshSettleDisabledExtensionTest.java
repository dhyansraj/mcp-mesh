package io.mcpmesh.spring;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Pins the suite-wide settle opt-out (issue #1193): the auto-registered
 * {@link MeshSettleDisabledExtension} must have installed a DISABLED
 * (timeout=0) settle state before this class's tests run — WITHOUT this
 * class arming anything itself. Run in isolation this is a hard proof the
 * autodetection wiring (junit-platform.properties + META-INF/services)
 * engages: the default JVM-static instance reads the environment (20s
 * window) at class load and would NOT be settled here.
 */
class MeshSettleDisabledExtensionTest {

    @Test
    void everyTestClassStartsWithADisabledSettleWindow() {
        MeshSettleState state = MeshSettleState.getInstance();
        assertTrue(state.isSettled(),
            "auto-registered extension must install a disabled (timeout=0) window before each class");
        state.registerDeclared("never_resolved_cap");
        long start = System.nanoTime();
        state.awaitDependency("never_resolved_cap", "never_resolved_cap");
        assertTrue((System.nanoTime() - start) / 1_000_000 < 50,
            "disabled window must never wait");
        assertEquals(0, state.getWaitCount());
    }
}
