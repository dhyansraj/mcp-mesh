package com.example.dataprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.MediaParam;
import io.mcpmesh.spring.media.MeshMedia;
import io.mcpmesh.spring.media.MediaStore;
import io.modelcontextprotocol.spec.McpSchema.ResourceLink;
import io.mcpmesh.Selector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * DataProvider - MCP Mesh Agent
 *
 * A MCP Mesh agent generated using meshctl scaffold.
 */
@MeshAgent(
    name = "data-provider",
    version = "1.0.0",
    description = "MCP Mesh agent",
    port = 8090
)
@SpringBootApplication
public class DataProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(DataProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting DataProvider Agent...");
        SpringApplication.run(DataProviderApplication.class, args);
    }

    /**
     * Provide source data that the report consumer depends on.
     *
     * @return A row of source data.
     */
    @MeshTool(
        capability = "data_service",
        description = "Returns a row of source data for reports",
        tags = {"data"}
    )
    public java.util.Map<String, Object> dataService() {
        return java.util.Map.of("revenue", 1250, "currency", "USD", "region", "emea");
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

    // ===== MULTIMODAL EXAMPLE (uncomment and adapt) =====
    //
    // Return media (images, PDFs, files) from tools using MeshMedia.
    // LLMs automatically resolve resource_link objects to native image blocks.
    //
    // @MeshTool(capability = "chart_gen", description = "Generate a chart", tags = {"tools"})
    // public ResourceLink generateChart(
    //     @Param(value = "query", description = "Chart query") String query,
    //     MediaStore mediaStore
    // ) {
    //     byte[] png = renderChart(query);
    //     return MeshMedia.mediaResult(png, "chart.png", "image/png", mediaStore);
    // }
    //
    // Accept media URIs with @MediaParam:
    //
    // @MeshTool(capability = "image_analyzer", description = "Analyze an image", tags = {"tools"})
    // public String analyzeImage(
    //     @Param(value = "question", description = "Question about the image") String question,
    //     @MediaParam("image/*") @Param(value = "image", description = "Image URI") String imageUri
    // ) {
    //     return "Received image: " + imageUri;
    // }
}
