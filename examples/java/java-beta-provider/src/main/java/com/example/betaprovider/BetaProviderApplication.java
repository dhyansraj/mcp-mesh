package com.example.betaprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.List;
import java.util.Map;

@MeshAgent(
    name = "java-beta-provider",
    version = "1.0.0",
    description = "Schedule lookup provider",
    port = 9067
)
@SpringBootApplication
public class BetaProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(BetaProviderApplication.class, args);
    }

    @MeshTool(
        capability = "schedule_lookup",
        description = "Look up class schedule",
        tags = {"schedule"}
    )
    public List<Map<String, String>> getSchedule(
        @Param(value = "id", description = "Student ID") String id
    ) {
        return List.of(
            Map.of("day", "Monday", "class", "Math"),
            Map.of("day", "Wednesday", "class", "Art")
        );
    }
}
