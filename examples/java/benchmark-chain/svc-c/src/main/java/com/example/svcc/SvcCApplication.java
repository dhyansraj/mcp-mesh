package com.example.svcc;

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
    name = "svc-c",
    version = "1.0.0",
    description = "Chain service C - receives from B, calls D",
    port = 8080
)
@SpringBootApplication
public class SvcCApplication {

    private static final Logger log = LoggerFactory.getLogger(SvcCApplication.class);

    public static void main(String[] args) {
        log.info("Starting SvcC Agent...");
        SpringApplication.run(SvcCApplication.class, args);
    }

    @MeshTool(
        capability = "process_c",
        description = "Intermediate chain service C",
        tags = {"benchmark", "chain", "intermediate"},
        dependencies = @Selector(capability = "process_d")
    )
    public String processC(
        @Param(value = "mode", description = "baseline or payload") String mode,
        @Param(value = "payload", description = "payload data") String payload,
        @Param(value = "payload_size", description = "requested size") String payloadSize,
        McpMeshTool<String> processD
    ) {
        if (!processD.isAvailable()) {
            return "degraded: process_d dependency not available";
        }
        log.info("process_c called with mode={}, payload_size={}", mode, payloadSize);
        return processD.call(Map.of("mode", mode, "payload", payload, "payload_size", payloadSize));
    }
}
