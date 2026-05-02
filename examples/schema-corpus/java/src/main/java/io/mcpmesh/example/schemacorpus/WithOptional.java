package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.NotNull;

/**
 * Pattern 2: Optional — required {@code name} + nullable optional {@code nickname}.
 *
 * <p>{@code @NotNull} on {@code name} matches Pydantic's {@code name: str}.
 * Absence of {@code @NotNull} on {@code nickname} matches Pydantic's
 * {@code nickname: Optional[str] = None} via {@code NULLABLE_FIELDS_BY_DEFAULT}
 * + {@code NULLABLE_ALWAYS_AS_ANYOF} from MeshSchemaSupport.
 *
 * <p>NOTE: Records require all fields, so we use a regular class to allow
 * {@code nickname} to be optional/nullable in the generated schema (the SDK's
 * required-check returns false for non-record, non-{@code @NotNull} fields).
 */
public class WithOptional {
    @NotNull
    public String name;
    public String nickname;

    public WithOptional() {}

    public WithOptional(String name, String nickname) {
        this.name = name;
        this.nickname = nickname;
    }
}
