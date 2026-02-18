package man

import (
	"embed"
	"fmt"
	"strings"
)

//go:embed content/*.md
var guideContent embed.FS

// Guide represents a documentation guide topic.
type Guide struct {
	Name                 string
	Aliases              []string
	Title                string
	Description          string
	HasTypeScriptVariant bool // Whether a TypeScript variant page exists
	HasJavaVariant       bool // Whether a Java variant page exists
}

// guideRegistry maps guide names to their metadata.
var guideRegistry = map[string]*Guide{
	"overview": {
		Name:        "overview",
		Aliases:     []string{"architecture", "arch"},
		Title:       "MCP Mesh Architecture",
		Description: "Core architecture, agent coordination, and design philosophy",
	},
	"capabilities": {
		Name:                 "capabilities",
		Aliases:              []string{"caps"},
		Title:                "Capabilities System",
		Description:          "Named services that agents provide",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"tags": {
		Name:                 "tags",
		Aliases:              []string{"tag-matching"},
		Title:                "Tag Matching System",
		Description:          "Tag system with +/- operators for smart service selection",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"decorators": {
		Name:                 "decorators",
		Aliases:              []string{"decorator"},
		Title:                "MCP Mesh Decorators",
		Description:          "Python decorators, TypeScript function wrappers, and Java annotations for mesh services",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"dependency-injection": {
		Name:                 "dependency-injection",
		Aliases:              []string{"di", "injection"},
		Title:                "Dependency Injection",
		Description:          "How DI works, proxy creation, and automatic wiring",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"health": {
		Name:                 "health",
		Aliases:              []string{"health-checks", "heartbeat"},
		Title:                "Health Monitoring & Auto-Rewiring",
		Description:          "Heartbeat system, health checks, and automatic topology updates",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"registry": {
		Name:        "registry",
		Aliases:     []string{"reg"},
		Title:       "Registry Operations",
		Description: "Registry role, agent registration, and dependency resolution",
	},
	"llm": {
		Name:                 "llm",
		Aliases:              []string{"llm-integration"},
		Title:                "LLM Integration",
		Description:          "LLM agents, @mesh.llm decorator, and tool filtering",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"proxies": {
		Name:                 "proxies",
		Aliases:              []string{"proxy", "communication"},
		Title:                "Proxy System & Communication",
		Description:          "Inter-agent communication, proxy types, and configuration",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"environment": {
		Name:        "environment",
		Aliases:     []string{"env", "config"},
		Title:       "Environment Variables",
		Description: "Configuration via environment variables",
	},
	"deployment": {
		Name:                 "deployment",
		Aliases:              []string{"deploy"},
		Title:                "Deployment Patterns",
		Description:          "Local, Docker, and Kubernetes deployment",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"testing": {
		Name:                 "testing",
		Aliases:              []string{"curl", "mcp-api"},
		Title:                "Testing MCP Agents",
		Description:          "Testing agents with curl, MCP JSON-RPC syntax",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"api": {
		Name:                 "api",
		Aliases:              []string{"api-integration", "fastapi", "express", "backend", "route", "routes"},
		Title:                "API Integration",
		Description:          "Add mesh capabilities to existing web frameworks (FastAPI, Express, Spring Boot)",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"scaffold": {
		Name:        "scaffold",
		Aliases:     []string{"scaffolding", "generate", "gen", "new"},
		Title:       "Agent Scaffolding",
		Description: "Generate agents with meshctl scaffold command",
	},
	"cli": {
		Name:        "cli",
		Aliases:     []string{"commands", "call", "list", "status"},
		Title:       "CLI Commands",
		Description: "meshctl call, list, status for development and testing",
	},
	"observability": {
		Name:        "observability",
		Aliases:     []string{"tracing", "monitoring", "tempo", "grafana"},
		Title:       "Observability",
		Description: "Distributed tracing, Grafana dashboards, and monitoring setup",
	},
	"headers": {
		Name:        "headers",
		Aliases:     []string{"header-propagation", "propagation", "forwarding"},
		Title:       "HTTP Header Propagation",
		Description: "Propagate custom HTTP headers across agent calls",
	},
	"prerequisites": {
		Name:                 "prerequisites",
		Aliases:              []string{"prereq", "setup", "install"},
		Title:                "Prerequisites",
		Description:          "System requirements for Python, TypeScript, and Java development",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
	"quickstart": {
		Name:                 "quickstart",
		Aliases:              []string{"quick", "start", "hello"},
		Title:                "Quick Start",
		Description:          "Get started with MCP Mesh in minutes",
		HasTypeScriptVariant: true,
		HasJavaVariant:       true,
	},
}

// aliasMap maps aliases to canonical guide names.
var aliasMap map[string]string

func init() {
	aliasMap = make(map[string]string)
	for name, guide := range guideRegistry {
		aliasMap[name] = name
		for _, alias := range guide.Aliases {
			aliasMap[alias] = name
		}
	}
}

// GetGuide retrieves a guide by name or alias.
func GetGuide(name string) (*Guide, string, error) {
	return GetGuideWithVariant(name, "")
}

// GetGuideWithVariant retrieves a guide with optional language variant.
// variant can be "" (default/Python), "typescript", or "java".
// For pages with variants, inserts cross-language "Also available" links near the top.
func GetGuideWithVariant(name string, variant string) (*Guide, string, error) {
	name = strings.ToLower(strings.TrimSpace(name))

	canonicalName, ok := aliasMap[name]
	if !ok {
		return nil, "", fmt.Errorf("guide '%s' not found", name)
	}

	guide := guideRegistry[canonicalName]

	// Determine which file to load
	filename := canonicalName
	if variant == "typescript" && guide.HasTypeScriptVariant {
		filename = canonicalName + "_typescript"
	} else if variant == "java" && guide.HasJavaVariant {
		filename = canonicalName + "_java"
	}

	// Load content from embedded filesystem
	content, err := guideContent.ReadFile(fmt.Sprintf("content/%s.md", filename))
	if err != nil {
		if variant != "" {
			// Variant not found, fall back to default
			content, err = guideContent.ReadFile(fmt.Sprintf("content/%s.md", canonicalName))
			if err != nil {
				return nil, "", fmt.Errorf("failed to load guide content: %w", err)
			}
		} else {
			return nil, "", fmt.Errorf("failed to load guide content: %w", err)
		}
	}

	contentStr := string(content)

	// If variant was requested but doesn't exist, we loaded default — treat as default
	if variant == "typescript" && !guide.HasTypeScriptVariant {
		variant = ""
	} else if variant == "java" && !guide.HasJavaVariant {
		variant = ""
	}

	// Build cross-language "Also available" header
	var langHeader string
	switch variant {
	case "": // Default (Python) page
		var alts []string
		if guide.HasTypeScriptVariant {
			alts = append(alts, "`--typescript`")
		}
		if guide.HasJavaVariant {
			alts = append(alts, "`--java`")
		}
		if len(alts) > 0 {
			langHeader = "\n\n**Also available:** " + strings.Join(alts, " | ")
		}
	case "typescript":
		var alts []string
		alts = append(alts, fmt.Sprintf("`meshctl man %s` (default)", canonicalName))
		if guide.HasJavaVariant {
			alts = append(alts, "`--java`")
		}
		langHeader = "\n\n**Also available:** " + strings.Join(alts, " | ")
	case "java":
		var alts []string
		alts = append(alts, fmt.Sprintf("`meshctl man %s` (default)", canonicalName))
		if guide.HasTypeScriptVariant {
			alts = append(alts, "`--typescript`")
		}
		langHeader = "\n\n**Also available:** " + strings.Join(alts, " | ")
	}

	// Insert after the blockquote description, before the first ## section
	if langHeader != "" {
		if idx := strings.Index(contentStr, "\n\n## "); idx != -1 {
			contentStr = contentStr[:idx] + langHeader + contentStr[idx:]
		}
	}

	return guide, contentStr, nil
}

// ListGuides returns all available guides sorted by name.
func ListGuides() []*Guide {
	guides := make([]*Guide, 0, len(guideRegistry))
	// Return in a consistent order
	order := []string{
		"quickstart", "prerequisites", "overview", "capabilities", "tags", "decorators",
		"dependency-injection", "health", "registry", "llm",
		"proxies", "api", "environment", "deployment", "observability", "headers",
		"testing", "scaffold", "cli",
	}
	for _, name := range order {
		if guide, ok := guideRegistry[name]; ok {
			guides = append(guides, guide)
		}
	}
	return guides
}

// SearchResult represents a search match in guides.
type SearchResult struct {
	Guide   *Guide
	Matches []string // Lines containing the search term
}

// SearchGuides searches across all guide content for a query string.
func SearchGuides(query string) ([]*SearchResult, error) {
	query = strings.ToLower(query)
	var results []*SearchResult

	for name, guide := range guideRegistry {
		// Collect all files to search for this guide
		files := []string{name}
		if guide.HasTypeScriptVariant {
			files = append(files, name+"_typescript")
		}
		if guide.HasJavaVariant {
			files = append(files, name+"_java")
		}

		var allMatches []string
		found := false
		for _, file := range files {
			content, err := guideContent.ReadFile(fmt.Sprintf("content/%s.md", file))
			if err != nil {
				continue
			}
			contentStr := string(content)
			if strings.Contains(strings.ToLower(contentStr), query) {
				found = true
				lines := strings.Split(contentStr, "\n")
				for _, line := range lines {
					if strings.Contains(strings.ToLower(line), query) {
						allMatches = append(allMatches, strings.TrimSpace(line))
						if len(allMatches) >= 3 {
							break
						}
					}
				}
				if len(allMatches) >= 3 {
					break
				}
			}
		}

		if found {
			results = append(results, &SearchResult{
				Guide:   guide,
				Matches: allMatches,
			})
		}
	}

	return results, nil
}

// SuggestSimilarTopics returns topic suggestions for a failed lookup.
func SuggestSimilarTopics(query string) []string {
	query = strings.ToLower(query)
	var suggestions []string

	for name, guide := range guideRegistry {
		// Check if query is a substring of name or aliases
		if strings.Contains(name, query) {
			suggestions = append(suggestions, name)
			continue
		}
		for _, alias := range guide.Aliases {
			if strings.Contains(alias, query) {
				suggestions = append(suggestions, name)
				break
			}
		}
		// Check if query matches part of description
		if strings.Contains(strings.ToLower(guide.Description), query) {
			suggestions = append(suggestions, name)
		}
	}

	return suggestions
}
