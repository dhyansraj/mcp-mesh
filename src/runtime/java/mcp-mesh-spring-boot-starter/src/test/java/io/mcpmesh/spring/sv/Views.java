package io.mcpmesh.spring.sv;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Flow;

/**
 * Valid {@link McpMeshService} fixtures for the RFC #1280 integration tests.
 *
 * <p>All views live in this single package so a test can scope classpath
 * discovery to {@code io.mcpmesh.spring.sv} via {@code AutoConfigurationPackages}.
 * The nested interfaces are static (implicitly, inside an interface/class) and
 * therefore "independent" — discoverable by the registrar's Spring-Data-style
 * scanner.
 */
public final class Views {

    private Views() {
    }

    public record ChatRequest(String prompt) {
    }

    public record ChatResult(String text) {
    }

    public record Query(String q) {
    }

    public record Item(String id, String name) {
    }

    /**
     * Behavior view: exercises every param mode (0-arg, single-POJO,
     * multi-{@code @Param}), every return mode (sync, async, stream), a
     * {@code default} method, and mixed required/optional edges.
     */
    @McpMeshService
    public interface LlmService {

        @Selector(capability = "llm.chat", tags = {"+gpt"})
        ChatResult chat(ChatRequest req);

        @Selector(capability = "llm.vision", tags = {"+claude"}, required = true)
        Item vision(Query q);

        @Selector(capability = "llm.list")
        List<String> list();

        @Selector(capability = "llm.lookup")
        Item lookup(@Param("id") String id, @Param("region") String region);

        @Selector(capability = "llm.async")
        CompletableFuture<Item> fetchAsync(Query q);

        @Selector(capability = "llm.stream")
        Flow.Publisher<String> streamIt(@Param("q") String q);

        /** default method — NOT a dependency edge. */
        default String label() {
            return "llm-view";
        }
    }

    /**
     * Determinism view: methods declared reverse-alphabetically so the test can
     * assert the expanded dependency order is sorted by method name regardless.
     */
    @McpMeshService
    public interface DeterminismService {

        @Selector(capability = "det.zeta")
        String zeta();

        @Selector(capability = "det.yankee")
        String yankee();

        @Selector(capability = "det.alpha")
        String alpha();
    }

    /** Floor view: {@code minAvailable=2} over four optional methods (one async). */
    @McpMeshService(minAvailable = 2)
    public interface FloorService {

        @Selector(capability = "floor.a")
        String alpha();

        @Selector(capability = "floor.b")
        String bravo();

        @Selector(capability = "floor.c")
        String charlie();

        @Selector(capability = "floor.d")
        CompletableFuture<String> deltaAsync();
    }

    /** Wire-serialization view: one required + one optional edge. */
    @McpMeshService
    public interface WireService {

        @Selector(capability = "wire.req", required = true)
        String req();

        @Selector(capability = "wire.opt")
        String opt();
    }

    /**
     * Required-wins view: declares {@code rw_cap} required=true so a test can
     * pair it with an optional {@code @MeshDependsOn} on the same capability and
     * assert required wins across sources.
     */
    @McpMeshService
    public interface RequiredWinsService {

        @Selector(capability = "rw_cap", required = true)
        String rw();
    }
}
