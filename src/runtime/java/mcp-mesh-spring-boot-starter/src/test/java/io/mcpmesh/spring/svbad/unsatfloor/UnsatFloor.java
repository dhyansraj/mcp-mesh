package io.mcpmesh.spring.svbad.unsatfloor;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

/** Boot-fail (MED-7): minAvailable exceeds the number of bound methods. */
public final class UnsatFloor {

    private UnsatFloor() {
    }

    @McpMeshService(minAvailable = 3)
    public interface UnsatFloorService {
        @Selector(capability = "uf.a")
        String a();

        @Selector(capability = "uf.b")
        String b();
    }
}
