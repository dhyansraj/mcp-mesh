package io.mcpmesh.example.schema.consumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.SchemaMode;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.Map;

/**
 * Schema-aware consumer (Java).
 *
 * <p>Depends on capability {@code employee_lookup} with subset-mode schema check
 * ({@code expectedType=Employee.class}). Producer-good wires; producer-bad
 * (Hardware) is evicted by the schema stage. Cross-runtime: also wires to
 * Python/TS producer-good because they declare the same canonical Employee
 * hash.
 */
@MeshAgent(
    name = "consumer-java",
    version = "1.0.0",
    description = "Schema-aware consumer (Java) for issue #547 cross-runtime tests",
    port = 9122
)
@SpringBootApplication
public class ConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(ConsumerApplication.class, args);
    }

    @MeshTool(
        capability = "schema_aware_lookup_java",
        description = "Schema-aware consumer (subset mode) — Java",
        dependencies = @Selector(
            capability = "employee_lookup",
            expectedType = Employee.class,
            schemaMode = SchemaMode.SUBSET
        )
    )
    public String lookupWithSchema(
        @Param(value = "emp_id", description = "Employee ID") String empId,
        McpMeshTool<Employee> lookup
    ) {
        if (lookup == null || !lookup.isAvailable()) {
            return "no compatible producer for " + empId;
        }
        Employee result = lookup.call(Map.of("employee_id", empId));
        return "got: " + result;
    }
}
