package com.example.headerecho;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.spring.tracing.TraceContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.Map;

@MeshAgent(name = "header-echo-java", version = "1.0.0", port = 9050)
@SpringBootApplication
public class HeaderEchoApplication {

    private static final Logger log = LoggerFactory.getLogger(HeaderEchoApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(HeaderEchoApplication.class, args);
    }

    @MeshTool(capability = "echo_headers", description = "Return propagated headers")
    public Map<String, String> echoHeaders() {
        Map<String, String> headers = TraceContext.getPropagatedHeaders();
        log.info("Returning propagated headers: {}", headers);
        return headers;
    }
}
