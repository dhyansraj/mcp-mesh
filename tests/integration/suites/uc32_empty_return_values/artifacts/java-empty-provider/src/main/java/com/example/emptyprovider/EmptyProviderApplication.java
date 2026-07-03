package com.example.emptyprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.List;
import java.util.Map;

/**
 * Provider whose tool returns the empty/null boundary values from issue #1250.
 *
 * <p>The Java provider is the cross-check anchor: it always emitted a real
 * {@code "[]"} text block for empty lists, so every consumer parsed it
 * correctly. This agent lets the suite pin that behavior (Java provider x
 * Python consumer) alongside the previously-broken Python provider column.
 */
@SpringBootApplication
@MeshAgent(
    name = "java-empty-provider",
    version = "1.0.0",
    description = "Provider of empty/null boundary return values (issue #1250)",
    port = 9041
)
public class EmptyProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(EmptyProviderApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(EmptyProviderApplication.class, args);
    }

    /**
     * Return the boundary value for the given kind.
     *
     * @param kind One of: empty_list, empty_dict, empty_string, null_value, nonempty_list
     * @return [], {}, "", null or [1, 2, 3]
     */
    @MeshTool(
        capability = "empty_value_source",
        description = "Return the boundary value for the given kind",
        tags = {"empty", "roundtrip", "java"}
    )
    public Object getValue(
        @Param(value = "kind",
               description = "One of: empty_list, empty_dict, empty_string, null_value, nonempty_list")
        String kind
    ) {
        log.info("get_value called with kind={}", kind);
        return switch (kind) {
            case "empty_list" -> List.of();
            case "empty_dict" -> Map.of();
            case "empty_string" -> "";
            case "null_value" -> null;
            case "nonempty_list" -> List.of(1, 2, 3);
            default -> throw new IllegalArgumentException("unknown kind: " + kind);
        };
    }
}
