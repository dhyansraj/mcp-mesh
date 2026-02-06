package com.example.fastprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(
    name = "java-fast-provider",
    version = "1.0.0",
    description = "Fast data provider with api,fast tags",
    port = 9040
)
@SpringBootApplication
public class FastProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(FastProviderApplication.class, args);
    }

    @MeshTool(
        capability = "data_service",
        description = "Get data quickly (fast provider)",
        tags = {"api", "fast"}
    )
    public DataResponse getData(
        @Param(value = "query", description = "Data query") String query
    ) {
        return new DataResponse("JAVA_FAST: " + query);
    }

    public record DataResponse(String result) {}
}
