package io.mcpmesh.spring.svbad.blankcap;

import io.mcpmesh.MeshService;
import io.mcpmesh.Selector;

/** Boot-fail: @Selector with a blank capability. */
public final class BlankCap {

    private BlankCap() {
    }

    @MeshService
    public interface BlankCapService {
        @Selector(capability = "")
        String get();
    }
}
