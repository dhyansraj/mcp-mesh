package com.example.provider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(
    name = "typed-provider",
    version = "1.0.0",
    description = "Provider that executes tasks from typed arguments",
    port = 8080
)
@SpringBootApplication
public class ProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(ProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting Typed Provider Agent...");
        SpringApplication.run(ProviderApplication.class, args);
    }

    @MeshTool(
        capability = "execute_task",
        description = "Execute a task from typed arguments"
    )
    public String executeTask(
        @Param(value = "task", description = "task type") String task,
        @Param(value = "name", description = "name argument") String name,
        @Param(value = "count", description = "repeat count") int count
    ) {
        log.info("execute_task called with task={}, name={}, count={}", task, name, count);

        if ("greet".equals(task)) {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < count; i++) {
                sb.append("Hello ").append(name).append("!");
            }
            return sb.toString();
        }
        return "unknown task: " + task;
    }
}
