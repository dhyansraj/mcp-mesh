package com.example.viewproducer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * uc37 fixture — publishes DOT-SEPARATED capability names ({@code svc.alpha},
 * {@code svc.bravo}) as ordinary mesh tools. Each capability name is declared
 * EXPLICITLY on {@code @MeshTool(capability = "svc.alpha")} — the producer-side
 * {@code @McpMeshService("prefix")} sugar was removed (#1320), so the dotted
 * contract is owned by the annotation, not derived from the Java method name.
 *
 * <p>This agent is the consumer-view tests' unchanged provider (tc10/tc11 bind
 * {@code svc.alpha}/{@code svc.bravo}), and also the first thing to carry a
 * dotted capability name through a real cluster registration — the registry's
 * capability-name validator accepts it end-to-end (Go
 * {@code src/core/registry/validation.go}: dot-separated segments, each
 * letter-led alnum/_/-). Payloads are self-identifying (agent + capability) so
 * the consumer's report proves routing, not just registration.
 */
@MeshAgent(
    name = "java-view-producer",
    version = "1.0.0",
    description = "uc37 producer of svc.* dotted capabilities via explicit @MeshTool",
    port = 9202
)
@SpringBootApplication
public class JavaViewProducerApplication {

    private static final Logger log = LoggerFactory.getLogger(JavaViewProducerApplication.class);

    public static void main(String[] args) {
        log.info("Starting java-view-producer (uc37 dotted-capability producer)...");
        SpringApplication.run(JavaViewProducerApplication.class, args);
    }

    /** Publishes "svc.alpha" and "svc.bravo" as explicit dotted-capability tools. */
    @Component
    public static class SvcTools {

        @MeshTool(capability = "svc.alpha")
        public Map<String, Object> alpha() {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("agent", "java-view-producer");
            out.put("cap", "svc.alpha");
            out.put("msg", "hello-from-svc-alpha");
            return out;
        }

        @MeshTool(capability = "svc.bravo")
        public Map<String, Object> bravo() {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("agent", "java-view-producer");
            out.put("cap", "svc.bravo");
            out.put("msg", "hello-from-svc-bravo");
            return out;
        }
    }
}
