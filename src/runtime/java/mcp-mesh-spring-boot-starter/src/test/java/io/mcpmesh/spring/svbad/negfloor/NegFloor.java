package io.mcpmesh.spring.svbad.negfloor;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

/** Boot-fail (MED-7): a negative minAvailable floor. */
public final class NegFloor {

    private NegFloor() {
    }

    @McpMeshService(minAvailable = -1)
    public interface NegFloorService {
        @Selector(capability = "nf.a")
        String a();
    }
}
