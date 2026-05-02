package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.NotNull;
import java.time.LocalDate;

/**
 * Pattern 7: CaseConversion — camelCase Java fields, already canonical.
 *
 * <p>The normalizer's case-conversion rule rewrites Pydantic's snake_case into
 * camelCase to match Zod's and Java's emission.
 */
public record CaseConversion(
    double marketCap,
    @NotNull LocalDate hireDate,
    boolean isActive
) {}
