package com.example.signalprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.types.MeshSupersededException;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * uc38 java-signal-provider — emits the typed supersession signal (issue #1278).
 *
 * <p>The Java counterpart of py-signal-provider / ts-signal-provider. Java's
 * emit is DIFFERENT from the Python/TS fastmcp auto-serialize path: a thrown
 * {@link MeshSupersededException} is caught by the framework's MeshToolWrapper
 * and turned into the reserved {@code {"error":"claim_superseded"}} isError
 * envelope. This fixture proves that wrapper-catch emit crosses the REAL
 * JNI/HTTP transport and is recognized by a consumer's injected proxy.
 *
 * <p>These are PLAIN (synchronous) {@code @MeshTool}s, not {@code task=true}
 * job tools: the round-trip under test is a consumer's injected-proxy call that
 * catches the exception inline, which requires a synchronous throw — a task
 * tool would dispatch as an async job and never hand the caller an exception to
 * catch. No epoch dance: the app logic is out of scope; reject-superseded
 * rejects UNCONDITIONALLY.
 *
 * <p>Tool names are the camelCase method names (mesh's Java convention, e.g.
 * uc02 {@code greet}/{@code getInfo}): {@code rejectSuperseded},
 * {@code rejectGeneric}, {@code getRejectCount}.
 */
@MeshAgent(
    name = "java-signal-provider",
    version = "1.0.0",
    description = "uc38 provider that emits the typed supersession signal (issue #1278).",
    port = 9205
)
@SpringBootApplication
public class SignalProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(SignalProviderApplication.class, args);
    }

    // In-process invocation counter. Only rejectSuperseded increments it; a
    // double-invoke on the real transport (a fallback-transport retry) would
    // push this past 1.
    private static final AtomicInteger REJECT_SUPERSEDED_CALLS = new AtomicInteger(0);

    /**
     * Unconditionally rejects the caller as superseded. Counts the REAL
     * provider-side invocation, then throws the typed exception — the framework
     * wrapper emits the reserved claim_superseded envelope.
     */
    @MeshTool(
        capability = "reject-superseded",
        description = "Unconditionally rejects the caller as superseded (issue #1278)"
    )
    public Map<String, Object> rejectSuperseded() {
        REJECT_SUPERSEDED_CALLS.incrementAndGet();
        throw new MeshSupersededException("stale epoch: caller superseded");
    }

    /**
     * Control: fails with a plain (non-envelope) error. The caller must
     * classify this as generic, proving the recognize path is envelope-exact.
     */
    @MeshTool(
        capability = "reject-generic",
        description = "Control: fails with a generic (non-superseded) error"
    )
    public Map<String, Object> rejectGeneric() {
        throw new RuntimeException("generic-provider-failure: this is NOT a supersession");
    }

    /** Reports how many times reject-superseded actually ran in this process. */
    @MeshTool(
        capability = "superseded-call-count",
        description = "Reports how many times reject-superseded was invoked"
    )
    public Map<String, Object> getRejectCount() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("count", REJECT_SUPERSEDED_CALLS.get());
        return out;
    }
}
