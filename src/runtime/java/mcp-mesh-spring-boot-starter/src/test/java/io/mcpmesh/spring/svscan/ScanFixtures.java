package io.mcpmesh.spring.svscan;

import io.mcpmesh.MeshService;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;

/**
 * RFC #1280 phase-3 review (HIGH-1a): a directly-annotated parent view + a
 * sub-interface that only INHERITS the annotation. Only the parent is a scanned
 * bean view; the sub-interface is NOT co-discovered.
 */
public final class ScanFixtures {

    private ScanFixtures() {
    }

    @MeshService
    public interface ScanParent {
        @Selector(capability = "scan.p")
        String p(@Param("id") String id);
    }

    public interface ScanChild extends ScanParent {
        // Inherits @MeshService — must NOT be auto-discovered as a bean view.
    }
}
