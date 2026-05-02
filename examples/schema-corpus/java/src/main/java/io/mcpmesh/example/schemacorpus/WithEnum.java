package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.NotNull;

/**
 * Pattern 4: WithEnum — enum with values [admin, user, guest].
 *
 * <p>Jackson's {@code FLATTENED_ENUMS_FROM_JSONVALUE} option (set in
 * MeshSchemaSupport) emits enums as {@code {type: string, enum: [...]}}.
 *
 * <p>{@code @NotNull} ensures Jakarta validation drops the null branch so the
 * canonical enum shape matches Pydantic and Zod (no nullable union wrapping).
 */
public record WithEnum(@NotNull RoleEnum role) {

    public enum RoleEnum {
        admin, user, guest
    }
}
