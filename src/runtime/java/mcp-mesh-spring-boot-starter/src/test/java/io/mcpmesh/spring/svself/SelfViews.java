package io.mcpmesh.spring.svself;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

/**
 * Self-produced capability fixture (MED-6): the view binds a capability the
 * agent also produces via {@code @MeshTool}. The edge must be deduped away with
 * a WARN and markResolved so the eager-settle latch is not stranded.
 */
public final class SelfViews {

    private SelfViews() {
    }

    @McpMeshService
    public interface SelfView {
        @Selector(capability = "self.produced")
        String get();
    }
}
