package io.mcpmesh.spring.svmulti;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

/**
 * Cross-view determinism fixture: two single-method views declared in reverse
 * alphabetical order. {@code discoveredServices()} sorts views by interface
 * name, so the expanded dependency order must be [mv.alpha, mv.zulu].
 */
public final class MultiViews {

    private MultiViews() {
    }

    @McpMeshService
    public interface ZuluView {
        @Selector(capability = "mv.zulu")
        String zulu();
    }

    @McpMeshService
    public interface AlphaView {
        @Selector(capability = "mv.alpha")
        String alpha();
    }
}
