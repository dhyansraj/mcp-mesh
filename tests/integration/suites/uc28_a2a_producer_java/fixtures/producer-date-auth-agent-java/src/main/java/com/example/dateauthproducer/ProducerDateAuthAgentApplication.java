package com.example.dateauthproducer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.spring.web.MeshA2A;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.Map;

/**
 * uc28_a2a_producer_java fixture (bearer auth) — Java A2A producer
 * with {@code @MeshA2A(auth="bearer")} so the JSON-RPC entry rejects
 * requests without an {@code Authorization: Bearer <token>} header.
 * Listens on port 9092 to coexist with the non-auth fixtures.
 *
 * <p>The handler is dependency-free so the test doesn't need a
 * sibling provider — solo agent + registry are enough.
 */
@MeshAgent(
    name = "date-auth-agent",
    version = "1.0.0",
    description = "uc28 Java A2A producer fixture (bearer auth).",
    port = 9092
)
@SpringBootApplication
public class ProducerDateAuthAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(ProducerDateAuthAgentApplication.class, args);
    }

    @Component
    static class AuthSkill {

        @MeshA2A(
            path = "/agents/date",
            skillId = "get-date",
            skillName = "Get Date (auth)",
            description = "Get current date via bearer-protected A2A surface",
            tags = {"system", "date", "auth"},
            auth = "bearer"
        )
        public Map<String, Object> getDate(Map<String, Object> message) {
            return Map.of("date", Instant.now().toString());
        }
    }
}
