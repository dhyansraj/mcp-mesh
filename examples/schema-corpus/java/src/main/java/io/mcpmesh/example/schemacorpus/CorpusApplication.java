package io.mcpmesh.example.schemacorpus;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Schema-corpus producer (Java) — 12-pattern matrix for issue #547 Phase 7.
 *
 * <p>Twelve {@code @MeshTool} methods, each producing a different schema pattern
 * from the cross-runtime canonical-form spike. Paired with Python and TypeScript
 * corpus producers to prove end-to-end that all twelve patterns canonicalize to
 * the same hash across runtimes.
 *
 * <p>Pattern source: {@code ~/workspace/schema-spike-547/java/src/main/java/Extract.java}.
 */
@MeshAgent(
    name = "corpus-java",
    version = "1.0.0",
    description = "Schema-corpus producer (Java) — 12 patterns for issue #547 Phase 7",
    port = 9220
)
@SpringBootApplication
public class CorpusApplication {

    public static void main(String[] args) {
        SpringApplication.run(CorpusApplication.class, args);
    }

    @MeshTool(
        capability = "corpus_primitives",
        description = "Pattern 1: Primitives (str, int, bool, float)",
        outputType = Primitives.class
    )
    public Primitives getPrimitives() {
        return new Primitives("A1", 42, true, 3.14);
    }

    @MeshTool(
        capability = "corpus_optional",
        description = "Pattern 2: Optional[str] field",
        outputType = WithOptional.class
    )
    public WithOptional getOptional() {
        return new WithOptional("Alice", null);
    }

    @MeshTool(
        capability = "corpus_with_date",
        description = "Pattern 3: date field (Pydantic emits format=date)",
        outputType = WithDate.class
    )
    public WithDate getWithDate() {
        return new WithDate(java.time.LocalDate.of(2024, 1, 15));
    }

    @MeshTool(
        capability = "corpus_with_enum",
        description = "Pattern 4: enum with values [admin, user, guest]",
        outputType = WithEnum.class
    )
    public WithEnum getWithEnum() {
        return new WithEnum(WithEnum.RoleEnum.admin);
    }

    @MeshTool(
        capability = "corpus_nested",
        description = "Pattern 5: Nested model (Employee inside Nested)",
        outputType = Nested.class
    )
    public Nested getNested() {
        return new Nested(new Nested.Employee("Alice", "Engineering"));
    }

    @MeshTool(
        capability = "corpus_with_array",
        description = "Pattern 6: list[str]",
        outputType = WithArray.class
    )
    public WithArray getWithArray() {
        return new WithArray(java.util.List.of("alpha", "beta"));
    }

    @MeshTool(
        capability = "corpus_case_conversion",
        description = "Pattern 7: camelCase Java fields (already canonical)",
        outputType = CaseConversion.class
    )
    public CaseConversion getCaseConversion() {
        return new CaseConversion(1.0e9, java.time.LocalDate.of(2024, 1, 15), true);
    }

    @MeshTool(
        capability = "corpus_discriminated_union",
        description = "Pattern 8: DiscriminatedUnion (Dog|Cat by 'kind')",
        outputType = WithAnimal.class
    )
    public WithAnimal getDiscriminatedUnion() {
        return new WithAnimal(new WithAnimal.Dog("Lab"));
    }

    @MeshTool(
        capability = "corpus_recursive",
        description = "Pattern 9: Recursive TreeNode (self-reference)",
        outputType = TreeNode.class
    )
    public TreeNode getRecursive() {
        return new TreeNode("root", java.util.List.of(new TreeNode("child", java.util.List.of())));
    }

    @MeshTool(
        capability = "corpus_inheritance",
        description = "Pattern 10: Inheritance (Manager extends EmployeeBase, flattened)",
        outputType = WithManager.class
    )
    public WithManager getInheritance() {
        return new WithManager(new WithManager.Manager("Alice", "Engineering", 5));
    }

    @MeshTool(
        capability = "corpus_number_constraints",
        description = "Pattern 11: NumberConstraints (@Min(0) @Max(100))",
        outputType = WithScore.class
    )
    public WithScore getNumberConstraints() {
        return new WithScore(50);
    }

    @MeshTool(
        capability = "corpus_untagged_union",
        description = "Pattern 12: UntaggedUnion (str|int, no discriminator)",
        outputType = WithEither.class
    )
    public WithEither getUntaggedUnion() {
        return new WithEither("forty-two");
    }
}
