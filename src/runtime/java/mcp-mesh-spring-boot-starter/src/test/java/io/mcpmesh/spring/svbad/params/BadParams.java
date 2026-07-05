package io.mcpmesh.spring.svbad.params;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;

/**
 * Boot-fail fixture: a view method with 2+ parameters where at least one is
 * missing {@code @Param} (mixed signature).
 */
public final class BadParams {

    private BadParams() {
    }

    @McpMeshService
    public interface MixedParamsService {

        @Selector(capability = "bp.cap")
        String twoArgs(@Param("a") String a, String b);
    }
}
