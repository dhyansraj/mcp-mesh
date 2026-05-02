package io.mcpmesh.example.schema.producerbad;

/**
 * Hardware shape — intentionally mismatched with Employee to verify that
 * schema-aware consumers evict this rogue producer.
 *
 * <p>Canonical hash:
 * sha256:5f1ac9c41f432516a62aebef8841df800fba29342d114eb3813788d16cfa690c.
 */
public record Hardware(
    String sku,
    String model,
    double price
) {}
