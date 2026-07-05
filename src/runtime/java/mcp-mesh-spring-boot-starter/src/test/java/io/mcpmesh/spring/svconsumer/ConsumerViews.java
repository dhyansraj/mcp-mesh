package io.mcpmesh.spring.svconsumer;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

/**
 * Consumer-only gate fixture (MED-12): an app whose ONLY mesh surface is a
 * service view must boot name-less as a mesh consumer.
 */
public final class ConsumerViews {

    private ConsumerViews() {
    }

    @McpMeshService
    public interface ConsumerView {
        @Selector(capability = "consumer.only")
        String fetch();
    }
}
