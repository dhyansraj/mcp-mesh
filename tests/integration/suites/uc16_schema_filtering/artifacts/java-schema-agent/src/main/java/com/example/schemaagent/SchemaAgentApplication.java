package com.example.schemaagent;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import io.mcpmesh.Param;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * java-schema-agent - Test agent for verifying MCP schema filtering.
 *
 * 9 tools covering the parameter matrix (cases 1-9):
 *   t01NoParams:              no params -> empty schema
 *   t02OneParam:              one param -> name visible
 *   t03MultiParams:           multi params -> a, b, c visible
 *   t04WithDefaults:          with defaults -> a, b visible
 *   t05MeshtoolOnly:          McpMeshTool only -> empty schema (svc hidden)
 *   t06NormalThenMeshtool:    normal + McpMeshTool -> query visible, svc hidden
 *   t07MeshtoolThenNormal:    McpMeshTool + normal -> query visible, svc hidden
 *   t08MultiMeshtool:         multi McpMeshTool -> q visible, a/b hidden
 *   t09NormalMeshtoolDefaults: mixed with defaults -> q, n visible, svc hidden
 */
@MeshAgent(name = "java-schema-agent", version = "1.0.0", port = 9061)
@SpringBootApplication
public class SchemaAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(SchemaAgentApplication.class, args);
    }

    // Case 1: No params
    @MeshTool(capability = "schema.t01", description = "No parameters")
    public String t01NoParams() {
        return "ok";
    }

    // Case 2: One param
    @MeshTool(capability = "schema.t02", description = "Single parameter")
    public String t02OneParam(@Param(value = "name", description = "Name") String name) {
        return "Hello " + name;
    }

    // Case 3: Multiple params
    @MeshTool(capability = "schema.t03", description = "Multiple parameters")
    public String t03MultiParams(
        @Param(value = "a", description = "String param") String a,
        @Param(value = "b", description = "Number param") int b,
        @Param(value = "c", description = "Boolean param") boolean c
    ) {
        return a + " " + b + " " + c;
    }

    // Case 4: With defaults (Java uses Optional/nullable for defaults)
    @MeshTool(capability = "schema.t04", description = "Parameters with defaults")
    public String t04WithDefaults(
        @Param(value = "a", description = "Required param") String a,
        @Param(value = "b", description = "Optional param", required = false) Integer b
    ) {
        return a + " " + (b != null ? b : 5);
    }

    // Case 5: McpMeshTool only
    @MeshTool(
        capability = "schema.t05",
        description = "Injectable only",
        dependencies = @Selector(capability = "dep_a")
    )
    public String t05MeshtoolOnly(McpMeshTool<String> svc) {
        return "ok";
    }

    // Case 6: Normal then McpMeshTool
    @MeshTool(
        capability = "schema.t06",
        description = "Normal then injectable",
        dependencies = @Selector(capability = "dep_a")
    )
    public String t06NormalThenMeshtool(
        @Param(value = "query", description = "Query string") String query,
        McpMeshTool<String> svc
    ) {
        return "Result for " + query;
    }

    // Case 7: McpMeshTool then normal (reversed order)
    @MeshTool(
        capability = "schema.t07",
        description = "Injectable then normal",
        dependencies = @Selector(capability = "dep_a")
    )
    public String t07MeshtoolThenNormal(
        McpMeshTool<String> svc,
        @Param(value = "query", description = "Query string") String query
    ) {
        return "Result for " + query;
    }

    // Case 8: Multiple McpMeshTool
    @MeshTool(
        capability = "schema.t08",
        description = "Multiple injectables",
        dependencies = { @Selector(capability = "dep_a"), @Selector(capability = "dep_b") }
    )
    public String t08MultiMeshtool(
        @Param(value = "q", description = "Query") String q,
        McpMeshTool<String> a,
        McpMeshTool<String> b
    ) {
        return "Result for " + q;
    }

    // Case 9: Normal + McpMeshTool + optional param
    @MeshTool(
        capability = "schema.t09",
        description = "Mixed with defaults",
        dependencies = @Selector(capability = "dep_a")
    )
    public String t09NormalMeshtoolDefaults(
        @Param(value = "q", description = "Query") String q,
        @Param(value = "n", description = "Count", required = false) Integer n,
        McpMeshTool<String> svc
    ) {
        return q + " " + (n != null ? n : 5);
    }
}
