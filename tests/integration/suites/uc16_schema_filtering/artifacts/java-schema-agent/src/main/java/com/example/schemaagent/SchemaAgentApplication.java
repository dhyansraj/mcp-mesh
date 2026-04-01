package com.example.schemaagent;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import io.mcpmesh.Param;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(name = "java-schema-agent", version = "1.0.0", port = 9061)
@SpringBootApplication
public class SchemaAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(SchemaAgentApplication.class, args);
    }

    @MeshTool(capability = "schema.greet", description = "Simple greeting")
    public String greet(@Param(value = "name", description = "Name to greet") String name) {
        return "Hello " + name;
    }

    @MeshTool(
        capability = "schema.with_dep",
        description = "Tool with dependency",
        dependencies = @Selector(capability = "some_service")
    )
    public String withDep(
        @Param(value = "query", description = "Query string") String query,
        McpMeshTool<String> svc
    ) {
        return "Result for " + query;
    }
}
