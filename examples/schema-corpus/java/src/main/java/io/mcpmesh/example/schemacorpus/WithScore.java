package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;

/**
 * Pattern 11: NumberConstraints — int field with [0, 100] bounds.
 *
 * <p>{@code @Min}/{@code @Max} are picked up by the JakartaValidationModule (see
 * MeshSchemaSupport) and emitted as {@code minimum}/{@code maximum} JSON Schema
 * keywords, matching Pydantic's {@code Field(ge=0, le=100)} and Zod's
 * {@code .min(0).max(100)}.
 */
public record WithScore(@Min(0) @Max(100) int value) {}
