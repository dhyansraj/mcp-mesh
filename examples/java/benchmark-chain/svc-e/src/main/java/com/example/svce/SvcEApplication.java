package com.example.svce;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.Map;

@MeshAgent(
    name = "svc-e",
    version = "1.0.0",
    description = "Terminal service - generates response payload",
    port = 8080
)
@SpringBootApplication
public class SvcEApplication {

    private static final Logger log = LoggerFactory.getLogger(SvcEApplication.class);

    private static final String PATTERN = "abcdefghijklmnopqrstuvwxyz0123456789";
    private static final Map<String, Integer> PAYLOAD_SIZES = Map.of(
        "1kb", 1024,
        "10kb", 10240,
        "100kb", 102400,
        "1mb", 1048576
    );

    public static void main(String[] args) {
        log.info("Starting SvcE Agent...");
        SpringApplication.run(SvcEApplication.class, args);
    }

    @MeshTool(
        capability = "generate_response",
        description = "Terminal service that generates benchmark response",
        tags = {"benchmark", "chain", "terminal"}
    )
    public String generateResponse(
        @Param(value = "mode", description = "baseline or payload") String mode,
        @Param(value = "payload", description = "payload data") String payload,
        @Param(value = "payload_size", description = "requested size") String payloadSize
    ) {
        log.info("generate_response called with mode={}, payload_size={}", mode, payloadSize);

        if ("baseline".equals(mode)) {
            return "Hello World";
        }

        return generatePayload(payloadSize);
    }

    private String generatePayload(String sizeKey) {
        int targetBytes = PAYLOAD_SIZES.getOrDefault(sizeKey, 1024);
        int envelopeOverhead = "{\"data\":\"\"}".length();
        int dataLen = Math.max(targetBytes - envelopeOverhead, 0);
        int repetitions = (dataLen / PATTERN.length()) + 1;
        StringBuilder sb = new StringBuilder(PATTERN.length() * repetitions);
        for (int i = 0; i < repetitions; i++) {
            sb.append(PATTERN);
        }
        String data = sb.substring(0, dataLen);
        return "{\"data\":\"" + data + "\"}";
    }
}
