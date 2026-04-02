package com.example.caller;

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
    name = "typed-caller",
    version = "1.0.0",
    description = "Caller that sends typed arguments to provider",
    port = 8080
)
@SpringBootApplication
public class CallerApplication {

    private static final Logger log = LoggerFactory.getLogger(CallerApplication.class);

    public static void main(String[] args) {
        log.info("Starting Typed Caller Agent...");
        SpringApplication.run(CallerApplication.class, args);
    }

    @MeshTool(
        capability = "run_task",
        description = "Send typed arguments to provider",
        dependencies = @Selector(capability = "execute_task")
    )
    public String runTask(
        @Param(value = "task", description = "task type") String task,
        @Param(value = "name", description = "name argument") String name,
        @Param(value = "count", description = "repeat count") int count,
        McpMeshTool<String> executeTask
    ) {
        if (!executeTask.isAvailable()) {
            return "degraded: execute_task not available";
        }
        log.info("run_task called with task={}, name={}, count={}", task, name, count);
        return executeTask.call(Map.of("task", task, "name", name, "count", count));
    }
}
