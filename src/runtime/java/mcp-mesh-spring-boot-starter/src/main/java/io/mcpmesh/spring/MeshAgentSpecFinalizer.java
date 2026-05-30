package io.mcpmesh.spring;

import org.springframework.beans.factory.SmartInitializingSingleton;

/**
 * Idempotent wrapper for the agent-spec finalization callback. Implements
 * {@link SmartInitializingSingleton} so Spring still drives the finalization
 * after every singleton has been instantiated, but exposes
 * {@link #ensureFinalized()} so other late-phase beans can call the
 * finalization explicitly and not rely on SIS callback ordering (which
 * Spring does not honour across beans — neither {@code @DependsOn} nor
 * {@code Ordered} affect the {@code afterSingletonsInstantiated()} sweep).
 *
 * <p>Whichever caller fires first wins; subsequent calls are cheap no-ops
 * guarded by a {@code volatile boolean} flag. This guarantees the spec is
 * fully built before any consumer reads it, no matter what order the
 * SmartInitializingSingleton callbacks happen to run in.
 */
public class MeshAgentSpecFinalizer implements SmartInitializingSingleton {

    private final Runnable delegate;
    private volatile boolean finalized;

    MeshAgentSpecFinalizer(Runnable delegate) {
        this.delegate = delegate;
    }

    /**
     * Run the finalization exactly once on success. Safe to call multiple
     * times from multiple threads — the first caller wins the race and the
     * others return immediately.
     *
     * <p>If {@code delegate.run()} throws, the {@code finalized} flag stays
     * {@code false} so a subsequent caller retries the finalization. The
     * exception propagates unchanged to the current caller. Combined with
     * the {@code synchronized} modifier, this gives at-most-one concurrent
     * attempt and at-least-one successful completion (so long as a later
     * call eventually succeeds).
     */
    public synchronized void ensureFinalized() {
        if (finalized) {
            return;
        }
        delegate.run();
        finalized = true;
    }

    @Override
    public void afterSingletonsInstantiated() {
        ensureFinalized();
    }
}
