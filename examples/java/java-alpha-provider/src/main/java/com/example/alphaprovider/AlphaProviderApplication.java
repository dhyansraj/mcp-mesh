package com.example.alphaprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(
    name = "java-alpha-provider",
    version = "1.0.0",
    description = "Student lookup provider",
    port = 9066
)
@SpringBootApplication
public class AlphaProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(AlphaProviderApplication.class, args);
    }

    @MeshTool(
        capability = "student_lookup",
        description = "Look up student information",
        tags = {"student"}
    )
    public StudentResponse getStudent(
        @Param(value = "id", description = "Student ID") String id
    ) {
        return new StudentResponse("Alice", "A", "alpha-provider");
    }

    public record StudentResponse(String name, String grade, String source) {}
}
