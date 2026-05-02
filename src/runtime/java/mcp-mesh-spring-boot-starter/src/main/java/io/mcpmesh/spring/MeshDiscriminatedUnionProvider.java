package io.mcpmesh.spring;

import com.fasterxml.classmate.ResolvedType;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.github.victools.jsonschema.generator.CustomDefinition;
import com.github.victools.jsonschema.generator.CustomDefinitionProviderV2;
import com.github.victools.jsonschema.generator.SchemaGenerationContext;
import com.github.victools.jsonschema.generator.SchemaGeneratorConfig;
import com.github.victools.jsonschema.generator.SchemaKeyword;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Custom definition provider that emits a self-contained {@code anyOf} union for
 * Jackson-style discriminated unions ({@code @JsonTypeInfo + @JsonSubTypes}).
 *
 * <p>The default victools {@code JsonSubTypesResolver} produces a {@code $ref}-chain
 * shape: each subtype gets two {@code $defs} entries — a "raw" one and a "wrapper"
 * that adds the discriminator field via sibling {@code $ref + properties}. When the
 * Rust normalizer ({@code schema_normalize.rs}) inlines those refs it does a shallow
 * merge of {@code properties} / {@code required}, which DROPS the subtype's own
 * fields (e.g. {@code Dog.breed}) — leaving an anyOf branch with only the
 * discriminator.
 *
 * <p>This provider runs BEFORE the Jackson module's resolver. It detects the
 * polymorphic base class, generates each subtype's schema inline, injects the
 * discriminator property as a {@code const}, and returns a single {@code anyOf}
 * with no nested {@code $ref}. The result matches Pydantic's
 * {@code Annotated[Union[...], Field(discriminator=...)]} and Zod's
 * {@code z.discriminatedUnion(...)} after Rust-side oneOf-to-anyOf canonicalization,
 * so cross-runtime hash equality holds.
 *
 * <p>Issue #547 — DiscriminatedUnion canonical parity (Java).
 */
public final class MeshDiscriminatedUnionProvider implements CustomDefinitionProviderV2 {

    @Override
    public CustomDefinition provideCustomSchemaDefinition(
            ResolvedType javaType, SchemaGenerationContext context) {
        if (javaType == null) {
            return null;
        }
        Class<?> erased = javaType.getErasedType();
        JsonTypeInfo typeInfo = erased.getAnnotation(JsonTypeInfo.class);
        JsonSubTypes subTypes = erased.getAnnotation(JsonSubTypes.class);
        if (typeInfo == null || subTypes == null || subTypes.value().length == 0) {
            return null;
        }
        // Only NAME discriminators with PROPERTY inclusion produce a discriminator
        // field on the wire; other forms (CLASS id, WRAPPER_OBJECT, etc.) need
        // different shapes and are out of scope for cross-runtime parity here.
        if (typeInfo.use() != JsonTypeInfo.Id.NAME
                || (typeInfo.include() != JsonTypeInfo.As.PROPERTY
                    && typeInfo.include() != JsonTypeInfo.As.EXISTING_PROPERTY)) {
            return null;
        }
        String discriminatorProp = typeInfo.property();
        if (discriminatorProp == null || discriminatorProp.isEmpty()) {
            // Jackson default property name when @JsonTypeInfo.property is unset.
            discriminatorProp = "@type";
        }

        SchemaGeneratorConfig config = context.getGeneratorConfig();
        ObjectNode schemaNode = config.createObjectNode();
        ArrayNode anyOfArr = schemaNode.putArray(
            context.getKeyword(SchemaKeyword.TAG_ANYOF));

        String propertiesKey = context.getKeyword(SchemaKeyword.TAG_PROPERTIES);
        String requiredKey = context.getKeyword(SchemaKeyword.TAG_REQUIRED);
        String typeKey = context.getKeyword(SchemaKeyword.TAG_TYPE);
        String constKey = context.getKeyword(SchemaKeyword.TAG_CONST);
        String typeStringValue = context.getKeyword(SchemaKeyword.TAG_TYPE_STRING);

        for (JsonSubTypes.Type sub : subTypes.value()) {
            Class<?> subClass = sub.value();
            if (subClass == null) {
                continue;
            }
            String discriminatorValue = sub.name();
            if (discriminatorValue == null || discriminatorValue.isEmpty()) {
                String[] names = sub.names();
                if (names != null && names.length > 0) {
                    discriminatorValue = names[0];
                }
            }
            if (discriminatorValue == null || discriminatorValue.isEmpty()) {
                // Fall back to the simple class name (Jackson default for NAME ids).
                discriminatorValue = subClass.getSimpleName();
            }

            // Generate the subtype's natural schema inline. Pass `this` so we don't
            // re-enter ourselves on the same type (we won't — subtypes lack
            // @JsonSubTypes — but the contract is to skip the calling provider).
            ResolvedType resolvedSub = context.getTypeContext().resolve(subClass);
            ObjectNode subSchema = context.createStandardDefinition(resolvedSub, this);

            // Strip nested $ref/$defs/title bookkeeping from the subtype schema so
            // we can safely merge in the discriminator. The subtype IS a concrete
            // class (no @JsonSubTypes itself), so victools should give us a flat
            // {type:object, properties, required}.
            ObjectNode propsNode;
            if (subSchema.has(propertiesKey) && subSchema.get(propertiesKey).isObject()) {
                propsNode = (ObjectNode) subSchema.get(propertiesKey);
            } else {
                propsNode = subSchema.putObject(propertiesKey);
            }

            // Inject the discriminator property as {"const": "<name>", "type": "string"}.
            ObjectNode discNode = config.createObjectNode();
            discNode.put(constKey, discriminatorValue);
            discNode.put(typeKey, typeStringValue);
            propsNode.set(discriminatorProp, discNode);

            // Ensure the discriminator is in required.
            ArrayNode requiredArr;
            if (subSchema.has(requiredKey) && subSchema.get(requiredKey).isArray()) {
                requiredArr = (ArrayNode) subSchema.get(requiredKey);
            } else {
                requiredArr = subSchema.putArray(requiredKey);
            }
            boolean alreadyRequired = false;
            for (int i = 0; i < requiredArr.size(); i++) {
                if (discriminatorProp.equals(requiredArr.get(i).asString(""))) {
                    alreadyRequired = true;
                    break;
                }
            }
            if (!alreadyRequired) {
                requiredArr.add(discriminatorProp);
            }

            // Make sure the subtype claims it's an object (some configs omit when
            // properties are present).
            if (!subSchema.has(typeKey)) {
                subSchema.put(typeKey, context.getKeyword(SchemaKeyword.TAG_TYPE_OBJECT));
            }

            anyOfArr.add(subSchema);
        }

        // INLINE so the union is embedded directly (no $defs entry, no $ref chain
        // for the Rust normalizer to mis-merge).
        return new CustomDefinition(schemaNode, CustomDefinition.DefinitionType.INLINE,
            CustomDefinition.EXCLUDING_ATTRIBUTES);
    }
}
