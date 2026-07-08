package io.mcpmesh.spring.svbad.duplicateparam;

import io.mcpmesh.MeshService;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;

/** Boot-fail (MED-4): two parameters share the same @Param name. */
public final class DuplicateParam {

    private DuplicateParam() {
    }

    @MeshService
    public interface DuplicateParamService {
        @Selector(capability = "dp.cap")
        String get(@Param("id") String a, @Param("id") String b);
    }
}
