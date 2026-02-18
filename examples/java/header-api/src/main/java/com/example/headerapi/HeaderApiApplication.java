package com.example.headerapi;

import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshInject;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@SpringBootApplication
public class HeaderApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(HeaderApiApplication.class, args);
    }
}

@RestController
@RequestMapping("/api")
class HeaderApiController {

    @GetMapping("/echo-headers")
    @MeshRoute(dependencies = @MeshDependency(capability = "echo_headers"))
    public ResponseEntity<Map<String, Object>> echoHeaders(
            @MeshInject("echo_headers") McpMeshTool<Map<String, String>> echoHeadersTool) {

        if (echoHeadersTool == null || !echoHeadersTool.isAvailable()) {
            return ResponseEntity.status(503)
                    .body(Map.of("error", "echo_headers capability unavailable"));
        }

        Map<String, String> headers = echoHeadersTool.call(Map.of());

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-route");
        response.put("headers", headers);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        return ResponseEntity.ok(Map.of("status", "healthy"));
    }
}
