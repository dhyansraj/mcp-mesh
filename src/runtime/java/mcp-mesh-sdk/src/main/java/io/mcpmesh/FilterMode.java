package io.mcpmesh;

/**
 * Modes for filtering available tools in LLM agents.
 *
 * <p>Used with {@link MeshLlm#filterMode()} to control which tools
 * are available to the LLM during agentic loops.
 */
public enum FilterMode {

    /**
     * Include all tools matching any filter.
     *
     * <p>If multiple tools match the same capability, all are included.
     */
    ALL,

    /**
     * One tool per capability (best tag match).
     *
     * <p>If multiple tools match the same capability, only the best
     * match (highest tag score) is included.
     */
    BEST_MATCH,

    /**
     * Include all available tools (ignore filter).
     *
     * <p>All tools from all agents in the mesh are made available.
     */
    WILDCARD
}
