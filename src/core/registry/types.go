package registry

// AgentQueryParams holds parameters for agent discovery queries
// MUST match Python ServiceDiscoveryQuery exactly
type AgentQueryParams struct {
	Namespace           string            `form:"namespace"`
	Status              string            `form:"status"`
	Capability          string            `form:"capability"`
	Capabilities        []string          `form:"capabilities"`
	CapabilityCategory  string            `form:"capability_category"`
	CapabilityStability string            `form:"capability_stability"`
	CapabilityTags      []string          `form:"capability_tags"`
	LabelSelector       map[string]string `form:"label_selector"`
	FuzzyMatch          bool              `form:"fuzzy_match"`
	VersionConstraint   string            `form:"version_constraint"`
}

// CapabilityQueryParams holds parameters for capability search queries
// MUST match Python CapabilitySearchQuery exactly
type CapabilityQueryParams struct {
	AgentID            string   `form:"agent_id"`
	Name               string   `form:"name"`
	DescriptionContains string  `form:"description_contains"`
	Category           string   `form:"category"`
	Tags               []string `form:"tags"`
	Stability          string   `form:"stability"`
	VersionConstraint  string   `form:"version_constraint"`
	FuzzyMatch         bool     `form:"fuzzy_match"`
	IncludeDeprecated  bool     `form:"include_deprecated"`
	AgentNamespace     string   `form:"agent_namespace"`
	AgentStatus        string   `form:"agent_status"`
}

// ErrorResponse represents API error responses matching Python FastAPI format
type ErrorResponse struct {
	Detail string `json:"detail"`
}

// ServiceInfo represents the root endpoint response
type ServiceInfo struct {
	Service      string                 `json:"service"`
	Version      string                 `json:"version"`
	Endpoints    map[string]string      `json:"endpoints"`
	Features     map[string]string      `json:"features"`
	Architecture string                 `json:"architecture"`
	Description  string                 `json:"description"`
}
