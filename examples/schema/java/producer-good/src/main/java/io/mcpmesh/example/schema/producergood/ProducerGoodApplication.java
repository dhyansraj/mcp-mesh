package io.mcpmesh.example.schema.producergood;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Schema-test producer (Java) — Employee shape that matches the consumer.
 *
 * <p>Capability: {@code employee_lookup}, tags={@code ["good"]}.
 * Outputs Employee {name, dept, salary} — the canonical cross-runtime shape.
 */
@MeshAgent(
    name = "producer-good-java",
    version = "1.0.0",
    description = "Schema-test producer (Java) with matching Employee shape",
    port = 9120
)
@SpringBootApplication
public class ProducerGoodApplication {

    public static void main(String[] args) {
        SpringApplication.run(ProducerGoodApplication.class, args);
    }

    @MeshTool(
        capability = "employee_lookup",
        description = "Return an Employee record (matching shape)",
        tags = {"good"},
        outputType = Employee.class
    )
    public Employee getEmployee(
        @Param(value = "employee_id", description = "Employee ID") String employeeId
    ) {
        return new Employee("Alice", "Engineering", 120000.0);
    }
}
