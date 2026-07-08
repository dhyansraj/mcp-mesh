package com.example.thumbnailprovider;

import io.mcpmesh.MeshAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * ThumbnailProvider - one leaf of the {@code @McpMeshService} service-view demo.
 *
 * <p>Agent bootstrap only. The capability is published by
 * {@link MediaThumbnailService}, whose {@code thumbnail(...)} method carries
 * {@code @MeshTool(capability = "media.thumbnail")}. The {@code media-gateway}
 * consumer binds it through the OPTIONAL {@code MediaService.thumbnail(...)} view
 * method — stop this agent and the gateway degrades gracefully while
 * {@code media.caption} and {@code media.transcribe} keep working.
 */
@MeshAgent(
    name = "thumbnail-provider",
    version = "1.0.0",
    description = "Publishes media.thumbnail into the shared media.* namespace",
    port = 8111
)
@SpringBootApplication
public class ThumbnailProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(ThumbnailProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting ThumbnailProvider Agent...");
        SpringApplication.run(ThumbnailProviderApplication.class, args);
    }
}
