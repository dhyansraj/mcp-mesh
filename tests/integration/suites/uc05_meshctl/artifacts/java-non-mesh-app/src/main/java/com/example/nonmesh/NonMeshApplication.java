package com.example.nonmesh;

import io.mcpmesh.spring.MeshAutoConfiguration;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * A regular Spring Boot app with mcp-mesh-spring-boot-starter on the classpath
 * but WITHOUT @MeshAgent. Used to verify that MCP_MESH_HTTP_PORT does not
 * override server.port for non-mesh applications.
 */
@SpringBootApplication(exclude = {MeshAutoConfiguration.class})
@RestController
public class NonMeshApplication {

    public static void main(String[] args) {
        SpringApplication.run(NonMeshApplication.class, args);
    }

    @GetMapping("/ping")
    public String ping() {
        return "pong";
    }
}
