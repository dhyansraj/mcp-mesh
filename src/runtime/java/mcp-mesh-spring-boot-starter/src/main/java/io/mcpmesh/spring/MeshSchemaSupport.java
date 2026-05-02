package io.mcpmesh.spring;

import com.github.victools.jsonschema.generator.Option;
import com.github.victools.jsonschema.generator.OptionPreset;
import com.github.victools.jsonschema.generator.SchemaGenerator;
import com.github.victools.jsonschema.generator.SchemaGeneratorConfig;
import com.github.victools.jsonschema.generator.SchemaGeneratorConfigBuilder;
import com.github.victools.jsonschema.generator.SchemaVersion;
import com.github.victools.jsonschema.module.jackson.JacksonOption;
import com.github.victools.jsonschema.module.jackson.JacksonSchemaModule;
import com.github.victools.jsonschema.module.jakarta.validation.JakartaValidationModule;
import com.github.victools.jsonschema.module.jakarta.validation.JakartaValidationOption;
import io.mcpmesh.core.MeshCoreBridge;
import io.mcpmesh.core.MeshObjectMappers;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Shared schema-generation + normalization helpers for the Spring Boot starter.
 *
 * <p>Centralizes the victools/jsonschema-generator config (so producer tool wrappers
 * and consumer dependency wiring emit the same shape) and the bridge to the
 * Rust normalizer (issue #547).
 */
public final class MeshSchemaSupport {

    private static final Logger log = LoggerFactory.getLogger(MeshSchemaSupport.class);

    private static final SchemaGenerator SCHEMA_GENERATOR;
    private static final ObjectMapper JSON = MeshObjectMappers.create();

    static {
        // SKIP_SUBTYPE_LOOKUP: disables the Jackson module's @JsonSubTypes
        // expansion via SubtypeResolver. Required so MeshDiscriminatedUnionProvider
        // (registered below) is the single source of truth for polymorphic schemas
        // — otherwise the SubtypeResolver rewrites property types to a $ref-chain
        // shape that the Rust normalizer mis-merges (drops subclass fields).
        // See MeshDiscriminatedUnionProvider for the canonical anyOf shape.
        JacksonSchemaModule jacksonModule = new JacksonSchemaModule(
            JacksonOption.RESPECT_JSONPROPERTY_REQUIRED,
            JacksonOption.FLATTENED_ENUMS_FROM_JSONVALUE,
            JacksonOption.SKIP_SUBTYPE_LOOKUP
        );
        // jakarta.validation.constraints.@NotNull (and @NotBlank/@NotEmpty) make a field
        // required AND drop the null branch from its type so it matches Pydantic's
        // `name: str` and Zod's `z.string()` shapes (cross-runtime hash equality).
        JakartaValidationModule jakartaModule = new JakartaValidationModule(
            JakartaValidationOption.NOT_NULLABLE_FIELD_IS_REQUIRED,
            JakartaValidationOption.INCLUDE_PATTERN_EXPRESSIONS
        );
        SchemaGeneratorConfigBuilder configBuilder = new SchemaGeneratorConfigBuilder(
                SchemaVersion.DRAFT_2020_12, OptionPreset.PLAIN_JSON)
            .with(jacksonModule)
            .with(jakartaModule)
            .with(Option.PLAIN_DEFINITION_KEYS)
            .with(Option.DEFINITIONS_FOR_ALL_OBJECTS)
            .with(Option.NULLABLE_FIELDS_BY_DEFAULT)
            .with(Option.NULLABLE_ALWAYS_AS_ANYOF)
            .without(Option.SCHEMA_VERSION_INDICATOR);

        // Issue #547: emit a self-contained anyOf for @JsonTypeInfo + @JsonSubTypes
        // polymorphic types so the canonical form matches Pydantic / Zod after Rust
        // normalization. Registered BEFORE the Jackson module's resolver so it wins.
        configBuilder.forTypesInGeneral()
            .withCustomDefinitionProvider(new MeshDiscriminatedUnionProvider());

        configBuilder.forFields()
            .withRequiredCheck(field -> {
                if (field.getType().getErasedType().isPrimitive()) {
                    return true;
                }
                com.fasterxml.jackson.annotation.JsonProperty jsonProp =
                    field.getAnnotationConsideringFieldAndGetter(
                        com.fasterxml.jackson.annotation.JsonProperty.class);
                if (jsonProp != null) {
                    return jsonProp.required();
                }
                Class<?> fieldType = field.getType().getErasedType();
                if (Optional.class.isAssignableFrom(fieldType)) {
                    return false;
                }
                return field.getDeclaringType().getErasedType().isRecord();
            });

        SchemaGeneratorConfig config = configBuilder.build();
        SCHEMA_GENERATOR = new SchemaGenerator(config);
    }

    private MeshSchemaSupport() {}

    /**
     * @return the shared schema generator (DRAFT 2020-12, Jackson-aware)
     */
    public static SchemaGenerator generator() {
        return SCHEMA_GENERATOR;
    }

    /**
     * Generate a raw JSON Schema for a Java class as a JSON string.
     *
     * @param type the class to introspect
     * @return raw JSON Schema as a JSON string, or null if {@code type} is null/Void
     */
    public static String generateRawSchemaJson(Class<?> type) {
        if (type == null || type == Void.class || type == void.class) {
            return null;
        }
        try {
            JsonNode schema = SCHEMA_GENERATOR.generateSchema(type);
            schema = rewriteRootSelfRefs(schema, type);
            return JSON.writeValueAsString(schema);
        } catch (Exception e) {
            log.warn("Failed to generate JSON Schema for {}: {}", type.getName(), e.getMessage());
            return null;
        }
    }

    /**
     * Issue #547: rewrite victools' root self-reference shape into a named
     * {@code $defs} entry so the Rust normalizer's cyclic-def detection can apply
     * its structural-hash rename ({@code Recursive_<sha256[:12]>}).
     *
     * <p>For a self-referencing type like {@code record TreeNode(List<TreeNode> children)},
     * victools emits the root inline with {@code items: {"$ref": "#"}}. The bare
     * {@code "#"} ref is not in the {@code #/$defs/...} form the normalizer
     * expects, so it falls through to a {@code [non-local $ref kept: #]} WARN and
     * misses the rename.
     *
     * <p>This rewrites:
     * <pre>{@code
     *   {"type":"object","properties":{"children":{"type":"array","items":{"$ref":"#"}},...}}
     * }</pre>
     * into:
     * <pre>{@code
     *   {"$ref":"#/$defs/<TypeName>","$defs":{"<TypeName>":{...root content with #/$defs/<TypeName>...}}}
     * }</pre>
     *
     * <p>The root is left as a pure {@code $ref} so the normalizer's
     * {@code inline_refs} treats {@code <TypeName>} as a cyclic def and applies
     * the structural-hash rename. No-op when the schema contains no {@code "#"}
     * ref (the common case).
     */
    static JsonNode rewriteRootSelfRefs(JsonNode root, Class<?> type) {
        if (root == null || !root.isObject()) {
            return root;
        }
        if (!containsRootSelfRef(root)) {
            return root;
        }
        ObjectNode rootObj = (ObjectNode) root;
        // Pull out any pre-existing $defs we should preserve.
        ObjectNode existingDefs = null;
        if (rootObj.has("$defs") && rootObj.get("$defs").isObject()) {
            existingDefs = (ObjectNode) rootObj.get("$defs");
        }

        // Build the body: root content minus $defs, with `#` refs rewritten to
        // `#/$defs/<TypeName>`.
        String defName = type.getSimpleName();
        ObjectNode body = JSON.createObjectNode();
        Iterator<Map.Entry<String, JsonNode>> fields = rootObj.properties().iterator();
        while (fields.hasNext()) {
            Map.Entry<String, JsonNode> entry = fields.next();
            if ("$defs".equals(entry.getKey())) {
                continue;
            }
            body.set(entry.getKey(), entry.getValue());
        }
        String newRef = "#/$defs/" + defName;
        rewriteSelfRefsInPlace(body, newRef);

        // Compose the wrapped root.
        ObjectNode wrapped = JSON.createObjectNode();
        wrapped.put("$ref", newRef);
        ObjectNode defs = JSON.createObjectNode();
        defs.set(defName, body);
        if (existingDefs != null) {
            Iterator<Map.Entry<String, JsonNode>> it = existingDefs.properties().iterator();
            while (it.hasNext()) {
                Map.Entry<String, JsonNode> e = it.next();
                if (!defs.has(e.getKey())) {
                    defs.set(e.getKey(), e.getValue());
                }
            }
        }
        wrapped.set("$defs", defs);
        return wrapped;
    }

    private static boolean containsRootSelfRef(JsonNode node) {
        if (node == null) {
            return false;
        }
        if (node.isObject()) {
            JsonNode ref = node.get("$ref");
            if (ref != null && ref.isString() && "#".equals(ref.asString(""))) {
                return true;
            }
            Iterator<Map.Entry<String, JsonNode>> it = node.properties().iterator();
            while (it.hasNext()) {
                Map.Entry<String, JsonNode> e = it.next();
                if (containsRootSelfRef(e.getValue())) {
                    return true;
                }
            }
            return false;
        }
        if (node.isArray()) {
            for (int i = 0; i < node.size(); i++) {
                if (containsRootSelfRef(node.get(i))) {
                    return true;
                }
            }
        }
        return false;
    }

    private static void rewriteSelfRefsInPlace(JsonNode node, String newRef) {
        if (node == null) {
            return;
        }
        if (node.isObject()) {
            ObjectNode obj = (ObjectNode) node;
            JsonNode ref = obj.get("$ref");
            if (ref != null && ref.isString() && "#".equals(ref.asString(""))) {
                obj.put("$ref", newRef);
            }
            // Recurse into children. Snapshot keys to avoid concurrent modification
            // (we may have mutated $ref above; child mutations don't affect the
            // current iterator since we only call put on existing keys).
            List<String> keys = new ArrayList<>();
            Iterator<String> nameIter = obj.propertyNames().iterator();
            while (nameIter.hasNext()) {
                keys.add(nameIter.next());
            }
            for (String k : keys) {
                rewriteSelfRefsInPlace(obj.get(k), newRef);
            }
        } else if (node.isArray()) {
            ArrayNode arr = (ArrayNode) node;
            for (int i = 0; i < arr.size(); i++) {
                rewriteSelfRefsInPlace(arr.get(i), newRef);
            }
        }
    }

    /**
     * Normalize a raw JSON schema and throw on BLOCK verdict (so agent startup fails fast).
     *
     * @param rawJson raw JSON schema (may be null)
     * @param origin  origin runtime hint (e.g., "java")
     * @param context human-readable context for error messages (e.g., "tool 'lookup' input")
     * @return normalize result, or null when {@code rawJson} is null
     * @throws IllegalStateException when normalization returns BLOCK verdict
     */
    public static MeshCoreBridge.NormalizeResult normalizeOrThrow(
            String rawJson, String origin, String context) {
        if (rawJson == null) {
            return null;
        }
        MeshCoreBridge.NormalizeResult result = MeshCoreBridge.normalizeSchema(rawJson, origin);
        if (result.isBlocked()) {
            throw new IllegalStateException(
                "Schema normalization BLOCKED for " + context + ": "
                    + String.join("; ", result.warnings()));
        }
        return result;
    }

    /**
     * Issue #547 Phase 4: cluster-wide schema strict mode.
     *
     * <p>Reads {@code MCP_MESH_SCHEMA_STRICT} env var. When true, WARN verdicts
     * are promoted to BLOCK so ops can harden a whole cluster without changing
     * every consumer.
     */
    public static boolean clusterStrictEnabled() {
        String v = System.getenv("MCP_MESH_SCHEMA_STRICT");
        if (v == null) {
            return false;
        }
        String lc = v.trim().toLowerCase();
        return "1".equals(lc) || "true".equals(lc) || "yes".equals(lc);
    }

    /**
     * Issue #547 Phase 4: schema verdict policy.
     *
     * <p>Composes the cluster-wide strict knob and the per-tool
     * {@code outputSchemaStrict} override. Returns true when the SDK should
     * refuse agent startup.
     *
     * <ul>
     *   <li>verdict=BLOCK + toolStrict=true  → refuse</li>
     *   <li>verdict=BLOCK + toolStrict=false → log only (override wins)</li>
     *   <li>verdict=WARN  + clusterStrict=true + toolStrict=true  → refuse</li>
     *   <li>verdict=WARN  + clusterStrict=true + toolStrict=false → log only</li>
     *   <li>verdict=WARN  + clusterStrict=false                   → log only</li>
     *   <li>verdict=OK → never refuse</li>
     * </ul>
     */
    public static boolean shouldRefuseStartup(
            String verdict, boolean clusterStrict, boolean toolStrict) {
        if ("BLOCK".equals(verdict)) {
            return toolStrict;
        }
        if ("WARN".equals(verdict)) {
            return clusterStrict && toolStrict;
        }
        return false;
    }

    /**
     * Issue #547 Phase 4: normalize a raw JSON schema and apply the verdict policy.
     *
     * <p>Use this from callsites that need the per-tool override + cluster-wide
     * knob to take effect. Unlike {@link #normalizeOrThrow}, this respects:
     * <ul>
     *   <li>{@code MCP_MESH_SCHEMA_STRICT=true} promoting WARN→BLOCK
     *       (when {@code clusterStrict=true}); throws.</li>
     *   <li>Per-tool {@code outputSchemaStrict=false} demoting BLOCK→WARN
     *       (when {@code toolStrict=false}); logs and returns the result.</li>
     * </ul>
     * Demoted-BLOCK warnings are tagged so the registry-side audit trail can
     * distinguish them from native WARN.
     *
     * @param rawJson       raw JSON schema (may be null)
     * @param origin        origin runtime hint (e.g., "java")
     * @param context       human-readable context for error messages
     * @param clusterStrict cluster-wide strict flag (typically from env var)
     * @param toolStrict    per-tool override (default true = current behavior)
     * @return normalize result with possibly tagged warnings, or null when rawJson is null
     * @throws IllegalStateException when the policy says startup must be refused
     */
    public static MeshCoreBridge.NormalizeResult normalizeWithPolicy(
            String rawJson,
            String origin,
            String context,
            boolean clusterStrict,
            boolean toolStrict) {
        if (rawJson == null) {
            return null;
        }
        MeshCoreBridge.NormalizeResult result = MeshCoreBridge.normalizeSchema(rawJson, origin);
        String verdict = result.verdict();
        List<String> warnings = result.warnings();

        if (shouldRefuseStartup(verdict, clusterStrict, toolStrict)) {
            String promoted = "WARN".equals(verdict)
                ? " (MCP_MESH_SCHEMA_STRICT=true upgraded WARN→BLOCK)"
                : "";
            throw new IllegalStateException(
                "Schema normalization " + verdict + " for " + context + promoted
                    + ": " + String.join("; ", warnings));
        }

        if ("BLOCK".equals(verdict)) {
            // Demoted by per-tool override — log loudly + tag warnings.
            log.warn("Schema BLOCK demoted to WARN for {} (outputSchemaStrict=false): {}",
                context, warnings);
            List<String> tagged = new java.util.ArrayList<>(warnings.size());
            for (String w : warnings) {
                tagged.add("[demoted from BLOCK] " + w);
            }
            return new MeshCoreBridge.NormalizeResult(
                result.canonicalJson(), result.hash(), verdict, tagged);
        }
        if ("WARN".equals(verdict)) {
            log.warn("Schema WARN for {}: {}", context, warnings);
        }
        return result;
    }

    /**
     * Merge a list of warnings into the target list, ignoring null/empty inputs.
     *
     * @param accumulator the list to merge into
     * @param warnings    warnings to add (may be null)
     */
    public static void mergeWarnings(List<String> accumulator, List<String> warnings) {
        if (warnings == null || warnings.isEmpty()) {
            return;
        }
        accumulator.addAll(warnings);
    }
}
