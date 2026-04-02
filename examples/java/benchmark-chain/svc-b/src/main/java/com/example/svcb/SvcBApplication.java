package com.example.svcb;

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
    name = "svc-b",
    version = "1.0.0",
    description = "Chain service B - receives from A, calls C",
    port = 8080
)
@SpringBootApplication
public class SvcBApplication {

    private static final Logger log = LoggerFactory.getLogger(SvcBApplication.class);

    public static void main(String[] args) {
        log.info("Starting SvcB Agent...");
        SpringApplication.run(SvcBApplication.class, args);
    }

    @MeshTool(
        capability = "process_b",
        description = "Intermediate chain service B",
        tags = {"benchmark", "chain", "intermediate"},
        dependencies = @Selector(capability = "process_c")
    )
    public String processB(
        @Param(value = "mode", description = "baseline or payload") String mode,
        @Param(value = "payload", description = "payload data") String payload,
        @Param(value = "payload_size", description = "requested size") String payloadSize,
        McpMeshTool<String> processC
    ) {
        if (!processC.isAvailable()) {
            return "degraded: process_c dependency not available";
        }
        log.info("process_b called with mode={}, payload_size={}", mode, payloadSize);
        return processC.call(Map.of("mode", mode, "payload", payload, "payload_size", payloadSize));
    }
}
