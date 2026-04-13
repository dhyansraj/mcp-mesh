package com.example.slow;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(
    name = "java-slow-agent",
    version = "1.0.0",
    description = "Slow agent for timeout chain test (last hop)",
    port = 8080
)
@SpringBootApplication
public class SlowAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(SlowAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Java Slow Agent...");
        SpringApplication.run(SlowAgentApplication.class, args);
    }

    @MeshTool(
        capability = "slow_java",
        description = "Sleeps 70s then returns completion marker"
    )
    public String slowChainJava(
        @Param(value = "message", description = "chain message") String message
    ) {
        log.info("slow_java called with message={}", message);
        try {
            Thread.sleep(70000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return "{\"chain\":\"java (interrupted)\",\"data\":\"interrupted\"}";
        }
        return "{\"chain\":\"java\",\"data\":\"timeout_chain_complete\"}";
    }
}
