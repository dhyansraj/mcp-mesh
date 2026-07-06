package com.example.viewproducer;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.MeshAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * uc37 fixture — RFC #1280 PHASE 3 producer sugar: a {@code @Component} class
 * annotated {@code @McpMeshService("svc")} publishes each public declared
 * method as an ordinary mesh tool with a DOT-SEPARATED capability name
 * ({@code svc.alpha}, {@code svc.bravo}) through the normal {@code @MeshTool}
 * machinery.
 *
 * <p>This agent is ALSO the first thing to ever carry a dotted capability name
 * through a real cluster registration — tc08 asserts the registry's widened
 * capability-name validator accepts it end-to-end (Go
 * {@code src/core/registry/validation.go}: dot-separated segments, each
 * letter-led alnum/_/-). Payloads are self-identifying (agent + capability)
 * so the consumer's {@code view_dotted} report proves routing, not just
 * registration.
 *
 * <p>Keep the producer class MINIMAL: every public declared method becomes a
 * published tool — do not add public helpers.
 */
@MeshAgent(
    name = "java-view-producer",
    version = "1.0.0",
    description = "uc37 producer of svc.* dotted capabilities via @McpMeshService(\"svc\") sugar",
    port = 9202
)
@SpringBootApplication
public class JavaViewProducerApplication {

    private static final Logger log = LoggerFactory.getLogger(JavaViewProducerApplication.class);

    public static void main(String[] args) {
        log.info("Starting java-view-producer (uc37 RFC #1280 phase-3 producer sugar)...");
        SpringApplication.run(JavaViewProducerApplication.class, args);
    }

    /**
     * Publishes "svc.alpha" and "svc.bravo" — nothing else. PUBLIC class,
     * matching the phase-3 unit fixture (svprod.ProdFixtures.MediaProducer):
     * the sugar publishes public declared methods, and a public declaring
     * class keeps reflective invocation unambiguous.
     */
    @McpMeshService("svc")
    @Component
    public static class SvcTools {

        public Map<String, Object> alpha() {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("agent", "java-view-producer");
            out.put("cap", "svc.alpha");
            out.put("msg", "hello-from-svc-alpha");
            return out;
        }

        public Map<String, Object> bravo() {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("agent", "java-view-producer");
            out.put("cap", "svc.bravo");
            out.put("msg", "hello-from-svc-bravo");
            return out;
        }
    }
}
