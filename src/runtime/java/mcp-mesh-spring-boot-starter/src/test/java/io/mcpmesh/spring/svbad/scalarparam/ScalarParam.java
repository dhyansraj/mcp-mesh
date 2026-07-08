package io.mcpmesh.spring.svbad.scalarparam;

import io.mcpmesh.MeshService;
import io.mcpmesh.Selector;

/** Boot-fail (MED-1): a lone unannotated scalar parameter. */
public final class ScalarParam {

    private ScalarParam() {
    }

    @MeshService
    public interface ScalarParamService {
        @Selector(capability = "sp.cap")
        String get(String id);
    }
}
