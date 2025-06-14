package database

import (
	"encoding/json"
	"time"
)

// Agent represents a process/container with multiple tools
type Agent struct {
	ID                string     `gorm:"primaryKey" json:"id"`
	Name              string     `gorm:"not null" json:"name"`
	Namespace         string     `gorm:"default:'default'" json:"namespace"`
	BaseEndpoint      string     `gorm:"not null" json:"base_endpoint"`
	Status            string     `gorm:"default:'healthy'" json:"status"`
	Transport         string     `gorm:"default:'[\"stdio\"]'" json:"-"`
	LastHeartbeat     *time.Time `json:"last_heartbeat,omitempty"`
	TimeoutThreshold  int        `gorm:"default:60" json:"timeout_threshold"`
	EvictionThreshold int        `gorm:"default:120" json:"eviction_threshold"`
	Labels            string     `gorm:"default:'{}'" json:"-"`
	Metadata          string     `gorm:"default:'{}'" json:"-"`
	Dependencies      string     `gorm:"default:'[]'" json:"-"`
	CreatedAt         time.Time  `json:"created_at"`
	UpdatedAt         time.Time  `json:"updated_at"`

	// Relations
	Tools []Tool `gorm:"foreignKey:AgentID" json:"tools,omitempty"`
}

// GetTransport returns parsed transport array
func (a *Agent) GetTransport() []string {
	var transport []string
	json.Unmarshal([]byte(a.Transport), &transport)
	return transport
}

// SetTransport sets transport as JSON array
func (a *Agent) SetTransport(transport []string) {
	data, _ := json.Marshal(transport)
	a.Transport = string(data)
}

// GetLabels returns parsed labels
func (a *Agent) GetLabels() map[string]string {
	var labels map[string]string
	json.Unmarshal([]byte(a.Labels), &labels)
	return labels
}

// SetLabels sets labels as JSON
func (a *Agent) SetLabels(labels map[string]string) {
	data, _ := json.Marshal(labels)
	a.Labels = string(data)
}

// GetMetadata returns parsed metadata
func (a *Agent) GetMetadata() map[string]interface{} {
	var metadata map[string]interface{}
	json.Unmarshal([]byte(a.Metadata), &metadata)
	return metadata
}

// SetMetadata sets metadata as JSON
func (a *Agent) SetMetadata(metadata map[string]interface{}) {
	data, _ := json.Marshal(metadata)
	a.Metadata = string(data)
}

// GetDependencies returns parsed dependencies
func (a *Agent) GetDependencies() []interface{} {
	var dependencies []interface{}
	json.Unmarshal([]byte(a.Dependencies), &dependencies)
	return dependencies
}

// SetDependencies sets dependencies as JSON
func (a *Agent) SetDependencies(dependencies []interface{}) {
	data, _ := json.Marshal(dependencies)
	a.Dependencies = string(data)
}

// Tool represents an individual function within an agent
type Tool struct {
	ID           uint      `gorm:"primaryKey" json:"id"`
	AgentID      string    `gorm:"not null;index" json:"agent_id"`
	Name         string    `gorm:"not null" json:"name"`
	Capability   string    `gorm:"not null;index" json:"capability"`
	Version      string    `gorm:"default:'1.0.0'" json:"version"`
	Dependencies string    `gorm:"default:'[]'" json:"-"`
	Config       string    `gorm:"default:'{}'" json:"-"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`

	// Relations
	Agent Agent `gorm:"foreignKey:AgentID;references:ID;constraint:OnDelete:CASCADE" json:"-"`
}

// Dependency represents a tool dependency with constraints
type Dependency struct {
	Capability string   `json:"capability"`
	Version    string   `json:"version,omitempty"` // e.g., ">=1.0.0"
	Tags       []string `json:"tags,omitempty"`    // e.g., ["production", "US_EAST"]
}

// GetDependencies returns parsed dependencies
func (t *Tool) GetDependencies() []Dependency {
	var deps []Dependency
	json.Unmarshal([]byte(t.Dependencies), &deps)
	return deps
}

// SetDependencies sets dependencies as JSON
func (t *Tool) SetDependencies(deps []Dependency) {
	data, _ := json.Marshal(deps)
	t.Dependencies = string(data)
}

// ToolConfig represents tool-specific configuration
type ToolConfig struct {
	Description          string                 `json:"description,omitempty"`
	Tags                 []string               `json:"tags,omitempty"`
	Endpoint             string                 `json:"endpoint,omitempty"`
	EnableHTTP           bool                   `json:"enable_http"`
	HTTPHost             string                 `json:"http_host,omitempty"`
	HTTPPort             int                    `json:"http_port,omitempty"`
	HealthInterval       int                    `json:"health_interval"`
	Timeout              int                    `json:"timeout"`
	RetryAttempts        int                    `json:"retry_attempts"`
	EnableCaching        bool                   `json:"enable_caching"`
	FallbackMode         bool                   `json:"fallback_mode"`
	SecurityContext      string                 `json:"security_context,omitempty"`
	PerformanceProfile   map[string]interface{} `json:"performance_profile,omitempty"`
	ResourceRequirements map[string]interface{} `json:"resource_requirements,omitempty"`
	Parameters           map[string]interface{} `json:"parameters,omitempty"`
}

// GetConfig returns parsed config
func (t *Tool) GetConfig() ToolConfig {
	var config ToolConfig
	json.Unmarshal([]byte(t.Config), &config)
	return config
}

// SetConfig sets config as JSON
func (t *Tool) SetConfig(config ToolConfig) {
	data, _ := json.Marshal(config)
	t.Config = string(data)
}

// RegistryEvent represents an audit trail event
type RegistryEvent struct {
	ID        uint      `gorm:"primaryKey" json:"id"`
	EventType string    `gorm:"not null" json:"event_type"`
	AgentID   string    `gorm:"not null;index" json:"agent_id"`
	ToolName  *string   `json:"tool_name,omitempty"`
	Timestamp time.Time `gorm:"index" json:"timestamp"`
	Data      string    `gorm:"default:'{}'" json:"-"`
}

// GetData returns parsed event data
func (e *RegistryEvent) GetData() map[string]interface{} {
	var data map[string]interface{}
	json.Unmarshal([]byte(e.Data), &data)
	return data
}

// SetData sets data as JSON
func (e *RegistryEvent) SetData(data map[string]interface{}) {
	bytes, _ := json.Marshal(data)
	e.Data = string(bytes)
}
