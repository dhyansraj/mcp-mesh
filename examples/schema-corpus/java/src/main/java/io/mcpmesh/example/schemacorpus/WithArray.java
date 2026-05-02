package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.NotNull;
import java.util.List;

/**
 * Pattern 6: WithArray — {@code List<String>}.
 */
public record WithArray(@NotNull List<String> tags) {}
