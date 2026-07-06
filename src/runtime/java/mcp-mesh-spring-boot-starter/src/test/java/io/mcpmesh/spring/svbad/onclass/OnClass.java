package io.mcpmesh.spring.svbad.onclass;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;

/**
 * Boot-fail: a producer class annotated {@code @McpMeshService} with a BLANK
 * prefix (RFC #1280 phase 3 — a producer class requires a name prefix).
 */
public final class OnClass {

    private OnClass() {
    }

    @McpMeshService // blank value → boot-fail
    public static class BlankPrefixProducer {
        public String greet(@Param("name") String name) {
            return "hi " + name;
        }
    }
}
