package io.mcpmesh.spring;

import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import jakarta.validation.constraints.NotNull;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Tests for {@link MeshDiscriminatedUnionProvider}: ensures Jackson
 * {@code @JsonTypeInfo} + {@code @JsonSubTypes} polymorphism produces a
 * self-contained {@code anyOf} union with the discriminator field embedded as a
 * {@code const} in every branch (matching Pydantic / Zod canonical shape).
 *
 * <p>Issue #547 — Phase 7 corpus parity (Java).
 */
@DisplayName("MeshDiscriminatedUnionProvider — @JsonSubTypes anyOf canonical")
class MeshDiscriminatedUnionProviderTest {

    private static final ObjectMapper MAPPER = io.mcpmesh.core.MeshObjectMappers.create();

    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.PROPERTY, property = "kind")
    @JsonSubTypes({
        @JsonSubTypes.Type(value = Dog.class, name = "dog"),
        @JsonSubTypes.Type(value = Cat.class, name = "cat"),
    })
    public static abstract class Animal {}

    public static class Dog extends Animal {
        @NotNull public String breed;
        public Dog() {}
    }

    public static class Cat extends Animal {
        public boolean indoor;
        public Cat() {}
    }

    public record WithAnimal(@NotNull Animal pet) {}

    @Nested
    @DisplayName("Base class as root")
    class BaseClassAsRoot {

        @Test
        @DisplayName("@JsonSubTypes base class produces flat anyOf with no $ref chain")
        void baseClassProducesFlatAnyOf() throws Exception {
            String rawJson = MeshSchemaSupport.generateRawSchemaJson(Animal.class);
            assertNotNull(rawJson);
            JsonNode root = MAPPER.readTree(rawJson);

            assertTrue(root.has("anyOf"), "Expected top-level anyOf, got: " + rawJson);
            assertEquals(2, root.get("anyOf").size(), "Expected 2 branches");

            // No $defs should be emitted for the union itself (everything inline).
            assertFalse(root.has("$defs"),
                "Expected no $defs (union should be inline). Got: " + rawJson);
            // No $ref anywhere — INLINE means embedded subtype schemas.
            assertFalse(rawJson.contains("\"$ref\""),
                "Expected no $ref in flat anyOf. Got: " + rawJson);
        }

        @Test
        @DisplayName("Each subtype branch carries its own fields + discriminator const")
        void eachBranchHasSubtypeFieldsAndDiscriminator() throws Exception {
            String rawJson = MeshSchemaSupport.generateRawSchemaJson(Animal.class);
            JsonNode anyOf = MAPPER.readTree(rawJson).get("anyOf");

            JsonNode dogBranch = findBranchByDiscriminator(anyOf, "kind", "dog");
            assertNotNull(dogBranch, "Dog branch missing. Got: " + rawJson);
            assertTrue(dogBranch.path("properties").has("breed"),
                "Dog branch should have 'breed' property. Got: " + dogBranch);
            assertTrue(dogBranch.path("properties").has("kind"),
                "Dog branch should have 'kind' discriminator. Got: " + dogBranch);
            assertEquals("string",
                dogBranch.path("properties").path("kind").path("type").asString(""),
                "Discriminator should declare type=string");

            JsonNode catBranch = findBranchByDiscriminator(anyOf, "kind", "cat");
            assertNotNull(catBranch, "Cat branch missing. Got: " + rawJson);
            assertTrue(catBranch.path("properties").has("indoor"),
                "Cat branch should have 'indoor' property. Got: " + catBranch);
            assertTrue(catBranch.path("properties").has("kind"),
                "Cat branch should have 'kind' discriminator. Got: " + catBranch);
        }

        @Test
        @DisplayName("Discriminator is in required list of every branch")
        void discriminatorIsRequiredInEveryBranch() throws Exception {
            String rawJson = MeshSchemaSupport.generateRawSchemaJson(Animal.class);
            JsonNode anyOf = MAPPER.readTree(rawJson).get("anyOf");

            for (int i = 0; i < anyOf.size(); i++) {
                JsonNode branch = anyOf.get(i);
                JsonNode required = branch.get("required");
                assertNotNull(required, "Branch " + i + " missing 'required'. Got: " + branch);
                boolean hasKind = false;
                for (int j = 0; j < required.size(); j++) {
                    if ("kind".equals(required.get(j).asString(""))) {
                        hasKind = true;
                        break;
                    }
                }
                assertTrue(hasKind,
                    "Branch " + i + " required must include 'kind'. Got: " + branch);
            }
        }
    }

    @Nested
    @DisplayName("Polymorphic field on enclosing record")
    class PolymorphicField {

        @Test
        @DisplayName("Field of polymorphic type produces inline anyOf — no $ref chain")
        void fieldExpandsToInlineAnyOf() throws Exception {
            String rawJson = MeshSchemaSupport.generateRawSchemaJson(WithAnimal.class);
            assertNotNull(rawJson);
            JsonNode root = MAPPER.readTree(rawJson);

            JsonNode pet = root.path("properties").path("pet");
            assertTrue(pet.has("anyOf"),
                "Expected pet.anyOf to be the union. Got: " + rawJson);

            // No $defs at root — everything should be inline.
            assertFalse(root.has("$defs"),
                "Expected no $defs at root (union inline). Got: " + rawJson);
            // No $ref anywhere — confirms SKIP_SUBTYPE_LOOKUP suppressed the
            // Jackson module's expansion in favor of our flat union.
            assertFalse(rawJson.contains("\"$ref\""),
                "Expected no $ref in WithAnimal schema. Got: " + rawJson);
        }

        @Test
        @DisplayName("WithAnimal subtype branches have full fields and discriminator")
        void withAnimalBranchesAreComplete() throws Exception {
            String rawJson = MeshSchemaSupport.generateRawSchemaJson(WithAnimal.class);
            JsonNode anyOf = MAPPER.readTree(rawJson)
                .path("properties").path("pet").path("anyOf");
            assertEquals(2, anyOf.size());

            JsonNode dogBranch = findBranchByDiscriminator(anyOf, "kind", "dog");
            assertNotNull(dogBranch);
            assertTrue(dogBranch.path("properties").has("breed"));

            JsonNode catBranch = findBranchByDiscriminator(anyOf, "kind", "cat");
            assertNotNull(catBranch);
            assertTrue(catBranch.path("properties").has("indoor"));
        }
    }

    @Nested
    @DisplayName("Provider scope")
    class ProviderScope {

        public record Plain(@NotNull String name) {}

        @Test
        @DisplayName("Non-polymorphic class falls through (provider returns null)")
        void nonPolymorphicFallsThrough() throws Exception {
            String rawJson = MeshSchemaSupport.generateRawSchemaJson(Plain.class);
            assertNotNull(rawJson);
            JsonNode root = MAPPER.readTree(rawJson);
            assertFalse(root.has("anyOf"),
                "Plain record should not get anyOf wrapping. Got: " + rawJson);
            assertEquals("object", root.path("type").asString(""));
        }
    }

    private static JsonNode findBranchByDiscriminator(
            JsonNode anyOf, String discriminatorProp, String discriminatorValue) {
        for (int i = 0; i < anyOf.size(); i++) {
            JsonNode branch = anyOf.get(i);
            JsonNode constNode = branch.path("properties").path(discriminatorProp).path("const");
            if (discriminatorValue.equals(constNode.asString(""))) {
                return branch;
            }
        }
        return null;
    }
}
