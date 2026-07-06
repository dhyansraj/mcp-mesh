package io.mcpmesh.spring.svprod;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;

/**
 * RFC #1280 phase-3 end-to-end fixtures: a PRODUCER class publishing
 * {@code media.*} tools and a CONSUMER view binding one of them — within a
 * single agent.
 */
public final class ProdFixtures {

    private ProdFixtures() {
    }

    /** Producer: publishes "media.caption" and "media.thumbnail". */
    @McpMeshService("media")
    public static class MediaProducer {
        public String caption(@Param("text") String text) {
            return "cap:" + text;
        }

        public String thumbnail(@Param("assetId") String assetId) {
            return "thumb:" + assetId;
        }
    }

    /** Consumer view binding the producer's capability by name. */
    @McpMeshService
    public interface MediaConsumerView {
        @Selector(capability = "media.caption")
        String caption(@Param("text") String text);
    }
}
