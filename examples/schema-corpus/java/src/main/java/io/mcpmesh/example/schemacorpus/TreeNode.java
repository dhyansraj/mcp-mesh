package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.NotNull;
import java.util.List;

/**
 * Pattern 9: Recursive — self-referencing TreeNode.
 *
 * <p>victools/jsonschema-generator detects the cycle and emits {@code $defs} +
 * {@code $ref}. The Rust normalizer renames the cyclic def to
 * {@code Recursive_<sha256[:12]>} so the canonical form is independent of the
 * Java class name.
 */
public record TreeNode(
    @NotNull String value,
    @NotNull List<TreeNode> children
) {}
