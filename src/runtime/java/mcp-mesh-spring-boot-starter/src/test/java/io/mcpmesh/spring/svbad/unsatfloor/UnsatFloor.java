package io.mcpmesh.spring.svbad.unsatfloor;

import io.mcpmesh.MeshService;
import io.mcpmesh.Selector;

/** Boot-fail (MED-7): minAvailable exceeds the number of bound methods. */
public final class UnsatFloor {

    private UnsatFloor() {
    }

    @MeshService(minAvailable = 3)
    public interface UnsatFloorService {
        @Selector(capability = "uf.a")
        String a();

        @Selector(capability = "uf.b")
        String b();
    }
}
