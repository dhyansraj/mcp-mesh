package io.mcpmesh.spring.svxsrc;

import io.mcpmesh.MeshService;
import io.mcpmesh.Selector;

/**
 * Cross-source resolved-type conflict fixture (MED-5): a view binds {@code xs.cap}
 * to {@link TypeX}. A test pairs it with a {@code @MeshDependsOn} declaring the
 * same capability with a conflicting (or matching) expectedType.
 */
public final class XsrcViews {

    private XsrcViews() {
    }

    public record TypeX(String x) {
    }

    public record TypeY(int y) {
    }

    @MeshService
    public interface XsrcView {
        @Selector(capability = "xs.cap")
        TypeX get();
    }
}
