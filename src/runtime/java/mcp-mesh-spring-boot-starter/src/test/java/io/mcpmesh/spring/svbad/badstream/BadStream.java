package io.mcpmesh.spring.svbad.badstream;

import io.mcpmesh.MeshService;
import io.mcpmesh.Selector;

import java.util.concurrent.Flow;

/** Boot-fail (MED-8): a streaming view whose chunk type is not String. */
public final class BadStream {

    private BadStream() {
    }

    @MeshService
    public interface BadStreamService {
        @Selector(capability = "bs.cap")
        Flow.Publisher<Integer> get();
    }
}
