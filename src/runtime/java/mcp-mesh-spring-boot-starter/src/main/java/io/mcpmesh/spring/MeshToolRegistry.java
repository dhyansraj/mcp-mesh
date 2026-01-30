package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.core.AgentSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

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

        ToolMetadata metadata = new ToolMetadata(
            capability,
            annotation.description(),
            annotation.version(),
            Arrays.asList(annotation.tags()),
            extractDependencies(annotation.dependencies()),
            extractInputSchema(method),
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
        var objectMapper = new com.fasterxml.jackson.databind.ObjectMapper();

        for (ToolMetadata meta : tools.values()) {
            AgentSpec.ToolSpec spec = new AgentSpec.ToolSpec();
            spec.setFunctionName(meta.method().getName());
            spec.setCapability(meta.capability());
            spec.setDescription(meta.description());
            spec.setVersion(meta.version());
            spec.setTags(meta.tags());

            // Convert input schema Map to JSON string
            try {
                spec.setInputSchema(objectMapper.writeValueAsString(meta.inputSchema()));
            } catch (Exception e) {
                spec.setInputSchema("{}");
            }

            // Add dependencies to the tool spec
            for (DependencyInfo dep : meta.dependencies()) {
                AgentSpec.DependencySpec depSpec = new AgentSpec.DependencySpec();
                depSpec.setCapability(dep.capability());
                try {
                    depSpec.setTags(objectMapper.writeValueAsString(dep.tags()));
                } catch (Exception e) {
                    depSpec.setTags("[]");
                }
                depSpec.setVersion(dep.version());
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

        for (ToolMetadata meta : tools.values()) {
            for (DependencyInfo dep : meta.dependencies()) {
                AgentSpec.DependencySpec spec = new AgentSpec.DependencySpec();
                spec.setCapability(dep.capability());
                // Convert List<String> to JSON array string
                try {
                    spec.setTags(new com.fasterxml.jackson.databind.ObjectMapper()
                        .writeValueAsString(dep.tags()));
                } catch (Exception e) {
                    spec.setTags("[]");
                }
                spec.setVersion(dep.version());
                deps.add(spec);
            }
        }

        return deps;
    }

    private List<DependencyInfo> extractDependencies(Selector[] selectors) {
        List<DependencyInfo> deps = new ArrayList<>();
        for (Selector sel : selectors) {
            if (!sel.capability().isEmpty()) {
                deps.add(new DependencyInfo(
                    sel.capability(),
                    Arrays.asList(sel.tags()),
                    sel.version()
                ));
            }
        }
        return deps;
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
     */
    public record ToolMetadata(
        String capability,
        String description,
        String version,
        List<String> tags,
        List<DependencyInfo> dependencies,
        Map<String, Object> inputSchema,
        Object bean,
        Method method
    ) {}

    /**
     * Information about a tool dependency.
     */
    public record DependencyInfo(
        String capability,
        List<String> tags,
        String version
    ) {}
}
