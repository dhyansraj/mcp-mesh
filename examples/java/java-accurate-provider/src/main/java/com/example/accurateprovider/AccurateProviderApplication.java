package com.example.accurateprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(
    name = "java-accurate-provider",
    version = "1.0.0",
    description = "Accurate data provider with api,accurate tags",
    port = 9041
)
@SpringBootApplication
public class AccurateProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(AccurateProviderApplication.class, args);
    }

    @MeshTool(
        capability = "data_service",
        description = "Get data accurately (accurate provider)",
        tags = {"api", "accurate"}
    )
    public DataResponse getData(
        @Param(value = "query", description = "Data query") String query
    ) {
        return new DataResponse("JAVA_ACCURATE: " + query);
    }

    public record DataResponse(String result) {}
}
