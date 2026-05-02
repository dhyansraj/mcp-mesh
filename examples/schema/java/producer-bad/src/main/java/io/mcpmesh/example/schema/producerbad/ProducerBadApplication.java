package io.mcpmesh.example.schema.producerbad;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Rogue schema-test producer (Java) — same capability, different shape.
 *
 * <p>Capability: {@code employee_lookup}, tags={@code ["bad"]}.
 * Outputs Hardware {sku, model, price} — schema-aware consumer should evict.
 */
@MeshAgent(
    name = "producer-bad-java",
    version = "1.0.0",
    description = "Schema-test rogue producer (Java) with mismatched Hardware shape",
    port = 9121
)
@SpringBootApplication
public class ProducerBadApplication {

    public static void main(String[] args) {
        SpringApplication.run(ProducerBadApplication.class, args);
    }

    @MeshTool(
        capability = "employee_lookup",
        description = "Returns Hardware (rogue, mis-registered as employee_lookup)",
        tags = {"bad"},
        outputType = Hardware.class
    )
    public Hardware getHardware(
        @Param(value = "item_id", description = "Item ID") String itemId
    ) {
        return new Hardware("H123", "X1 Carbon", 1500.0);
    }
}
