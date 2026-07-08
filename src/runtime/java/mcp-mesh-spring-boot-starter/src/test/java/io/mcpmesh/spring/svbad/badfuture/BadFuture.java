package io.mcpmesh.spring.svbad.badfuture;

import io.mcpmesh.MeshService;
import io.mcpmesh.Selector;

import java.util.concurrent.Future;

/** Boot-fail (MED-8): a non-CompletableFuture Future/CompletionStage return. */
public final class BadFuture {

    private BadFuture() {
    }

    @MeshService
    public interface BadFutureService {
        @Selector(capability = "bf.cap")
        Future<String> get();
    }
}
