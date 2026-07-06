package com.example.captionprovider;

import io.mcpmesh.MeshAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * CaptionProvider - one leaf of the {@code @McpMeshService} service-view demo.
 *
 * <p>Agent bootstrap only. The capability itself is published by the
 * producer-sugar bean {@link MediaCaptionService}: a class annotated
 * {@code @McpMeshService("media")} publishes each public method as
 * {@code media.<methodName>}, so its {@code caption(...)} method becomes the
 * dotted capability {@code media.caption} — one slice of the shared
 * {@code media.*} namespace that {@code thumbnail-provider} and
 * {@code transcribe-provider} also publish into.
 */
@MeshAgent(
    name = "caption-provider",
    version = "1.0.0",
    description = "Publishes media.caption into the shared media.* namespace",
    port = 8110
)
@SpringBootApplication
public class CaptionProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(CaptionProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting CaptionProvider Agent...");
        SpringApplication.run(CaptionProviderApplication.class, args);
    }
}
