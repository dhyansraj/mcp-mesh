package io.mcpmesh.example.schemacorpus;

import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import jakarta.validation.constraints.NotNull;

/**
 * Pattern 8: DiscriminatedUnion — Dog|Cat discriminated by {@code kind}.
 *
 * <p>Jackson's {@code @JsonTypeInfo} + {@code @JsonSubTypes} drives polymorphic
 * serialization. The Rust normalizer strips the {@code discriminator} keyword
 * and rewrites {@code oneOf -> anyOf} so the canonical shape matches Pydantic's
 * (after discriminator stripping) and Zod's emission.
 */
public record WithAnimal(@NotNull Animal pet) {

    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.PROPERTY, property = "kind")
    @JsonSubTypes({
        @JsonSubTypes.Type(value = Dog.class, name = "dog"),
        @JsonSubTypes.Type(value = Cat.class, name = "cat"),
    })
    public static abstract class Animal {}

    public static class Dog extends Animal {
        @NotNull
        public String breed;

        public Dog() {}

        public Dog(String breed) {
            this.breed = breed;
        }
    }

    public static class Cat extends Animal {
        public boolean indoor;

        public Cat() {}

        public Cat(boolean indoor) {
            this.indoor = indoor;
        }
    }
}
