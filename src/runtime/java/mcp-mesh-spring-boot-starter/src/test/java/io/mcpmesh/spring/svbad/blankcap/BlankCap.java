package io.mcpmesh.spring.svbad.blankcap;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

/** Boot-fail: @Selector with a blank capability. */
public final class BlankCap {

    private BlankCap() {
    }

    @McpMeshService
    public interface BlankCapService {
        @Selector(capability = "")
        String get();
    }
}
