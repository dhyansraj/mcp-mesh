package io.mcpmesh.example.schemacorpus;

/**
 * Pattern 12: UntaggedUnion — {@code str|int} with no discriminator.
 *
 * <p>Java has no native union type. We use {@code Object} as the field type so
 * Jackson's schema generator emits an open shape; the canonical form is
 * primarily reconciled by extractor convention (the Rust normalizer does not
 * synthesize the {@code anyOf:[string,integer]} branches).
 *
 * <p>Per spike notes, this pattern is fragile — hash equality requires all
 * three runtimes to emit the branches in the same order. WARN-worthy in
 * production. See {@code ~/workspace/schema-spike-547/results.md} pattern 12.
 */
public record WithEither(Object value) {}
