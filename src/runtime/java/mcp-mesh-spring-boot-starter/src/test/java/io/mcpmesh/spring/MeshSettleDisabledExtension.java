package io.mcpmesh.spring;

import org.junit.jupiter.api.extension.BeforeAllCallback;
import org.junit.jupiter.api.extension.ExtensionContext;

/**
 * Suite-wide settling-window opt-out (issue #1193) — the Java analogue of
 * the Python {@code tests/unit} conftest fixture and the TypeScript
 * suite-level {@code MCP_MESH_SETTLE_TIMEOUT=0}.
 *
 * <p>Auto-registered for EVERY test class via
 * {@code META-INF/services/org.junit.jupiter.api.extension.Extension} plus
 * {@code junit.jupiter.extensions.autodetection.enabled} in
 * {@code junit-platform.properties}, so the opt-out never depends on test
 * class execution order: {@link MeshSettleState} is JVM-static and its
 * default instance reads the environment (default 20s window) at first
 * class touch — without this, whichever test class happened to touch it
 * first would inherit a live window. Installing a DISABLED (timeout=0)
 * state in {@code beforeAll} of every class makes the suite posture
 * deterministic; {@link MeshSettleStateTest} arms explicit windows per
 * test via {@code resetForTests(double)} on top of this baseline.
 */
public final class MeshSettleDisabledExtension implements BeforeAllCallback {

    @Override
    public void beforeAll(ExtensionContext context) {
        MeshSettleState.resetForTests();
    }
}
