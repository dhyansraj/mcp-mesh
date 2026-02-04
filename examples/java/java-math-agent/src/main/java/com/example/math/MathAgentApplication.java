package com.example.math;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.Map;

/**
 * Java Math Agent - provides add and multiply capabilities.
 *
 * This agent is used for distributed tracing tests, providing basic
 * math operations that can be called by other agents.
 */
@SpringBootApplication
@MeshAgent(
    name = "java-math-agent",
    version = "1.0.0",
    description = "Java Math Agent providing add and multiply capabilities",
    port = 9010
)
public class MathAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(MathAgentApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(MathAgentApplication.class, args);
    }

    /**
     * Add two numbers together.
     */
    @MeshTool(
        capability = "add",
        description = "Add two numbers together",
        tags = {"tools", "data", "math", "add"}
    )
    public Map<String, Object> add(
        @Param(value = "a", description = "First number") double a,
        @Param(value = "b", description = "Second number") double b
    ) {
        double result = a + b;
        log.info("[add] Adding {} + {} = {}", a, b, result);
        return Map.of(
            "a", a,
            "b", b,
            "result", result
        );
    }

    /**
     * Multiply two numbers together.
     */
    @MeshTool(
        capability = "multiply",
        description = "Multiply two numbers together",
        tags = {"tools", "data", "math", "multiply"}
    )
    public Map<String, Object> multiply(
        @Param(value = "a", description = "First number") double a,
        @Param(value = "b", description = "Second number") double b
    ) {
        double result = a * b;
        log.info("[multiply] Multiplying {} * {} = {}", a, b, result);
        return Map.of(
            "a", a,
            "b", b,
            "result", result
        );
    }
}
