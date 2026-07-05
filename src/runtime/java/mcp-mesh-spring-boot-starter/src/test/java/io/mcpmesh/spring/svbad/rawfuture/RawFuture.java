package io.mcpmesh.spring.svbad.rawfuture;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

import java.util.concurrent.CompletableFuture;

/** Boot-fail (MED-8): raw CompletableFuture with no type argument. */
public final class RawFuture {

    private RawFuture() {
    }

    @McpMeshService
    public interface RawFutureService {
        @SuppressWarnings("rawtypes")
        @Selector(capability = "rf.cap")
        CompletableFuture get();
    }
}
