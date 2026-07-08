package io.mcpmesh.spring.svbad.selector;

import io.mcpmesh.MeshService;
import io.mcpmesh.Selector;

/** Boot-fail fixture: an abstract view method with no {@code @Selector}. */
public final class BadSelector {

    private BadSelector() {
    }

    @MeshService
    public interface MissingSelectorService {

        @Selector(capability = "ok.cap")
        String good();

        // No @Selector — must fail context refresh at registration time.
        String missing();
    }
}
