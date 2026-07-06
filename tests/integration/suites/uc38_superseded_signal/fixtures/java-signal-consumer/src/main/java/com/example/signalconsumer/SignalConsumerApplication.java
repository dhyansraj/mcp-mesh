package com.example.signalconsumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshSupersededException;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * uc38 java-signal-consumer — RECOGNIZES the typed supersession signal (#1278).
 *
 * <p>The Java counterpart of py-signal-consumer / ts-signal-consumer. Each
 * probe tool calls the provider through an INJECTED {@link McpMeshTool} proxy
 * (the real JNI/HTTP transport) and classifies the outcome:
 *
 * <ul>
 *   <li>{@code probeSuperseded} calls reject-superseded. The injected proxy
 *       must recognize the reserved claim_superseded envelope and re-throw the
 *       typed {@link MeshSupersededException}, so {@code catch
 *       (MeshSupersededException e)} fires and it reports outcome=superseded.
 *       That marker is reachable ONLY via the typed catch — a raw body or a
 *       generic error would land in the generic branch.</li>
 *   <li>{@code probeGeneric} calls reject-generic (the control). The plain
 *       error is NOT the reserved envelope, so the proxy must NOT re-throw
 *       MeshSupersededException; the handler falls through to the generic
 *       branch (outcome=generic).</li>
 * </ul>
 *
 * <p>The catch order matters: {@link MeshSupersededException} extends
 * {@code RuntimeException}, so the specific catch is listed first. Each probe
 * returns a {@code Map} so the caller parses it uniformly via
 * {@code content[0].text | fromjson}.
 *
 * <p>Tool names are the camelCase method names (mesh's Java convention):
 * {@code probeSuperseded}, {@code probeGeneric}.
 */
@MeshAgent(
    name = "java-signal-consumer",
    version = "1.0.0",
    description = "uc38 consumer that recognizes the typed supersession signal (issue #1278).",
    port = 9206
)
@SpringBootApplication
public class SignalConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(SignalConsumerApplication.class, args);
    }

    @MeshTool(
        capability = "probe-superseded",
        description = "Calls reject-superseded via injected proxy and classifies it",
        dependencies = @Selector(capability = "reject-superseded")
    )
    public Map<String, Object> probeSuperseded(McpMeshTool dep) {
        return classify(dep);
    }

    @MeshTool(
        capability = "probe-generic",
        description = "Control: calls reject-generic via injected proxy and classifies it",
        dependencies = @Selector(capability = "reject-generic")
    )
    public Map<String, Object> probeGeneric(McpMeshTool dep) {
        return classify(dep);
    }

    /**
     * Call the injected provider proxy and classify the failure. Reachable
     * outcomes: {@code no_dep} (dependency unresolved), {@code no_error} (the
     * provider unexpectedly succeeded), {@code superseded} (the typed exception
     * was re-thrown by the recognize path), {@code generic} (any other error).
     */
    private Map<String, Object> classify(McpMeshTool dep) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (dep == null) {
            out.put("outcome", "no_dep");
            return out;
        }
        try {
            dep.call();
            out.put("outcome", "no_error");
        } catch (MeshSupersededException e) {
            // Reachable ONLY when the injected proxy recognized the reserved
            // claim_superseded envelope and re-threw the typed exception.
            out.put("outcome", "superseded");
            out.put("detail", e.getDetail());
        } catch (Exception e) {
            // A generic error MUST land here — never misclassified as superseded.
            out.put("outcome", "generic");
            out.put("error_type", e.getClass().getSimpleName());
        }
        return out;
    }
}
