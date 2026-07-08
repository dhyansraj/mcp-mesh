package com.example.transcribeprovider;

import io.mcpmesh.MeshAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * TranscribeProvider - one leaf of the {@code @McpMeshService} service-view demo.
 *
 * <p>Agent bootstrap only. The capability is published by
 * {@link MediaTranscribeService}, whose {@code transcribe(...)} method carries
 * {@code @MeshTool(capability = "media.transcribe")} — a third, independent
 * slice of the shared {@code media.*} namespace, served by its own agent.
 */
@MeshAgent(
    name = "transcribe-provider",
    version = "1.0.0",
    description = "Publishes media.transcribe into the shared media.* namespace",
    port = 8112
)
@SpringBootApplication
public class TranscribeProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(TranscribeProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting TranscribeProvider Agent...");
        SpringApplication.run(TranscribeProviderApplication.class, args);
    }
}
