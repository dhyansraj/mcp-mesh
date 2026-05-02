package io.mcpmesh.example.schema.consumer;

import jakarta.validation.constraints.NotNull;

/**
 * Canonical Employee shape — mirrors the producer side.
 *
 * <p>Identical structure across consumer/producer-good Java agents (and across
 * Python/TS counterparts) yields the same canonical hash:
 * sha256:48882e31915113ed70ee620b2245bfcf856e4e146e2eb6e37700809d7338e732.
 */
public record Employee(
    @NotNull String name,
    @NotNull String dept,
    double salary
) {}
