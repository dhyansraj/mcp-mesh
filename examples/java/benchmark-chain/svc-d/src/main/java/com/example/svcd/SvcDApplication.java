package com.example.svcd;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.Map;

@MeshAgent(
    name = "svc-d",
    version = "1.0.0",
    description = "Chain service D - receives from C, calls E",
    port = 8080
)
@SpringBootApplication
public class SvcDApplication {

    private static final Logger log = LoggerFactory.getLogger(SvcDApplication.class);

    public static void main(String[] args) {
        log.info("Starting SvcD Agent...");
        SpringApplication.run(SvcDApplication.class, args);
    }

    @MeshTool(
        capability = "process_d",
        description = "Intermediate chain service D",
        tags = {"benchmark", "chain", "intermediate"},
        dependencies = @Selector(capability = "generate_response")
    )
    public String processD(
        @Param(value = "mode", description = "baseline or payload") String mode,
        @Param(value = "payload", description = "payload data") String payload,
        @Param(value = "payload_size", description = "requested size") String payloadSize,
        McpMeshTool<String> generateResponse
    ) {
        if (!generateResponse.isAvailable()) {
            return "degraded: generate_response dependency not available";
        }
        log.info("process_d called with mode={}, payload_size={}", mode, payloadSize);
        return generateResponse.call(Map.of("mode", mode, "payload", payload, "payload_size", payloadSize));
    }
}
