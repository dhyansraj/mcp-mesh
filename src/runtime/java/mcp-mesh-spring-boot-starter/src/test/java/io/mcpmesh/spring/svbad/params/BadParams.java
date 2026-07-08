package io.mcpmesh.spring.svbad.params;

import io.mcpmesh.MeshService;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;

/**
 * Boot-fail fixture: a view method with 2+ parameters where at least one is
 * missing {@code @Param} (mixed signature).
 */
public final class BadParams {

    private BadParams() {
    }

    @MeshService
    public interface MixedParamsService {

        @Selector(capability = "bp.cap")
        String twoArgs(@Param("a") String a, String b);
    }
}
