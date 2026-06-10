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
     * Build the MCP input schema for a {@code @MeshTool} method from its
     * {@code @Param}-annotated parameters.
     *
     * <p>Issue #1164 MED-2: this is the SINGLE source of truth for tool input
     * schemas — both the MCP-served schema ({@link MeshToolWrapper}) and the
     * heartbeat catalog ({@link MeshToolRegistry}) call this method, so the
     * registry-advertised {@code input_schema} / {@code input_schema_hash}
     * always represents the schema the MCP server actually serves. Previously
     * the registry hand-rolled a shallow {@code {"type": ...}} per parameter
     * (POJO → bare {@code {"type":"object"}}, {@code List<Foo>} → bare
     * {@code {"type":"array"}}), so heartbeat-derived consumers (cross-runtime
     * schema matching #547, llm_tools definitions) saw an impoverished shape
     * that diverged from the served one.
     *
     * <p>Per-parameter schemas come from the shared victools {@link #generator()}
     * (full nesting, {@code required}, {@code anyOf} nullability). Each
     * parameter's {@code $defs} block is hoisted to the root schema so the
     * composed document's {@code #/$defs/...} pointers stay resolvable; name
     * collisions between structurally different defs (same simple name,
     * different package) are disambiguated with a numeric suffix.
     *
     * <p>Parameters without {@code @Param} (injectable types: {@code McpMeshTool},
     * {@code MeshLlmAgent}, {@code MeshJob}, {@code A2AClient}) are excluded by
     * construction. {@code @MediaParam} contributes {@code x-media-type} and a
     * media-note description suffix (kept from the legacy registry builder).
     *
     * @param method the {@code @MeshTool}-annotated method
     * @return the composed input schema ({@code type/properties/required/$defs})
     */
    public static Map<String, Object> buildToolInputSchema(java.lang.reflect.Method method) {
        Map<String, Object> schema = new java.util.LinkedHashMap<>();
        schema.put("type", "object");

        Map<String, Object> properties = new java.util.LinkedHashMap<>();
        List<String> required = new ArrayList<>();
        Map<String, Object> rootDefs = new java.util.LinkedHashMap<>();

        java.lang.reflect.Parameter[] params = method.getParameters();
        java.lang.reflect.Type[] genericTypes = method.getGenericParameterTypes();

        for (int i = 0; i < params.length; i++) {
            io.mcpmesh.Param paramAnn = params[i].getAnnotation(io.mcpmesh.Param.class);
            if (paramAnn == null) {
                continue; // injectable / non-MCP parameter
            }

            Map<String, Object> propSchema = generateParameterSchema(genericTypes[i]);
            hoistDefs(propSchema, rootDefs);

            // @Param description WINS over a victools-derived one (Jackson
            // @JsonClassDescription on the parameter type, etc.) — the
            // user's per-parameter annotation is the more specific intent,
            // and the legacy heartbeat builder always used @Param here, so
            // letting the type-derived text shadow it would silently change
            // registry-advertised descriptions (#1164 review follow-up).
            // When @Param carries no description, the derived one is kept.
            if (!paramAnn.description().isEmpty()) {
                propSchema.put("description", paramAnn.description());
            }

            io.mcpmesh.MediaParam mediaParamAnn = params[i].getAnnotation(io.mcpmesh.MediaParam.class);
            if (mediaParamAnn != null) {
                propSchema.put("x-media-type", mediaParamAnn.value());
                String existingDesc = String.valueOf(propSchema.getOrDefault("description", ""));
                String mediaNote = "(accepts media URI: " + mediaParamAnn.value() + ")";
                if (!existingDesc.contains(mediaNote)) {
                    propSchema.put("description", (existingDesc + " " + mediaNote).trim());
                }
            }

            properties.put(paramAnn.value(), propSchema);
            if (paramAnn.required()) {
                required.add(paramAnn.value());
            }
        }

        schema.put("properties", properties);
        if (!required.isEmpty()) {
            schema.put("required", required);
        }
        if (!rootDefs.isEmpty()) {
            schema.put("$defs", rootDefs);
        }
        return schema;
    }

    /**
     * Generate the victools schema for one parameter type as a mutable Map.
     * Bare {@code "#"} root self-refs (recursive parameter types) are rewritten
     * to a named {@code $defs} entry first — embedding a bare {@code "#"} into
     * the composed tool schema would re-point it at the wrong root.
     * Falls back to {@code {"type":"object"}} on generation failure.
     */
    private static Map<String, Object> generateParameterSchema(java.lang.reflect.Type type) {
        try {
            JsonNode node = SCHEMA_GENERATOR.generateSchema(type);
            node = rewriteRootSelfRefs(node, rawClassOf(type));
            Map<String, Object> map = JSON.convertValue(
                node, new tools.jackson.core.type.TypeReference<Map<String, Object>>() {});
            if (map != null) {
                return map;
            }
        } catch (Exception e) {
            log.warn("Failed to generate JSON Schema for tool parameter type {}: {}", type, e.getMessage());
        }
        Map<String, Object> fallback = new java.util.LinkedHashMap<>();
        fallback.put("type", "object");
        return fallback;
    }

    /** Erased class of a reflective Type (for $defs naming); Object.class fallback. */
    private static Class<?> rawClassOf(java.lang.reflect.Type type) {
        if (type instanceof Class<?> c) {
            return c;
        }
        if (type instanceof java.lang.reflect.ParameterizedType pt
                && pt.getRawType() instanceof Class<?> raw) {
            return raw;
        }
        return Object.class;
    }

    /**
     * Hoist a property schema's {@code $defs} block into the composed root
     * schema's defs map, in place. Structurally identical defs are reused;
     * same-name-different-body collisions get a numeric-suffix rename, with
     * every {@code #/$defs/<name>} pointer inside the property subtree (and
     * its own def bodies) rewritten to the disambiguated name.
     *
     * <p>Collision detection iterates to a FIXPOINT over post-rename bodies
     * (#1164 review follow-up): a def whose body only diverges from the root
     * entry AFTER a nested ref is renamed (e.g. two same-named {@code Wrap}
     * defs referencing two different same-named {@code Item} defs) must also
     * be disambiguated. A single pre-rename comparison pass judged such defs
     * structurally equal, dropped the second one via putIfAbsent, and silently
     * served the WRONG nested subtree (the renamed {@code Item_2} def was
     * hoisted but orphaned). Each iteration compares the candidate body with
     * all renames-so-far applied; every iteration adds at least one rename, so
     * the loop is bounded by the def count.
     */
    @SuppressWarnings("unchecked")
    private static void hoistDefs(Map<String, Object> propSchema, Map<String, Object> rootDefs) {
        Object defsObj = propSchema.remove("$defs");
        if (!(defsObj instanceof Map)) {
            return;
        }
        Map<String, Object> propDefs = (Map<String, Object>) defsObj;

        Map<String, String> renames = new java.util.LinkedHashMap<>();
        while (true) {
            Map<String, String> newRenames = new java.util.LinkedHashMap<>();
            for (Map.Entry<String, Object> e : propDefs.entrySet()) {
                String name = e.getKey();
                if (renames.containsKey(name) || !rootDefs.containsKey(name)) {
                    continue;
                }
                // Compare what WOULD be stored: the body with all renames
                // decided so far applied (on a copy — the in-place rewrite
                // happens once, below, after the rename set is final).
                Object candidateBody = deepCopy(e.getValue());
                if (!renames.isEmpty()) {
                    renameDefsRefs(candidateBody, renames);
                }
                if (!rootDefs.get(name).equals(candidateBody)) {
                    int suffix = 2;
                    String candidate = name + "_" + suffix;
                    while (rootDefs.containsKey(candidate) || propDefs.containsKey(candidate)
                            || renames.containsValue(candidate)) {
                        candidate = name + "_" + (++suffix);
                    }
                    newRenames.put(name, candidate);
                    log.debug("$defs name collision on '{}' while composing tool input schema — "
                        + "disambiguated to '{}'", name, candidate);
                }
            }
            if (newRenames.isEmpty()) {
                break;
            }
            renames.putAll(newRenames);
        }
        if (!renames.isEmpty()) {
            renameDefsRefs(propSchema, renames);
            for (Object defBody : propDefs.values()) {
                renameDefsRefs(defBody, renames);
            }
        }
        for (Map.Entry<String, Object> e : propDefs.entrySet()) {
            String target = renames.getOrDefault(e.getKey(), e.getKey());
            rootDefs.putIfAbsent(target, e.getValue());
        }
    }

    /** Rewrite {@code "#/$defs/<old>"} pointers per the rename map, in place. */
    @SuppressWarnings("unchecked")
    private static void renameDefsRefs(Object node, Map<String, String> renames) {
        if (node instanceof Map<?, ?> m) {
            Map<String, Object> obj = (Map<String, Object>) m;
            Object ref = obj.get("$ref");
            if (ref instanceof String s && s.startsWith("#/$defs/")) {
                String name = s.substring("#/$defs/".length());
                String renamed = renames.get(name);
                if (renamed != null) {
                    obj.put("$ref", "#/$defs/" + renamed);
                }
            }
            for (Object v : obj.values()) {
                renameDefsRefs(v, renames);
            }
        } else if (node instanceof List<?> l) {
            for (Object item : l) {
                renameDefsRefs(item, renames);
            }
        }
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
        // `#/$defs/<TypeName>`. Issue #1164 LOW: a pre-existing $defs entry with
        // the same simple name (another package's type) must NOT be shadowed —
        // its internal refs point at the old body. Disambiguate the new root
        // def with a numeric suffix instead.
        String defName = type.getSimpleName();
        if (existingDefs != null && existingDefs.has(defName)) {
            int suffix = 2;
            String candidate = defName + "_" + suffix;
            while (existingDefs.has(candidate)) {
                candidate = defName + "_" + (++suffix);
            }
            log.debug("rewriteRootSelfRefs: $defs already contains '{}' — "
                + "disambiguating root self-ref def to '{}'", defName, candidate);
            defName = candidate;
        }
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
     * Inline every {@code $ref} in a victools-generated schema, returning a
     * self-contained schema with the root {@code $defs}/{@code definitions} removed.
     *
     * <p>The shared {@link #generator()} emits {@code DEFINITIONS_FOR_ALL_OBJECTS}
     * + {@code NULLABLE_ALWAYS_AS_ANYOF}, i.e. {@code $defs} + {@code $ref} +
     * {@code anyOf}. Some LLM providers (notably Anthropic hint mode) need a
     * fully self-contained schema with no {@code $ref} indirection, so this
     * resolves and inlines each reference in place.
     *
     * <p>Behaviour:
     * <ul>
     *   <li>Resolves {@code "#/$defs/<Name>"} and {@code "#/definitions/<Name>"}
     *       pointers against the root {@code $defs}/{@code definitions} map.</li>
     *   <li>Recurses through {@code properties}, {@code items} (object or array),
     *       {@code additionalProperties} (when a schema object) and the
     *       {@code anyOf}/{@code oneOf}/{@code allOf} arrays.</li>
     *   <li>Deep-copies each resolved definition per inline site, so multiple
     *       references to the same def never share mutable state.</li>
     *   <li>Guards cycles: a {@code $ref} that targets a name already on the
     *       expansion stack collapses to a bounded {@code {"type":"object"}}
     *       placeholder instead of recursing forever.</li>
     *   <li>A {@code $ref} node with sibling keys (e.g.
     *       {@code {"$ref":"...","description":"..."}}) inlines the resolved
     *       definition, then overlays the sibling keys (excluding {@code $ref}).</li>
     *   <li>Preserves all other keys verbatim and drops the root
     *       {@code $defs}/{@code definitions}.</li>
     * </ul>
     *
     * <p>Pure Java; null-safe. {@code null} in returns {@code null} out.
     *
     * @param schema victools schema as a Map (possibly null)
     * @return a self-contained schema Map with refs inlined, or {@code null}
     */
    @SuppressWarnings("unchecked")
    public static Map<String, Object> inlineRefs(Map<String, Object> schema) {
        if (schema == null) {
            return null;
        }
        Map<String, Object> defs = new java.util.LinkedHashMap<>();
        Object dollarDefs = schema.get("$defs");
        if (dollarDefs instanceof Map<?, ?> m) {
            defs.putAll((Map<String, Object>) m);
        }
        Object plainDefs = schema.get("definitions");
        if (plainDefs instanceof Map<?, ?> m) {
            defs.putAll((Map<String, Object>) m);
        }

        Map<String, Object> result =
            (Map<String, Object>) inlineNode(schema, defs, new java.util.LinkedHashSet<>());
        result.remove("$defs");
        result.remove("definitions");
        return result;
    }

    /**
     * Recursively inline refs within a single JSON-schema node.
     *
     * @param node    the node to process (any JSON value)
     * @param defs    flattened root definition map ($defs + definitions)
     * @param stack   names currently being expanded (cycle guard)
     * @return a new, ref-free node (deep copies on inline)
     */
    @SuppressWarnings("unchecked")
    private static Object inlineNode(Object node, Map<String, Object> defs, java.util.Set<String> stack) {
        if (node instanceof Map<?, ?> mapNode) {
            Map<String, Object> obj = (Map<String, Object>) mapNode;
            Object refVal = obj.get("$ref");
            if (refVal instanceof String ref) {
                String name = refDefName(ref);
                if (name != null) {
                    boolean cycle = stack.contains(name);
                    boolean dangling = !defs.containsKey(name);
                    if (cycle || dangling) {
                        // Cycle (self/recursive type) or dangling ref: emit a
                        // bounded placeholder so inlining always terminates.
                        // Recursive response models are rare; termination wins
                        // over preserving unbounded nesting depth here.
                        // A dangling ref is a real defect (the def map is missing
                        // the target) — warn loudly; an expected cycle stays silent.
                        if (dangling && !cycle) {
                            log.warn("inlineRefs: unresolved $ref '{}' (no matching def) "
                                + "— emitting bounded {{\"type\":\"object\"}} placeholder", ref);
                        }
                        Map<String, Object> placeholder = new java.util.LinkedHashMap<>();
                        placeholder.put("type", "object");
                        // Overlay any sibling keys (description, etc.).
                        for (Map.Entry<String, Object> e : obj.entrySet()) {
                            if (!"$ref".equals(e.getKey())) {
                                placeholder.put(e.getKey(), deepCopy(e.getValue()));
                            }
                        }
                        return placeholder;
                    }
                    stack.add(name);
                    Object resolved = inlineNode(defs.get(name), defs, stack);
                    stack.remove(name);
                    // Overlay sibling keys (excluding $ref) on top of the def.
                    // `resolved`/`merged` is always a freshly-built tree from
                    // inlineNode (never a shared def), so the in-place put is safe.
                    if (resolved instanceof Map) {
                        Map<String, Object> merged = (Map<String, Object>) resolved;
                        for (Map.Entry<String, Object> e : obj.entrySet()) {
                            if (!"$ref".equals(e.getKey())) {
                                merged.put(e.getKey(), deepCopy(e.getValue()));
                            }
                        }
                        return merged;
                    }
                    return resolved;
                }
                // Unrecognized ref form — fall through and copy verbatim.
            }

            Map<String, Object> out = new java.util.LinkedHashMap<>();
            for (Map.Entry<String, Object> e : obj.entrySet()) {
                out.put(e.getKey(), inlineNode(e.getValue(), defs, stack));
            }
            return out;
        }
        if (node instanceof List<?> listNode) {
            List<Object> out = new ArrayList<>(listNode.size());
            for (Object item : listNode) {
                out.add(inlineNode(item, defs, stack));
            }
            return out;
        }
        // Scalars are immutable — return as-is.
        return node;
    }

    /** Extract {@code <Name>} from {@code "#/$defs/<Name>"} or {@code "#/definitions/<Name>"}. */
    private static String refDefName(String ref) {
        if (ref == null) {
            return null;
        }
        if (ref.startsWith("#/$defs/")) {
            return ref.substring("#/$defs/".length());
        }
        if (ref.startsWith("#/definitions/")) {
            return ref.substring("#/definitions/".length());
        }
        return null;
    }

    /** Deep-copy a JSON-shaped value (Map/List/scalar) so inline sites never share state. */
    @SuppressWarnings("unchecked")
    private static Object deepCopy(Object node) {
        if (node instanceof Map<?, ?> m) {
            Map<String, Object> out = new java.util.LinkedHashMap<>();
            for (Map.Entry<String, Object> e : ((Map<String, Object>) m).entrySet()) {
                out.put(e.getKey(), deepCopy(e.getValue()));
            }
            return out;
        }
        if (node instanceof List<?> l) {
            List<Object> out = new ArrayList<>(l.size());
            for (Object item : l) {
                out.add(deepCopy(item));
            }
            return out;
        }
        return node;
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
