/**
 * Schema post-processing for media-typed tool parameters.
 *
 * Detects the "[media:TYPE]" convention in property descriptions
 * (set by mediaParam() in types.ts) and enriches the JSON Schema
 * with x-media-type annotations for LLM tool discovery.
 */

/**
 * Post-process a JSON Schema to enrich properties that use the
 * [media:TYPE] description convention with x-media-type annotations.
 *
 * Modifies the schema in place.
 *
 * @param schema - JSON Schema object (from zodToJsonSchema)
 */
export function enrichSchemaWithMediaTypes(schema: Record<string, unknown>): void {
    const properties = (schema as Record<string, unknown>)?.properties as
        Record<string, Record<string, unknown>> | undefined;
    if (!properties) return;

    for (const [, prop] of Object.entries(properties)) {
        const desc = prop?.description;
        if (typeof desc === "string") {
            const match = desc.match(/^\[media:([^\]]+)\]\s*/);
            if (match) {
                prop["x-media-type"] = match[1];
                prop.description = desc.replace(/^\[media:[^\]]+\]\s*/, "")
                    + ` (accepts media URI: ${match[1]})`;
            }
        }
    }
}
