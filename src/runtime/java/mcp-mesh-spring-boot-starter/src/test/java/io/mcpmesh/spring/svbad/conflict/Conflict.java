package io.mcpmesh.spring.svbad.conflict;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

/**
 * Boot-fail fixture: two views bind the same capability to conflicting resolved
 * types.
 */
public final class Conflict {

    private Conflict() {
    }

    public record TypeX(String x) {
    }

    public record TypeY(int y) {
    }

    @McpMeshService
    public interface ConflictAService {

        @Selector(capability = "cc.cap")
        TypeX m();
    }

    @McpMeshService
    public interface ConflictBService {

        @Selector(capability = "cc.cap")
        TypeY n();
    }
}
