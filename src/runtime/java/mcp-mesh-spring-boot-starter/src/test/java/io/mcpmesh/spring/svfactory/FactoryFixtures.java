package io.mcpmesh.spring.svfactory;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;

/**
 * RFC #1280 phase-3 review (item 2): a producer registered via a @Bean factory
 * method whose DECLARED return type is an interface/supertype. A bean-definition
 * scan would false-positive (getBeanClassName null, ResolvableType = the
 * interface), so the WARN must compare against ground-truth published classes.
 */
public final class FactoryFixtures {

    private FactoryFixtures() {
    }

    public interface MediaApi {
    }

    @McpMeshService("fmedia")
    public static class MediaImpl implements MediaApi {
        public String go(@Param("x") String x) {
            return x;
        }
    }
}
