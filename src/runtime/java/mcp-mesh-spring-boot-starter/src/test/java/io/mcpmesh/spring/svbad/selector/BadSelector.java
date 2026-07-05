package io.mcpmesh.spring.svbad.selector;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

/** Boot-fail fixture: an abstract view method with no {@code @Selector}. */
public final class BadSelector {

    private BadSelector() {
    }

    @McpMeshService
    public interface MissingSelectorService {

        @Selector(capability = "ok.cap")
        String good();

        // No @Selector — must fail context refresh at registration time.
        String missing();
    }
}
