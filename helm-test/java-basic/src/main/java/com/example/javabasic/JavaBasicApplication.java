package com.example.javabasic;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * JavaBasic - MCP Mesh Agent
 *
 * A MCP Mesh agent generated using meshctl scaffold.
 */
@MeshAgent(
    name = "java-basic",
    version = "1.0.0",
    description = "MCP Mesh agent",
    port = 8080
)
@SpringBootApplication
public class JavaBasicApplication {

    private static final Logger log = LoggerFactory.getLogger(JavaBasicApplication.class);

    public static void main(String[] args) {
        log.info("Starting JavaBasic Agent...");
        SpringApplication.run(JavaBasicApplication.class, args);
    }

    /**
     * A sample tool.
     *
     * @param input Input parameter
     * @return Result string
     */
    @MeshTool(
        capability = "hello",
        description = "A sample tool",
        tags = {"tools"}
    )
    public String hello(
        @Param(value = "input", description = "Input parameter") String input
    ) {
        log.info("hello called with: {}", input);
        return "Hello from java-basic: " + input;
    }

    // ===== MULTI-PARAMETER EXAMPLE (uncomment and adapt) =====
    //
    // @MeshTool methods can accept multiple typed parameters.
    // The mesh SDK generates JSON Schema from the @Param annotations.
    //
    // @MeshTool(
    //     capability = "process",
    //     description = "Process data with options",
    //     tags = {"tools"}
    // )
    // public String process(
    //     @Param(value = "text", description = "Text to process") String text,
    //     @Param(value = "count", description = "Repeat count") int count,
    //     @Param(value = "threshold", description = "Score threshold") double threshold,
    //     @Param(value = "verbose", description = "Verbose output", required = false) boolean verbose
    // ) {
    //     return "Processed: " + text;
    // }

    // ===== DEPENDENCY INJECTION EXAMPLE (uncomment and adapt) =====
    //
    // Declare dependencies to call tools on other agents in the mesh.
    // The mesh runtime injects McpMeshTool instances for each dependency.
    //
    // @MeshTool(
    //     capability = "orchestrate",
    //     description = "Calls another agent's tool",
    //     tags = {"tools"},
    //     dependencies = @Selector(capability = "calculator")
    // )
    // public String orchestrate(
    //     @Param(value = "expression", description = "Math expression") String expression,
    //     McpMeshTool<String> calculator                // injected by mesh
    // ) {
    //     if (!calculator.isAvailable()) {
    //         return "calculator dependency not available";
    //     }
    //     String result = calculator.call(java.util.Map.of("expression", expression));
    //     return "Calculator says: " + result;
    // }

    // ===== RETURN TYPE EXAMPLES =====
    //
    // Tools can return complex types. The SDK serializes them to JSON.
    //
    // public record ProcessResult(String output, int tokenCount) {}
    //
    // @MeshTool(capability = "analyze", description = "Analyze text", tags = {"tools"})
    // public ProcessResult analyze(@Param(value = "text", description = "Text") String text) {
    //     return new ProcessResult("analyzed: " + text, text.length());
    // }
}
