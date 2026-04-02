package com.example.svca;

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
    name = "svc-a",
    version = "1.0.0",
    description = "Entry service - receives request, calls svc-b",
    port = 8080
)
@SpringBootApplication
public class SvcAApplication {

    private static final Logger log = LoggerFactory.getLogger(SvcAApplication.class);

    public static void main(String[] args) {
        log.info("Starting SvcA Agent...");
        SpringApplication.run(SvcAApplication.class, args);
    }

    @MeshTool(
        capability = "call_chain",
        description = "Entry point for benchmark chain",
        tags = {"benchmark", "chain", "entry"},
        dependencies = @Selector(capability = "process_b")
    )
    public String callChain(
        @Param(value = "mode", description = "baseline or payload") String mode,
        @Param(value = "payload", description = "payload data") String payload,
        @Param(value = "payload_size", description = "requested size") String payloadSize,
        McpMeshTool<String> processB
    ) {
        if (!processB.isAvailable()) {
            return "degraded: process_b dependency not available";
        }
        log.info("call_chain called with mode={}, payload_size={}", mode, payloadSize);
        return processB.call(Map.of("mode", mode, "payload", payload, "payload_size", payloadSize));
    }
}
