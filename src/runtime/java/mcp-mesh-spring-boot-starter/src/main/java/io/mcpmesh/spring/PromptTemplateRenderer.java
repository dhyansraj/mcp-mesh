package io.mcpmesh.spring;

import freemarker.cache.ClassTemplateLoader;
import freemarker.cache.FileTemplateLoader;
import freemarker.cache.MultiTemplateLoader;
import freemarker.cache.TemplateLoader;
import freemarker.template.Configuration;
import freemarker.template.Template;
import freemarker.template.TemplateException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.io.IOException;
import java.io.StringWriter;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Renders system prompts using FreeMarker templates.
 *
 * <p>Supports three prompt formats:
 * <ul>
 *   <li><b>Inline</b>: Plain text string (returned as-is)</li>
 *   <li><b>File template</b>: {@code file://path/to/template.ftl}</li>
 *   <li><b>Classpath template</b>: {@code classpath://prompts/template.ftl}</li>
 * </ul>
 *
 * <h2>Template Variables</h2>
 * <p>Templates can use FreeMarker variables that are populated from the
 * context parameter specified in {@code @MeshLlm(contextParam = "ctx")}.
 *
 * <h2>Example Template</h2>
 * <pre>{@code
 * You are a ${domain} analysis expert.
 * User expertise level: ${userLevel}
 *
 * <#if focusAreas?has_content>
 * Focus your analysis on: ${focusAreas?join(", ")}
 * </#if>
 *
 * You have access to system tools. Use up to ${maxTools} tools.
 * }</pre>
 *
 * @see io.mcpmesh.MeshLlm
 */
public class PromptTemplateRenderer {

    private static final Logger log = LoggerFactory.getLogger(PromptTemplateRenderer.class);

    private static final String FILE_PREFIX = "file://";
    private static final String FILE_PREFIX_SHORT = "file:";
    private static final String CLASSPATH_PREFIX = "classpath://";
    private static final String CLASSPATH_PREFIX_SHORT = "classpath:";

    // FreeMarker configuration (lazily initialized)
    private volatile Configuration freemarkerConfig;

    // Template cache (path -> compiled Template)
    private final Map<String, Template> templateCache = new ConcurrentHashMap<>();

    /**
     * Check if the prompt is a template reference (file:// or classpath://).
     *
     * <p>Supports both full and short prefixes:
     * <ul>
     *   <li>{@code file://path} or {@code file:path}</li>
     *   <li>{@code classpath://path} or {@code classpath:path}</li>
     * </ul>
     *
     * @param prompt The system prompt string
     * @return true if it's a template reference
     */
    public boolean isTemplate(String prompt) {
        if (prompt == null || prompt.isEmpty()) {
            return false;
        }
        return prompt.startsWith(FILE_PREFIX) || prompt.startsWith(FILE_PREFIX_SHORT) ||
               prompt.startsWith(CLASSPATH_PREFIX) || prompt.startsWith(CLASSPATH_PREFIX_SHORT);
    }

    /**
     * Render a system prompt with the given context.
     *
     * <p>If the prompt is a template reference, loads and renders it.
     * Otherwise returns the prompt as-is (treating inline variables with FreeMarker).
     *
     * @param prompt  The system prompt (inline text, file://, or classpath://)
     * @param context Context variables for template rendering (can be null)
     * @return The rendered prompt
     */
    public String render(String prompt, Map<String, Object> context) {
        if (prompt == null || prompt.isEmpty()) {
            return "";
        }

        // If it's a template reference, load and render
        if (prompt.startsWith(FILE_PREFIX)) {
            String path = prompt.substring(FILE_PREFIX.length());
            return renderFileTemplate(path, context);
        }
        if (prompt.startsWith(FILE_PREFIX_SHORT)) {
            String path = prompt.substring(FILE_PREFIX_SHORT.length());
            return renderFileTemplate(path, context);
        }

        if (prompt.startsWith(CLASSPATH_PREFIX)) {
            String path = prompt.substring(CLASSPATH_PREFIX.length());
            return renderClasspathTemplate(path, context);
        }
        if (prompt.startsWith(CLASSPATH_PREFIX_SHORT)) {
            String path = prompt.substring(CLASSPATH_PREFIX_SHORT.length());
            return renderClasspathTemplate(path, context);
        }

        // Check if inline prompt has FreeMarker syntax
        if (containsFreeMarkerSyntax(prompt)) {
            return renderInlineTemplate(prompt, context);
        }

        // Plain text - return as-is
        return prompt;
    }

    /**
     * Check if the prompt contains FreeMarker syntax.
     */
    private boolean containsFreeMarkerSyntax(String prompt) {
        return prompt.contains("${") || prompt.contains("<#");
    }

    /**
     * Render a template from the file system.
     */
    private String renderFileTemplate(String path, Map<String, Object> context) {
        try {
            Template template = getOrLoadFileTemplate(path);
            return processTemplate(template, context);
        } catch (Exception e) {
            log.error("Failed to render file template '{}': {}", path, e.getMessage());
            throw new RuntimeException("Template rendering failed: " + path, e);
        }
    }

    /**
     * Render a template from the classpath.
     */
    private String renderClasspathTemplate(String path, Map<String, Object> context) {
        try {
            Template template = getOrLoadClasspathTemplate(path);
            return processTemplate(template, context);
        } catch (Exception e) {
            log.error("Failed to render classpath template '{}': {}", path, e.getMessage());
            throw new RuntimeException("Template rendering failed: classpath://" + path, e);
        }
    }

    /**
     * Render an inline template string.
     */
    private String renderInlineTemplate(String templateStr, Map<String, Object> context) {
        try {
            // Check cache first
            String cacheKey = "inline:" + templateStr.hashCode();
            Template template = templateCache.get(cacheKey);

            if (template == null) {
                template = new Template("inline", templateStr, getConfiguration());
                templateCache.put(cacheKey, template);
            }

            return processTemplate(template, context);
        } catch (Exception e) {
            log.warn("Failed to render inline template, returning as-is: {}", e.getMessage());
            return templateStr;
        }
    }

    /**
     * Get or load a file template.
     */
    private Template getOrLoadFileTemplate(String path) throws IOException {
        String cacheKey = "file:" + path;
        Template template = templateCache.get(cacheKey);

        if (template == null) {
            File file = new File(path);
            if (!file.exists()) {
                throw new IOException("Template file not found: " + path);
            }

            Configuration cfg = getConfiguration();
            FileTemplateLoader loader = new FileTemplateLoader(file.getParentFile());
            cfg.setTemplateLoader(loader);

            template = cfg.getTemplate(file.getName());
            templateCache.put(cacheKey, template);
            log.debug("Loaded file template: {}", path);
        }

        return template;
    }

    /**
     * Get or load a classpath template.
     */
    private Template getOrLoadClasspathTemplate(String path) throws IOException {
        String cacheKey = "classpath:" + path;
        Template template = templateCache.get(cacheKey);

        if (template == null) {
            Configuration cfg = getConfiguration();

            // Determine the base path and template name
            int lastSlash = path.lastIndexOf('/');
            String basePath = lastSlash > 0 ? "/" + path.substring(0, lastSlash) : "/";
            String templateName = lastSlash > 0 ? path.substring(lastSlash + 1) : path;

            ClassTemplateLoader loader = new ClassTemplateLoader(getClass(), basePath);
            cfg.setTemplateLoader(loader);

            template = cfg.getTemplate(templateName);
            templateCache.put(cacheKey, template);
            log.debug("Loaded classpath template: {}", path);
        }

        return template;
    }

    /**
     * Process a template with the given context.
     */
    private String processTemplate(Template template, Map<String, Object> context) throws IOException, TemplateException {
        StringWriter writer = new StringWriter();
        template.process(context != null ? context : Map.of(), writer);
        return writer.toString();
    }

    /**
     * Get or create the FreeMarker configuration.
     */
    private Configuration getConfiguration() {
        if (freemarkerConfig == null) {
            synchronized (this) {
                if (freemarkerConfig == null) {
                    Configuration cfg = new Configuration(Configuration.VERSION_2_3_32);
                    cfg.setDefaultEncoding("UTF-8");
                    cfg.setLogTemplateExceptions(false);
                    cfg.setWrapUncheckedExceptions(true);
                    cfg.setFallbackOnNullLoopVariable(false);

                    // Set up multi-loader for both classpath and file system
                    try {
                        TemplateLoader[] loaders = new TemplateLoader[] {
                            new ClassTemplateLoader(getClass(), "/"),
                            new FileTemplateLoader(new File("."))
                        };
                        cfg.setTemplateLoader(new MultiTemplateLoader(loaders));
                    } catch (IOException e) {
                        log.warn("Failed to set up file template loader: {}", e.getMessage());
                        cfg.setClassLoaderForTemplateLoading(getClass().getClassLoader(), "/");
                    }

                    freemarkerConfig = cfg;
                }
            }
        }
        return freemarkerConfig;
    }

    /**
     * Clear the template cache.
     * Useful for development/testing when templates change.
     */
    public void clearCache() {
        templateCache.clear();
        log.debug("Template cache cleared");
    }
}
