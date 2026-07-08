package io.mcpmesh.spring.svtool;

import io.mcpmesh.MeshService;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;

/**
 * RFC #1280 phase-2 coexistence fixture: a view usable BOTH as a phase-1 bean
 * (discovered facade) AND as a {@code @MeshTool} parameter — independent edges.
 */
public final class ToolViews {

    private ToolViews() {
    }

    @MeshService
    public interface CoexistView {
        @Selector(capability = "coexist.one")
        String one(@Param("id") String id);

        @Selector(capability = "coexist.two")
        String two(@Param("id") String id);
    }
}
