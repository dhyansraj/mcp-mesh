package io.mcpmesh.spring;

import freemarker.template.Configuration;
import freemarker.template.Template;
import freemarker.template.TemplateExceptionHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

/**
 * Loads and processes Freemarker templates for system prompts.
 *
 * <p>Supports multiple source types:
 * <ul>
 *   <li>Inline strings (plain text)</li>
 *   <li>{@code file://path/to/template.ftl} - File system templates</li>
 *   <li>{@code classpath://prompts/template.ftl} - Classpath resources</li>
 * </ul>
 *
 * <h2>Template Syntax</h2>
 * <p>Uses Freemarker syntax. Example:
 * <pre>
 * You are an AI assistant.
 *
 * ## Query
 * ${query}
 *
 * &lt;#if parameters?has_content&gt;
 * ## Parameters
 * &lt;#list parameters?keys as key&gt;
 * - ${key}: ${parameters[key]}
 * &lt;/#list&gt;
 * &lt;/#if&gt;
 * </pre>
 */
@Component
public class PromptTemplateLoader {

    private static final Logger log = LoggerFactory.getLogger(PromptTemplateLoader.class);
    private static final String FILE_PREFIX = "file://";
    private static final String CLASSPATH_PREFIX = "classpath://";

    private final Configuration freemarkerConfig;

    public PromptTemplateLoader() {
        this.freemarkerConfig = new Configuration(Configuration.VERSION_2_3_32);
        this.freemarkerConfig.setDefaultEncoding("UTF-8");
        this.freemarkerConfig.setTemplateExceptionHandler(TemplateExceptionHandler.RETHROW_HANDLER);
        this.freemarkerConfig.setLogTemplateExceptions(false);
        this.freemarkerConfig.setWrapUncheckedExceptions(true);
        this.freemarkerConfig.setFallbackOnNullLoopVariable(false);
    }

    /**
     * Load and process a prompt template.
     *
     * @param templateSpec The template specification (inline, file://, or classpath://)
     * @param context      Variables to inject into the template
     * @return The processed prompt string
     */
    public String loadAndProcess(String templateSpec, Map<String, Object> context) {
        if (templateSpec == null || templateSpec.isBlank()) {
            return "";
        }

        String templateContent = loadTemplate(templateSpec);
        return processTemplate(templateContent, context);
    }

    /**
     * Load a template from the specified source.
     *
     * @param templateSpec The template specification
     * @return The raw template content
     */
    public String loadTemplate(String templateSpec) {
        if (templateSpec == null || templateSpec.isBlank()) {
            return "";
        }

        // File system template
        if (templateSpec.startsWith(FILE_PREFIX)) {
            String path = templateSpec.substring(FILE_PREFIX.length());
            return loadFromFile(path);
        }

        // Classpath resource
        if (templateSpec.startsWith(CLASSPATH_PREFIX)) {
            String path = templateSpec.substring(CLASSPATH_PREFIX.length());
            return loadFromClasspath(path);
        }

        // Inline template (plain string)
        return templateSpec;
    }

    /**
     * Process a template string with the given context.
     *
     * @param templateContent The template content
     * @param context         Variables to inject
     * @return The processed string
     */
    public String processTemplate(String templateContent, Map<String, Object> context) {
        if (templateContent == null || templateContent.isBlank()) {
            return "";
        }

        // If no Freemarker directives, return as-is
        if (!containsFreemarkerDirectives(templateContent)) {
            return templateContent;
        }

        try {
            Template template = new Template("prompt",
                new StringReader(templateContent), freemarkerConfig);

            StringWriter writer = new StringWriter();
            template.process(context, writer);
            return writer.toString();
        } catch (Exception e) {
            log.error("Failed to process Freemarker template: {}", e.getMessage());
            throw new RuntimeException("Template processing failed", e);
        }
    }

    private String loadFromFile(String path) {
        try {
            Path filePath = Path.of(path);
            if (!Files.exists(filePath)) {
                throw new FileNotFoundException("Template file not found: " + path);
            }
            return Files.readString(filePath, StandardCharsets.UTF_8);
        } catch (IOException e) {
            log.error("Failed to load template from file {}: {}", path, e.getMessage());
            throw new RuntimeException("Failed to load template file: " + path, e);
        }
    }

    private String loadFromClasspath(String path) {
        try {
            // Remove leading slash if present
            String resourcePath = path.startsWith("/") ? path.substring(1) : path;
            ClassPathResource resource = new ClassPathResource(resourcePath);

            if (!resource.exists()) {
                throw new FileNotFoundException("Classpath resource not found: " + path);
            }

            try (InputStream is = resource.getInputStream();
                 BufferedReader reader = new BufferedReader(
                     new InputStreamReader(is, StandardCharsets.UTF_8))) {

                StringBuilder sb = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    sb.append(line).append("\n");
                }
                return sb.toString();
            }
        } catch (IOException e) {
            log.error("Failed to load template from classpath {}: {}", path, e.getMessage());
            throw new RuntimeException("Failed to load classpath template: " + path, e);
        }
    }

    private boolean containsFreemarkerDirectives(String content) {
        // Check for common Freemarker markers
        return content.contains("${") ||
               content.contains("<#") ||
               content.contains("<@") ||
               content.contains("[#") ||
               content.contains("[@");
    }
}
