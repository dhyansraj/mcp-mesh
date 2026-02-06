package com.example.deprecatedprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(
    name = "java-deprecated-provider",
    version = "1.0.0",
    description = "Deprecated data provider with api,deprecated tags",
    port = 9042
)
@SpringBootApplication
public class DeprecatedProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(DeprecatedProviderApplication.class, args);
    }

    @MeshTool(
        capability = "data_service",
        description = "Get data from deprecated provider",
        tags = {"api", "deprecated"}
    )
    public DataResponse getData(
        @Param(value = "query", description = "Data query") String query
    ) {
        return new DataResponse("JAVA_DEPRECATED: " + query);
    }

    public record DataResponse(String result) {}
}
