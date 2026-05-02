package io.mcpmesh.spring;

import io.mcpmesh.MediaParam;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.SchemaMode;
import io.mcpmesh.Selector;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshCoreBridge;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry for mesh tools discovered via annotation scanning.
 *
 * <p>Collects metadata from methods annotated with {@code @MeshTool}
 * and provides tool specifications for agent registration.
 */
public class MeshToolRegistry {

    private static final Logger log = LoggerFactory.getLogger(MeshToolRegistry.class);

    private final Map<String, ToolMetadata> tools = new ConcurrentHashMap<>();

    /**
     * Register a tool from an annotated method.
     *
     * @param bean       The bean containing the method
     * @param method     The annotated method
     * @param annotation The @MeshTool annotation
     */
    public void registerTool(Object bean, Method method, MeshTool annotation) {
        String capability = annotation.capability();

        Class<?> outputType = annotation.outputType();
        if (outputType == Void.class || outputType == void.class) {
            outputType = null;
        }

        ToolMetadata metadata = new ToolMetadata(
            capability,
            annotation.description(),
            annotation.version(),
            Arrays.asList(annotation.tags()),
            extractDependencies(annotation.dependencies()),
            extractInputSchema(method),
            outputType,
            // Issue #547 Phase 4: per-tool override (default true = current behavior).
            annotation.outputSchemaStrict(),
            bean,
            method
        );

        tools.put(capability, metadata);
        log.info("Registered mesh tool: {} ({})", capability, method);
    }

    /**
     * Get all registered tools as AgentSpec ToolSpecs.
     *
     * @return List of tool specifications
     */
    public List<AgentSpec.ToolSpec> getToolSpecs() {
        List<AgentSpec.ToolSpec> specs = new ArrayList<>();
        var jsonMapper = JsonMapper.builder().build();

        // Issue #547 Phase 4: cluster-wide strict knob (env var). Per-tool
        // override is read from each tool's metadata inside the loop.
        boolean clusterStrict = MeshSchemaSupport.clusterStrictEnabled();

        for (ToolMetadata meta : tools.values()) {
            AgentSpec.ToolSpec spec = new AgentSpec.ToolSpec();
            spec.setFunctionName(meta.method().getName());
            spec.setCapability(meta.capability());
            spec.setDescription(meta.description());
            spec.setVersion(meta.version());
            spec.setTags(meta.tags());

            // Convert input schema Map to JSON string. The input schema is built
            // from @Param annotations only, so mesh DI parameters (McpMeshTool /
            // MeshLlmAgent) are already excluded by construction (#547).
            String inputSchemaJson;
            try {
                inputSchemaJson = jsonMapper.writeValueAsString(meta.inputSchema());
            } catch (Exception e) {
                inputSchemaJson = "{}";
            }
            spec.setInputSchema(inputSchemaJson);

            // Issue #547 / Phase 4: normalize input + output schemas via Rust core
            // and apply the verdict policy (cluster strict + per-tool override).
            List<String> warnings = new ArrayList<>();
            String contextBase = "tool '" + meta.capability() + "'";
            boolean toolStrict = meta.outputSchemaStrict();

            MeshCoreBridge.NormalizeResult inputResult = MeshSchemaSupport.normalizeWithPolicy(
                inputSchemaJson, "java", contextBase + " input", clusterStrict, toolStrict);
            if (inputResult != null) {
                spec.setInputSchemaCanonical(inputResult.canonicalJson());
                spec.setInputSchemaHash(inputResult.hash());
                MeshSchemaSupport.mergeWarnings(warnings, inputResult.warnings());
            }

            if (meta.outputType() != null) {
                String outputSchemaJson = MeshSchemaSupport.generateRawSchemaJson(meta.outputType());
                if (outputSchemaJson != null) {
                    spec.setOutputSchema(outputSchemaJson);
                    MeshCoreBridge.NormalizeResult outputResult = MeshSchemaSupport.normalizeWithPolicy(
                        outputSchemaJson, "java", contextBase + " output", clusterStrict, toolStrict);
                    if (outputResult != null) {
                        spec.setOutputSchemaCanonical(outputResult.canonicalJson());
                        spec.setOutputSchemaHash(outputResult.hash());
                        MeshSchemaSupport.mergeWarnings(warnings, outputResult.warnings());
                    }
                }
            }

            if (!warnings.isEmpty()) {
                spec.setSchemaWarnings(warnings);
            }

            // Add dependencies to the tool spec
            for (DependencyInfo dep : meta.dependencies()) {
                AgentSpec.DependencySpec depSpec = new AgentSpec.DependencySpec();
                depSpec.setCapability(dep.capability());
                try {
                    depSpec.setTags(jsonMapper.writeValueAsString(dep.tags()));
                } catch (Exception e) {
                    depSpec.setTags("[]");
                }
                depSpec.setVersion(dep.version());
                applySchemaMatching(depSpec, dep, clusterStrict);
                spec.getDependencies().add(depSpec);
            }

            specs.add(spec);
        }

        return specs;
    }

    /**
     * Get all registered tool metadata.
     *
     * @return Collection of tool metadata
     */
    public Collection<ToolMetadata> getAllTools() {
        return Collections.unmodifiableCollection(tools.values());
    }

    /**
     * Get tool metadata by capability name.
     *
     * @param capability The capability name
     * @return Tool metadata, or null if not found
     */
    public ToolMetadata getTool(String capability) {
        return tools.get(capability);
    }

    /**
     * Get all dependency specifications.
     *
     * @return List of dependency specs
     */
    public List<AgentSpec.DependencySpec> getDependencySpecs() {
        List<AgentSpec.DependencySpec> deps = new ArrayList<>();
        boolean clusterStrict = MeshSchemaSupport.clusterStrictEnabled();

        for (ToolMetadata meta : tools.values()) {
            for (DependencyInfo dep : meta.dependencies()) {
                AgentSpec.DependencySpec spec = new AgentSpec.DependencySpec();
                spec.setCapability(dep.capability());
                // Convert List<String> to JSON array string
                try {
                    spec.setTags(JsonMapper.builder().build()
                        .writeValueAsString(dep.tags()));
                } catch (Exception e) {
                    spec.setTags("[]");
                }
                spec.setVersion(dep.version());
                applySchemaMatching(spec, dep, clusterStrict);
                deps.add(spec);
            }
        }

        return deps;
    }

    private List<DependencyInfo> extractDependencies(Selector[] selectors) {
        List<DependencyInfo> deps = new ArrayList<>();
        for (Selector sel : selectors) {
            if (!sel.capability().isEmpty()) {
                Class<?> expectedType = sel.expectedType();
                if (expectedType == Void.class || expectedType == void.class) {
                    expectedType = null;
                }
                deps.add(new DependencyInfo(
                    sel.capability(),
                    Arrays.asList(sel.tags()),
                    sel.version(),
                    expectedType,
                    sel.schemaMode()
                ));
            }
        }
        return deps;
    }

    /**
     * Apply issue #547 schema-aware matching fields to the outgoing AgentSpec
     * dependency. Mirrors {@code MeshRouteRegistry.applySchemaMatching}:
     *
     * <ul>
     *   <li>{@code expectedType} set, {@code schemaMode} unset → default mode SUBSET</li>
     *   <li>{@code schemaMode} set, {@code expectedType} unset → log warning, no schema check</li>
     *   <li>{@code expectedType} set + {@code schemaMode} != NONE → normalize and ship</li>
     *   <li>both unset → backward-compatible no-op</li>
     * </ul>
     *
     * <p>Phase 4: cluster-wide strict knob promotes WARN→BLOCK on the consumer
     * side too. There's no per-tool override here — the override is producer-side.
     */
    private static void applySchemaMatching(
            AgentSpec.DependencySpec target, DependencyInfo source, boolean clusterStrict) {
        Class<?> expectedType = source.expectedType();
        SchemaMode mode = source.schemaMode();
        boolean modeRequested = mode != null && mode != SchemaMode.NONE;

        if (expectedType == null && !modeRequested) {
            return;
        }
        if (expectedType == null) {
            log.warn("Dependency '{}' sets schemaMode={} but no expectedType — ignoring schema match",
                source.capability(), mode);
            return;
        }
        SchemaMode effectiveMode = modeRequested ? mode : SchemaMode.SUBSET;

        String rawJson = MeshSchemaSupport.generateRawSchemaJson(expectedType);
        if (rawJson == null) {
            log.warn("Dependency '{}': failed to generate JSON Schema for expectedType {} — skipping schema match",
                source.capability(), expectedType.getName());
            return;
        }
        MeshCoreBridge.NormalizeResult result = MeshSchemaSupport.normalizeWithPolicy(
            rawJson, "java", "dependency '" + source.capability() + "' expected schema",
            clusterStrict, true);
        if (result == null) {
            return;
        }
        target.setExpectedSchemaCanonical(result.canonicalJson());
        target.setExpectedSchemaHash(result.hash());
        target.setMatchMode(effectiveMode == SchemaMode.STRICT ? "strict" : "subset");
    }

    private Map<String, Object> extractInputSchema(Method method) {
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");

        Map<String, Object> properties = new LinkedHashMap<>();
        List<String> required = new ArrayList<>();

        for (Parameter param : method.getParameters()) {
            Param paramAnn = param.getAnnotation(Param.class);
            if (paramAnn != null) {
                Map<String, Object> propSchema = new LinkedHashMap<>();
                propSchema.put("type", getJsonType(param.getType()));

                if (!paramAnn.description().isEmpty()) {
                    propSchema.put("description", paramAnn.description());
                }

                MediaParam mediaParamAnn = param.getAnnotation(MediaParam.class);
                if (mediaParamAnn != null) {
                    propSchema.put("x-media-type", mediaParamAnn.value());
                    String existingDesc = (String) propSchema.getOrDefault("description", "");
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
        }

        schema.put("properties", properties);
        if (!required.isEmpty()) {
            schema.put("required", required);
        }

        return schema;
    }

    private String getJsonType(Class<?> type) {
        if (type == String.class) {
            return "string";
        } else if (type == int.class || type == Integer.class ||
                   type == long.class || type == Long.class) {
            return "integer";
        } else if (type == double.class || type == Double.class ||
                   type == float.class || type == Float.class) {
            return "number";
        } else if (type == boolean.class || type == Boolean.class) {
            return "boolean";
        } else if (type.isArray() || List.class.isAssignableFrom(type)) {
            return "array";
        } else {
            return "object";
        }
    }

    /**
     * Metadata about a registered tool.
     *
     * <p>{@code outputType} is the optional return type from {@link MeshTool#outputType()},
     * used for output-schema generation (issue #547). Null when the user did not opt in.
     *
     * <p>{@code outputSchemaStrict} mirrors {@link MeshTool#outputSchemaStrict()} —
     * when false, BLOCK verdicts for this tool are demoted to WARN instead of
     * refusing startup (issue #547 Phase 4).
     */
    public record ToolMetadata(
        String capability,
        String description,
        String version,
        List<String> tags,
        List<DependencyInfo> dependencies,
        Map<String, Object> inputSchema,
        Class<?> outputType,
        boolean outputSchemaStrict,
        Object bean,
        Method method
    ) {}

    /**
     * Information about a tool dependency.
     *
     * <p>{@code expectedType} and {@code schemaMode} carry the issue #547
     * schema-aware matching opt-in from {@link Selector#expectedType()} and
     * {@link Selector#schemaMode()}. {@code expectedType} is null when not set;
     * {@code schemaMode} defaults to {@link SchemaMode#NONE}.
     */
    public record DependencyInfo(
        String capability,
        List<String> tags,
        String version,
        Class<?> expectedType,
        SchemaMode schemaMode
    ) {
        public DependencyInfo(String capability, List<String> tags, String version) {
            this(capability, tags, version, null, SchemaMode.NONE);
        }
    }
}
