package io.mcpmesh.spring.svnonbean;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;

/**
 * RFC #1280 phase-3 review (MED-3): a @McpMeshService producer CLASS that is NOT
 * a Spring bean — must produce a WARN (soft-fail), not silence.
 */
public final class NonBeanFixtures {

    private NonBeanFixtures() {
    }

    @McpMeshService("orphan")
    public static class NonBeanProducer {
        public String go(@Param("x") String x) {
            return x;
        }
    }
}
