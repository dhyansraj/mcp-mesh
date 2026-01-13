/**
 * Template rendering for LLM system prompts using Handlebars.
 *
 * Supports both inline templates and file-based templates using the `file://` prefix.
 * Handlebars was chosen for its popularity in the TypeScript/JavaScript ecosystem.
 *
 * @example
 * ```typescript
 * // Inline template
 * const rendered = await renderTemplate(
 *   "Hello, {{name}}! You have {{count}} items.",
 *   { name: "User", count: 5 }
 * );
 *
 * // File-based template
 * const rendered = await renderTemplate(
 *   "file://prompts/assistant.hbs",
 *   { user: "John", context: { topic: "math" } }
 * );
 * ```
 */

import Handlebars from "handlebars";
import * as fs from "fs/promises";
import * as path from "path";

/**
 * Cache for compiled Handlebars templates.
 * Key is the template string (for inline) or resolved file path (for file://).
 */
const templateCache = new Map<string, HandlebarsTemplateDelegate>();

/**
 * Check if a template string is a file reference.
 */
export function isFileTemplate(template: string): boolean {
  return template.startsWith("file://");
}

/**
 * Extract the file path from a file:// template reference.
 */
export function extractFilePath(template: string): string {
  if (!isFileTemplate(template)) {
    throw new Error(`Not a file template: ${template}`);
  }
  return template.slice(7); // Remove "file://" prefix
}

/**
 * Resolve a file path relative to the caller's location.
 * If the path is absolute, it's returned as-is.
 * If relative, it's resolved from the current working directory.
 */
function resolveTemplatePath(filePath: string): string {
  if (path.isAbsolute(filePath)) {
    return filePath;
  }
  return path.resolve(process.cwd(), filePath);
}

/**
 * Load a template file and return its contents.
 */
async function loadTemplateFile(filePath: string): Promise<string> {
  const resolvedPath = resolveTemplatePath(filePath);
  try {
    return await fs.readFile(resolvedPath, "utf-8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error(`Template file not found: ${resolvedPath}`);
    }
    throw err;
  }
}

/**
 * Get or compile a Handlebars template.
 * Templates are cached by their source (inline string or resolved absolute file path).
 */
async function getCompiledTemplate(
  template: string
): Promise<HandlebarsTemplateDelegate> {
  // Determine cache key - use absolute path for file templates
  let cacheKey: string;
  let templateContent: string;

  if (isFileTemplate(template)) {
    const filePath = extractFilePath(template);
    const absolutePath = resolveTemplatePath(filePath);
    cacheKey = absolutePath; // Use absolute path as cache key

    // Check cache first
    const cached = templateCache.get(cacheKey);
    if (cached) {
      return cached;
    }

    templateContent = await loadTemplateFile(filePath);
  } else {
    cacheKey = template; // Use inline template as cache key

    // Check cache first
    const cached = templateCache.get(cacheKey);
    if (cached) {
      return cached;
    }

    templateContent = template;
  }

  // Compile and cache
  const compiled = Handlebars.compile(templateContent);
  templateCache.set(cacheKey, compiled);

  return compiled;
}

/**
 * Render a template with the given context.
 *
 * @param template - Template string (inline) or file reference ("file://path/to/template.hbs")
 * @param context - Context object for template variables
 * @returns Rendered string
 *
 * @example
 * ```typescript
 * // Inline template
 * const result = await renderTemplate("Hello {{name}}!", { name: "World" });
 * // => "Hello World!"
 *
 * // File template (prompts/assistant.hbs)
 * const result = await renderTemplate("file://prompts/assistant.hbs", {
 *   user: { name: "John" },
 *   preferences: ["math", "science"],
 * });
 * ```
 */
export async function renderTemplate(
  template: string,
  context: Record<string, unknown> = {}
): Promise<string> {
  const compiled = await getCompiledTemplate(template);
  return compiled(context);
}

/**
 * Clear the template cache.
 * Useful for development/testing when templates are being modified.
 */
export function clearTemplateCache(): void {
  templateCache.clear();
}

/**
 * Register a custom Handlebars helper.
 *
 * @param name - Helper name
 * @param fn - Helper function
 *
 * @example
 * ```typescript
 * registerHelper("uppercase", (str) => str.toUpperCase());
 * // Template: "Hello {{uppercase name}}!"
 * // Context: { name: "world" }
 * // Result: "Hello WORLD!"
 * ```
 */
export function registerHelper(
  name: string,
  fn: Handlebars.HelperDelegate
): void {
  Handlebars.registerHelper(name, fn);
}

/**
 * Register a partial template.
 *
 * @param name - Partial name
 * @param template - Template string
 *
 * @example
 * ```typescript
 * registerPartial("header", "<h1>{{title}}</h1>");
 * // Template: "{{> header title='Welcome'}}"
 * // Result: "<h1>Welcome</h1>"
 * ```
 */
export function registerPartial(name: string, template: string): void {
  Handlebars.registerPartial(name, template);
}

// Register common helpers

/**
 * JSON helper - stringify an object
 * Usage: {{json data}}
 */
registerHelper("json", (context: unknown) => {
  return JSON.stringify(context, null, 2);
});

/**
 * Join helper - join array elements
 * Usage: {{join items ", "}}
 */
registerHelper("join", (items: unknown[], separator: string) => {
  if (!Array.isArray(items)) return "";
  return items.join(typeof separator === "string" ? separator : ", ");
});

/**
 * Eq helper - equality check
 * Usage: {{#if (eq a b)}}...{{/if}}
 */
registerHelper("eq", (a: unknown, b: unknown) => {
  return a === b;
});

/**
 * Ne helper - not equal check
 * Usage: {{#if (ne a b)}}...{{/if}}
 */
registerHelper("ne", (a: unknown, b: unknown) => {
  return a !== b;
});

/**
 * Default helper - provide default value
 * Usage: {{default value "fallback"}}
 */
registerHelper("default", (value: unknown, defaultValue: unknown) => {
  return value ?? defaultValue;
});
