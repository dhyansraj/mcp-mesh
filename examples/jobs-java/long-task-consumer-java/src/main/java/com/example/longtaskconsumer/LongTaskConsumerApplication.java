package com.example.longtaskconsumer;

import io.mcpmesh.JobProxy;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MeshJob Phase B — Java Consumer: commission a remote long-running job.
 *
 * <p>Demonstrates the consumer-side dispatch surface in Java:
 * <pre>{@code
 * @MeshTool(
 *     capability = "commission_report",
 *     dependencies = @Selector(capability = "generate_report"))
 * public Map<String, Object> commissionReport(
 *     @Param("user_id") String userId,
 *     @Param("sections") List<String> sections,
 *     MeshJob generateReport) {  // injected as MeshJobSubmitter
 *   var proxy = ((MeshJobSubmitter) generateReport).submit(...).get();
 *   return (Map<String, Object>) proxy.await(60.0);
 * }
 * }</pre>
 *
 * <p>The DI layer sees the {@code MeshJob}-typed parameter and that
 * this method depends on a capability ({@code generate_report}); it
 * injects a {@link MeshJobSubmitter} bound to that capability.
 * {@code submit(...)} posts to {@code /jobs} on the registry and
 * returns a {@link JobProxy} bound to the new job id; {@code await(...)}
 * polls the registry's {@code GET /jobs/{id}} until the status is
 * terminal.
 *
 * <p>Run after the provider is up:
 * <pre>
 * MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "long-task-consumer-java",
    version = "1.0.0",
    description = "MeshJob Phase B (Java) consumer — commissions and awaits remote reports",
    port = 9121
)
@SpringBootApplication
public class LongTaskConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(LongTaskConsumerApplication.class, args);
    }

    @MeshTool(
        capability = "commission_report",
        description = "Commission a report from the long-task provider and await its result. "
            + "Demonstrates the submit-and-wait pattern.",
        dependencies = @Selector(capability = "generate_report")
    )
    @SuppressWarnings("unchecked")
    public Map<String, Object> commissionReport(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            MeshJob generateReport) throws Exception {

        if (!(generateReport instanceof MeshJobSubmitter submitter)) {
            // Defensive: in unit tests or if injection fails, fall back so
            // callers see a clear error message rather than ClassCastException.
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error",
                "generate_report submitter not injected — check that the "
                + "long-task-provider-java is registered with task=true");
            return err;
        }

        if (sections == null) {
            sections = List.of("intro", "analysis", "summary");
        }

        // submit() posts to /jobs and returns a CompletableFuture<JobProxy>
        // bound to the new job id. maxDuration is the per-attempt soft
        // timeout the provider runtime enforces (and the registry's
        // deadline-exceeded cron sweeps if the producer crashes).
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("sections", sections);

        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload,
            null,    // ownerInstanceId — let the registry route via claim
            60,      // maxDuration seconds
            null,    // maxRetries — accept default
            null     // totalDeadline — unlimited
        );
        try (JobProxy proxy = submitter.submit(opts).get()) {
            // Poll the registry until terminal. Returns the producer's
            // complete() payload on success; throws on failure / cancel
            // / timeout.
            Object result = proxy.await(60.0);
            if (result instanceof Map<?, ?> m) {
                return (Map<String, Object>) m;
            }
            Map<String, Object> wrapped = new LinkedHashMap<>();
            wrapped.put("result", result);
            return wrapped;
        }
    }
}
