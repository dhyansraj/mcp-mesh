package com.example.headerrelay;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(name = "header-relay-java", version = "1.0.0", port = 9051)
@SpringBootApplication
public class HeaderRelayApplication {

    private static final Logger log = LoggerFactory.getLogger(HeaderRelayApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(HeaderRelayApplication.class, args);
    }

    @MeshTool(
        capability = "relay_headers",
        description = "Call echo_headers and return result",
        dependencies = @Selector(capability = "echo_headers")
    )
    public String relayHeaders(McpMeshTool<String> echoSvc) {
        if (echoSvc == null || !echoSvc.isAvailable()) {
            log.warn("echo_headers dependency not available");
            return "{\"error\": \"echo_headers not available\"}";
        }
        log.info("Calling echo_headers via mesh dependency");
        return echoSvc.call();
    }
}
