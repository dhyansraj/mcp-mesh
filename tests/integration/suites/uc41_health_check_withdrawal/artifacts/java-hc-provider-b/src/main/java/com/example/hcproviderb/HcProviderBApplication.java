package com.example.hcproviderb;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.Map;

/**
 * java-hc-provider-b — the survivor (issue #1480).
 *
 * <p>Second provider of {@code hc_probe_java}. Deliberately has NO
 * {@code @MeshHealthCheck}: it is the control. It must keep heartbeating
 * throughout, so a run where BOTH providers go unhealthy (dead registry,
 * stalled sweep, container-wide stall) is distinguishable from a genuine
 * withdrawal of A.
 *
 * <p>Loses the resolver tiebreak to A while A is healthy — equal tag score,
 * equal version, then agent ID ASC, and {@code hc-provider-a-java-<uuid>} sorts
 * before {@code hc-provider-b-java-<uuid>}. So the consumer deterministically
 * starts on A and any answer naming B is a real re-resolution.
 */
@SpringBootApplication
@MeshAgent(
    name = "hc-provider-b-java",
    version = "1.0.0",
    description = "Survivor provider that the consumer fails over to (#1480)",
    port = 3432
)
public class HcProviderBApplication {

    static final String AGENT_NAME = "hc-provider-b-java";

    public static void main(String[] args) {
        SpringApplication.run(HcProviderBApplication.class, args);
    }

    @MeshTool(
        capability = "hc_probe_java",
        description = "Report which provider instance served this call",
        tags = {"hc-withdrawal"}
    )
    public Map<String, Object> probeB() {
        return Map.of("served_by", AGENT_NAME, "pid", ProcessHandle.current().pid());
    }
}
