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
	},
	"tags": {
		Name:                 "tags",
		Aliases:              []string{"tag-matching"},
		Title:                "Tag Matching System",
		Description:          "Tag system with +/- operators for smart service selection",
		HasTypeScriptVariant: true,
	},
	"decorators": {
		Name:                 "decorators",
		Aliases:              []string{"decorator"},
		Title:                "MCP Mesh Decorators",
		Description:          "Python decorators and TypeScript function wrappers for mesh services",
		HasTypeScriptVariant: true,
	},
	"dependency-injection": {
		Name:                 "dependency-injection",
		Aliases:              []string{"di", "injection"},
		Title:                "Dependency Injection",
		Description:          "How DI works, proxy creation, and automatic wiring",
		HasTypeScriptVariant: true,
	},
	"health": {
		Name:                 "health",
		Aliases:              []string{"health-checks", "heartbeat"},
		Title:                "Health Monitoring & Auto-Rewiring",
		Description:          "Heartbeat system, health checks, and automatic topology updates",
		HasTypeScriptVariant: true,
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
	},
	"proxies": {
		Name:                 "proxies",
		Aliases:              []string{"proxy", "communication"},
		Title:                "Proxy System & Communication",
		Description:          "Inter-agent communication, proxy types, and configuration",
		HasTypeScriptVariant: true,
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
	},
	"testing": {
		Name:                 "testing",
		Aliases:              []string{"curl", "mcp-api"},
		Title:                "Testing MCP Agents",
		Description:          "Testing agents with curl, MCP JSON-RPC syntax",
		HasTypeScriptVariant: true,
	},
	"fastapi": {
		Name:        "fastapi",
		Aliases:     []string{"backend"},
		Title:       "FastAPI Integration",
		Description: "@mesh.route for FastAPI backends consuming mesh capabilities",
	},
	"express": {
		Name:        "express",
		Aliases:     []string{"route", "routes"},
		Title:       "Express Integration",
		Description: "mesh.route() for Express backends consuming mesh capabilities",
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
	"prerequisites": {
		Name:        "prerequisites",
		Aliases:     []string{"prereq", "setup", "install"},
		Title:       "Prerequisites",
		Description: "System requirements for Python and TypeScript development",
	},
	"quickstart": {
		Name:                 "quickstart",
		Aliases:              []string{"quick", "start", "hello"},
		Title:                "Quick Start",
		Description:          "Get started with MCP Mesh in minutes",
		HasTypeScriptVariant: true,
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
	return GetGuideWithVariant(name, false)
}

// GetGuideWithVariant retrieves a guide with optional TypeScript variant.
// If typescript is true and a TypeScript variant exists, it returns that instead.
// For Python pages with TypeScript variants, appends a footer note.
func GetGuideWithVariant(name string, typescript bool) (*Guide, string, error) {
	name = strings.ToLower(strings.TrimSpace(name))

	canonicalName, ok := aliasMap[name]
	if !ok {
		return nil, "", fmt.Errorf("guide '%s' not found", name)
	}

	guide := guideRegistry[canonicalName]

	// Determine which file to load (use HasTypeScriptVariant from Guide struct)
	filename := canonicalName
	if typescript && guide.HasTypeScriptVariant {
		filename = canonicalName + "_typescript"
	}

	// Load content from embedded filesystem
	content, err := guideContent.ReadFile(fmt.Sprintf("content/%s.md", filename))
	if err != nil {
		if typescript {
			// TypeScript variant not found, fall back to default
			content, err = guideContent.ReadFile(fmt.Sprintf("content/%s.md", canonicalName))
			if err != nil {
				return nil, "", fmt.Errorf("failed to load guide content: %w", err)
			}
		} else {
			return nil, "", fmt.Errorf("failed to load guide content: %w", err)
		}
	}

	contentStr := string(content)

	// For Python pages (not TypeScript), append footer if TypeScript variant exists
	if !typescript && guide.HasTypeScriptVariant {
		contentStr += fmt.Sprintf("\n\n---\n\n**See also:** `meshctl man %s --typescript` for TypeScript examples.\n", canonicalName)
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
		"proxies", "fastapi", "express", "environment", "deployment", "observability",
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
		content, err := guideContent.ReadFile(fmt.Sprintf("content/%s.md", name))
		if err != nil {
			continue
		}

		contentStr := string(content)
		if strings.Contains(strings.ToLower(contentStr), query) {
			// Find matching lines
			var matches []string
			lines := strings.Split(contentStr, "\n")
			for _, line := range lines {
				if strings.Contains(strings.ToLower(line), query) {
					matches = append(matches, strings.TrimSpace(line))
					if len(matches) >= 3 { // Limit to 3 matches per guide
						break
					}
				}
			}
			results = append(results, &SearchResult{
				Guide:   guide,
				Matches: matches,
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
