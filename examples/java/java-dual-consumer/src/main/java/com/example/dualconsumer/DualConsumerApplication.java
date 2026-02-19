package com.example.dualconsumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Dual-dependency consumer for dep_index alignment test (issue #572).
 *
 * Declares two dependencies in specific order:
 *   dep_index=0: student_lookup (from alpha provider)
 *   dep_index=1: schedule_lookup (from beta provider)
 *
 * If dep_index alignment is broken, when only beta is running:
 *   - dep 0 would incorrectly appear available (beta wired to wrong index)
 *   - dep 1 would incorrectly appear unavailable
 */
@MeshAgent(
    name = "java-dual-consumer",
    version = "1.0.0",
    description = "Consumer with two dependencies for dep_index alignment test",
    port = 9068
)
@SpringBootApplication
public class DualConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(DualConsumerApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(DualConsumerApplication.class, args);
    }

    @MeshTool(
        capability = "enrollment_check",
        description = "Check enrollment using student and schedule data",
        tags = {"consumer", "dual-dep"},
        dependencies = {
            @Selector(capability = "student_lookup"),
            @Selector(capability = "schedule_lookup"),
        }
    )
    public Map<String, Object> checkEnrollment(
        @Param(value = "id", description = "Student ID") String id,
        McpMeshTool<Map<String, Object>> studentService,
        McpMeshTool<Object> scheduleService
    ) {
        Map<String, Object> result = new LinkedHashMap<>();

        boolean studentAvailable = studentService != null && studentService.isAvailable();
        boolean scheduleAvailable = scheduleService != null && scheduleService.isAvailable();

        result.put("student_available", studentAvailable);
        result.put("schedule_available", scheduleAvailable);
        result.put("student", null);
        result.put("schedule", null);

        if (studentAvailable) {
            try {
                log.info("Calling student_lookup at: {}", studentService.getEndpoint());
                result.put("student", studentService.call(Map.of("id", id)));
            } catch (Exception e) {
                log.warn("Failed to call student_lookup: {}", e.getMessage());
                result.put("student_error", e.getMessage());
            }
        }

        if (scheduleAvailable) {
            try {
                log.info("Calling schedule_lookup at: {}", scheduleService.getEndpoint());
                result.put("schedule", scheduleService.call(Map.of("id", id)));
            } catch (Exception e) {
                log.warn("Failed to call schedule_lookup: {}", e.getMessage());
                result.put("schedule_error", e.getMessage());
            }
        }

        return result;
    }
}
