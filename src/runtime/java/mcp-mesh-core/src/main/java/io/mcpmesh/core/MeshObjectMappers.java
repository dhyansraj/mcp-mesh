package io.mcpmesh.core;

import tools.jackson.databind.ObjectMapper;

/**
 * Central factory for ObjectMapper instances used across the MCP Mesh SDK.
 *
 * <p>Jackson 3 has JavaTimeModule, Jdk8Module, and ParameterNamesModule
 * built into jackson-databind — no separate module registration is needed.
 * This factory exists to provide a single place for any future configuration
 * that applies to all ObjectMapper instances in the SDK.
 */
public final class MeshObjectMappers {

    private MeshObjectMappers() {}

    /**
     * Create a new ObjectMapper with MCP Mesh defaults.
     *
     * <p>Use this for static fields and non-Spring contexts. In Spring-managed
     * beans, prefer injecting Spring's ObjectMapper for consistency with
     * application-wide configuration.
     *
     * @return a configured ObjectMapper instance
     */
    public static ObjectMapper create() {
        return new ObjectMapper();
    }
}
