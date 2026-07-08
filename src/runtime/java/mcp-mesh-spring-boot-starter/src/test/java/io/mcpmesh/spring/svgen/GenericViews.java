package io.mcpmesh.spring.svgen;

import io.mcpmesh.MeshService;
import io.mcpmesh.Selector;

/**
 * MED-3 fixtures: generic super-interfaces, covariant overrides (bridge-method
 * skipping), and diamond inheritance.
 */
public final class GenericViews {

    private GenericViews() {
    }

    public record Item(String id, String name) {
    }

    /** Generic base — the view binds T via {@code extends Base<Item>}. */
    public interface Base<T> {
        @Selector(capability = "gen.get")
        T get();
    }

    @MeshService
    public interface GenericView extends Base<Item> {
    }

    /** Covariant override: the concrete return is Item; a bridge {@code Object thing()} is generated. */
    public interface CovBase {
        Object thing();
    }

    @MeshService
    public interface CovView extends CovBase {
        @Override
        @Selector(capability = "cov.thing")
        Item thing();
    }

    /** Diamond: both super-interfaces declare the same @Selector method. */
    public interface DiamondA {
        @Selector(capability = "diamond.x")
        String x();
    }

    public interface DiamondB {
        @Selector(capability = "diamond.x")
        String x();
    }

    @MeshService
    public interface DiamondView extends DiamondA, DiamondB {
    }

    /**
     * Diamond where only ONE super-interface annotates the shared signature. The
     * annotated declaration must always win the dedupe regardless of
     * {@code Class#getMethods()} iteration order — a single JVM run can't force
     * the order, but the fixture pins the intent (boots with the annotated
     * binding for {@code diamond.mixed}).
     */
    public interface AnnotatedSide {
        @Selector(capability = "diamond.mixed")
        String mixed();
    }

    public interface PlainSide {
        String mixed();
    }

    @MeshService
    public interface MixedDiamondView extends AnnotatedSide, PlainSide {
    }
}
