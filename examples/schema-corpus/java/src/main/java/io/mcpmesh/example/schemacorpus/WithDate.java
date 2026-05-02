package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.NotNull;
import java.time.LocalDate;

/**
 * Pattern 3: WithDate — {@code LocalDate} field.
 *
 * <p>Jackson's schema generator emits {@code {type: string, format: date}} for
 * {@code LocalDate}, matching Pydantic's emission for {@code date}.
 *
 * <p>{@code @NotNull} ensures Jakarta validation drops the null branch so the
 * canonical form matches Pydantic's required {@code date} field (no nullable
 * union wrapping).
 */
public record WithDate(@NotNull LocalDate hireDate) {}
