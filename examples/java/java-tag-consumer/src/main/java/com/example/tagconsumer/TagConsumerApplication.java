package com.example.tagconsumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(
    name = "java-tag-consumer",
    version = "1.0.0",
    description = "Consumer agent with various tag selectors",
    port = 9045
)
@SpringBootApplication
public class TagConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(TagConsumerApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(TagConsumerApplication.class, args);
    }

    /**
     * Fetch data requiring "api" tag.
     */
    @MeshTool(
        capability = "fetch_required",
        description = "Fetch data requiring api tag",
        tags = {"consumer"},
        dependencies = @Selector(capability = "data_service", tags = {"api"})
    )
    public FetchResponse fetchRequired(
        @Param(value = "query", description = "Data query") String query,
        McpMeshTool<DataResponse> dataService
    ) {
        log.info("fetchRequired: {}", query);
        DataResponse data = dataService.call("query", query);
        return new FetchResponse("Required: " + data.result());
    }

    /**
     * Fetch data preferring "fast" tag.
     */
    @MeshTool(
        capability = "fetch_prefer_fast",
        description = "Fetch data preferring fast provider",
        tags = {"consumer"},
        dependencies = @Selector(capability = "data_service", tags = {"+fast"})
    )
    public FetchResponse fetchPreferFast(
        @Param(value = "query", description = "Data query") String query,
        McpMeshTool<DataResponse> dataService
    ) {
        log.info("fetchPreferFast: {}", query);
        DataResponse data = dataService.call("query", query);
        return new FetchResponse("PreferFast: " + data.result());
    }

    /**
     * Fetch data excluding "deprecated" tag.
     */
    @MeshTool(
        capability = "fetch_exclude_deprecated",
        description = "Fetch data excluding deprecated provider",
        tags = {"consumer"},
        dependencies = @Selector(capability = "data_service", tags = {"-deprecated"})
    )
    public FetchResponse fetchExcludeDeprecated(
        @Param(value = "query", description = "Data query") String query,
        McpMeshTool<DataResponse> dataService
    ) {
        log.info("fetchExcludeDeprecated: {}", query);
        DataResponse data = dataService.call("query", query);
        return new FetchResponse("ExcludeDeprecated: " + data.result());
    }

    /**
     * Fetch data with combined filters: require api, prefer accurate, exclude deprecated.
     */
    @MeshTool(
        capability = "fetch_combined",
        description = "Fetch data with combined filters",
        tags = {"consumer"},
        dependencies = @Selector(capability = "data_service", tags = {"api", "+accurate", "-deprecated"})
    )
    public FetchResponse fetchCombined(
        @Param(value = "query", description = "Data query") String query,
        McpMeshTool<DataResponse> dataService
    ) {
        log.info("fetchCombined: {}", query);
        DataResponse data = dataService.call("query", query);
        return new FetchResponse("Combined: " + data.result());
    }

    /**
     * Response from data service providers.
     * Matches the JSON structure returned by the provider agents.
     */
    public record DataResponse(String result) {}

    /**
     * Response from fetch operations.
     */
    public record FetchResponse(String result) {}
}
