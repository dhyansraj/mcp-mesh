package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/spf13/cobra"
)

// CLIConfig represents the CLI configuration structure
// MUST match Python CLI configuration behavior exactly
type CLIConfig struct {
	// Registry settings
	RegistryPort int    `json:"registry_port"` // default: 8000
	RegistryHost string `json:"registry_host"` // default: "localhost"

	// Database settings
	DBPath string `json:"db_path"` // default: "./dev_registry.db"

	// Logging settings
	LogLevel string `json:"log_level"` // default: "INFO"

	// Health monitoring
	HealthCheckInterval int `json:"health_check_interval"` // default: 10

	// Development settings
	DebugMode bool `json:"debug_mode"` // default: false

	// Timeout settings
	StartupTimeout  int `json:"startup_timeout"`  // default: 30
	ShutdownTimeout int `json:"shutdown_timeout"` // default: 30

	// Detached service settings
	EnableBackground bool   `json:"enable_background"` // default: false (detached mode)
	PIDFile          string `json:"pid_file"`          // default: "./mcp_mesh_dev.pid"

	// State management
	StateDir string `json:"state_dir"` // default: "~/.mcp_mesh"

	// Configuration metadata
	Version      string    `json:"version"`       // Configuration version for migration
	LastModified time.Time `json:"last_modified"` // Last modification timestamp

	// Thread safety
	mu sync.RWMutex `json:"-"`
}

// ConfigVersion represents the current configuration schema version
const ConfigVersion = "1.0.0"

// DefaultConfig returns the default configuration
// MUST match Python CLI default values exactly
func DefaultConfig() *CLIConfig {
	homeDir, _ := os.UserHomeDir()
	stateDir := filepath.Join(homeDir, ".mcp_mesh")

	return &CLIConfig{
		RegistryPort:        8000,
		RegistryHost:        "localhost",
		DBPath:              "mcp_mesh_registry.db",
		LogLevel:            "INFO",
		HealthCheckInterval: 10,
		DebugMode:           false,
		StartupTimeout:      30,
		ShutdownTimeout:     30,
		EnableBackground:    false,
		PIDFile:             "./mcp_mesh_dev.pid",
		StateDir:            stateDir,
		Version:             ConfigVersion,
		LastModified:        time.Now(),
	}
}

// LoadConfig loads configuration with proper precedence: CLI flags > Environment vars > Defaults
func LoadConfig() (*CLIConfig, error) {
	// Start with default values
	config := DefaultConfig()

	// 1. Load from environment variables (MCP_MESH_ prefix)
	loadFromEnvironment(config)

	// 2. Validate configuration
	if err := config.Validate(); err != nil {
		return nil, fmt.Errorf("configuration validation failed: %w", err)
	}

	// 3. Migrate configuration if needed
	if err := config.Migrate(); err != nil {
		return nil, fmt.Errorf("configuration migration failed: %w", err)
	}

	return config, nil
}

// loadFromEnvironment loads configuration from environment variables
// MUST match Python environment variable handling exactly
func loadFromEnvironment(config *CLIConfig) {
	config.mu.Lock()
	defer config.mu.Unlock()

	// Registry settings
	if val := os.Getenv("MCP_MESH_REGISTRY_PORT"); val != "" {
		if port, err := strconv.Atoi(val); err == nil && port > 0 && port <= 65535 {
			config.RegistryPort = port
		}
	}

	if val := os.Getenv("MCP_MESH_REGISTRY_HOST"); val != "" {
		config.RegistryHost = val
	}

	// Database settings
	if val := os.Getenv("MCP_MESH_DB_PATH"); val != "" {
		config.DBPath = val
	}

	// Logging settings
	if val := os.Getenv("MCP_MESH_LOG_LEVEL"); val != "" {
		config.LogLevel = strings.ToUpper(val)
	}

	// Health monitoring
	if val := os.Getenv("MCP_MESH_HEALTH_CHECK_INTERVAL"); val != "" {
		if interval, err := strconv.Atoi(val); err == nil && interval > 0 {
			config.HealthCheckInterval = interval
		}
	}

	// Development settings
	if val := os.Getenv("MCP_MESH_DEBUG_MODE"); val != "" {
		config.DebugMode = parseBoolEnv(val)
	}

	// Timeout settings
	if val := os.Getenv("MCP_MESH_STARTUP_TIMEOUT"); val != "" {
		if timeout, err := strconv.Atoi(val); err == nil && timeout > 0 {
			config.StartupTimeout = timeout
		}
	}

	if val := os.Getenv("MCP_MESH_SHUTDOWN_TIMEOUT"); val != "" {
		if timeout, err := strconv.Atoi(val); err == nil && timeout > 0 {
			config.ShutdownTimeout = timeout
		}
	}

	// Background service settings
	if val := os.Getenv("MCP_MESH_ENABLE_BACKGROUND"); val != "" {
		config.EnableBackground = parseBoolEnv(val)
	}

	if val := os.Getenv("MCP_MESH_PID_FILE"); val != "" {
		config.PIDFile = val
	}
}

// parseBoolEnv parses boolean values from environment variables
// MUST match Python boolean parsing behavior
func parseBoolEnv(val string) bool {
	switch strings.ToLower(strings.TrimSpace(val)) {
	case "true", "1", "yes", "on", "t", "y":
		return true
	case "false", "0", "no", "off", "f", "n":
		return false
	default:
		return false
	}
}

// getConfigFilePath returns the configuration file path with cross-platform support
// MUST match Python config file path handling exactly
func getConfigFilePath() string {
	var configDir string

	// Cross-platform configuration directory handling
	switch runtime.GOOS {
	case "windows":
		// Windows: Use APPDATA or fallback to user home
		if appData := os.Getenv("APPDATA"); appData != "" {
			configDir = filepath.Join(appData, "mcp_mesh")
		} else if homeDir, err := os.UserHomeDir(); err == nil {
			configDir = filepath.Join(homeDir, ".mcp_mesh")
		} else {
			return ".\\cli_config.json"
		}
	case "darwin":
		// macOS: Use ~/Library/Application Support
		if homeDir, err := os.UserHomeDir(); err == nil {
			configDir = filepath.Join(homeDir, "Library", "Application Support", "mcp_mesh")
		} else {
			return "./cli_config.json"
		}
	default:
		// Linux and other Unix-like systems: Use XDG_CONFIG_HOME or ~/.config
		if xdgConfig := os.Getenv("XDG_CONFIG_HOME"); xdgConfig != "" {
			configDir = filepath.Join(xdgConfig, "mcp_mesh")
		} else if homeDir, err := os.UserHomeDir(); err == nil {
			configDir = filepath.Join(homeDir, ".config", "mcp_mesh")
		} else {
			return "./cli_config.json"
		}
	}

	// Ensure config directory exists with proper permissions
	if err := os.MkdirAll(configDir, 0755); err != nil {
		// Fallback to current directory with OS-specific filename
		if runtime.GOOS == "windows" {
			return ".\\cli_config.json"
		}
		return "./cli_config.json"
	}

	return filepath.Join(configDir, "cli_config.json")
}

// IsValidConfigPath checks if a configuration path is valid and accessible
func IsValidConfigPath(path string) error {
	// Check if path is absolute or relative
	if !filepath.IsAbs(path) {
		return fmt.Errorf("configuration path must be absolute: %s", path)
	}

	// Check directory permissions
	dir := filepath.Dir(path)
	if info, err := os.Stat(dir); err != nil {
		if os.IsNotExist(err) {
			return fmt.Errorf("configuration directory does not exist: %s", dir)
		}
		return fmt.Errorf("cannot access configuration directory %s: %w", dir, err)
	} else if !info.IsDir() {
		return fmt.Errorf("configuration path is not a directory: %s", dir)
	}

	// Check write permissions by creating a temporary file
	tempFile := filepath.Join(dir, ".config_test_"+fmt.Sprintf("%d", time.Now().UnixNano()))
	if err := os.WriteFile(tempFile, []byte("test"), 0644); err != nil {
		return fmt.Errorf("no write permission in configuration directory %s: %w", dir, err)
	}
	os.Remove(tempFile) // Cleanup

	return nil
}

// GetPlatformDefaults returns platform-specific default values
func GetPlatformDefaults() map[string]interface{} {
	defaults := make(map[string]interface{})

	switch runtime.GOOS {
	case "windows":
		defaults["pid_file"] = ".\\mcp_mesh_dev.pid"
		defaults["db_path"] = "mcp_mesh_registry.db"
	default:
		defaults["pid_file"] = "./mcp_mesh_dev.pid"
		defaults["db_path"] = "mcp_mesh_registry.db"
	}

	return defaults
}

// NormalizePath normalizes file paths for the current platform
func NormalizePath(path string) string {
	// Convert path separators to platform-specific format
	normalized := filepath.FromSlash(path)

	// Clean the path to remove redundant elements
	normalized = filepath.Clean(normalized)

	return normalized
}

// EnsureDirectoryExists creates a directory if it doesn't exist with proper permissions
func EnsureDirectoryExists(dir string) error {
	if info, err := os.Stat(dir); err != nil {
		if os.IsNotExist(err) {
			// Create directory with appropriate permissions
			perm := os.FileMode(0755)
			if runtime.GOOS == "windows" {
				// Windows doesn't use Unix permissions in the same way
				perm = os.FileMode(0777)
			}
			if err := os.MkdirAll(dir, perm); err != nil {
				return fmt.Errorf("failed to create directory %s: %w", dir, err)
			}
		} else {
			return fmt.Errorf("failed to access directory %s: %w", dir, err)
		}
	} else if !info.IsDir() {
		return fmt.Errorf("path exists but is not a directory: %s", dir)
	}

	return nil
}

// SecureConfigPermissions sets secure permissions on configuration files
func SecureConfigPermissions(path string) error {
	// Set restrictive permissions on configuration files
	perm := os.FileMode(0600) // Read/write for owner only
	if runtime.GOOS == "windows" {
		// Windows has different permission handling
		perm = os.FileMode(0644)
	}

	if err := os.Chmod(path, perm); err != nil {
		return fmt.Errorf("failed to set secure permissions on %s: %w", path, err)
	}

	return nil
}

// ValidateEnvironmentVariable validates an environment variable value
func ValidateEnvironmentVariable(key, value string) error {
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("environment variable %s cannot be empty", key)
	}

	switch key {
	case "MCP_MESH_REGISTRY_PORT":
		if port, err := strconv.Atoi(value); err != nil || port < 1 || port > 65535 {
			return fmt.Errorf("invalid port in %s: %s (must be 1-65535)", key, value)
		}
	case "MCP_MESH_HEALTH_CHECK_INTERVAL", "MCP_MESH_STARTUP_TIMEOUT", "MCP_MESH_SHUTDOWN_TIMEOUT":
		if interval, err := strconv.Atoi(value); err != nil || interval < 1 {
			return fmt.Errorf("invalid interval in %s: %s (must be positive integer)", key, value)
		}
	case "MCP_MESH_LOG_LEVEL":
		validLevels := []string{"DEBUG", "INFO", "WARN", "ERROR", "FATAL"}
		valid := false
		for _, level := range validLevels {
			if strings.ToUpper(value) == level {
				valid = true
				break
			}
		}
		if !valid {
			return fmt.Errorf("invalid log level in %s: %s (must be one of: %s)", key, value, strings.Join(validLevels, ", "))
		}
	}

	return nil
}

// GetConfigurationSummary returns a summary of current configuration for display
func (c *CLIConfig) GetConfigurationSummary() map[string]interface{} {
	c.mu.RLock()
	defer c.mu.RUnlock()

	return map[string]interface{}{
		"registry": map[string]interface{}{
			"host": c.RegistryHost,
			"port": c.RegistryPort,
			"url":  fmt.Sprintf("http://%s:%d", c.RegistryHost, c.RegistryPort),
		},
		"database": map[string]interface{}{
			"path": c.DBPath,
		},
		"logging": map[string]interface{}{
			"level": c.LogLevel,
		},
		"monitoring": map[string]interface{}{
			"health_check_interval": c.HealthCheckInterval,
		},
		"development": map[string]interface{}{
			"debug_mode": c.DebugMode,
		},
		"timeouts": map[string]interface{}{
			"startup":  c.StartupTimeout,
			"shutdown": c.ShutdownTimeout,
		},
		"background": map[string]interface{}{
			"enabled":  c.EnableBackground,
			"pid_file": c.PIDFile,
		},
		"metadata": map[string]interface{}{
			"version":       c.Version,
			"last_modified": c.LastModified.Format(time.RFC3339),
			"config_file":   getConfigFilePath(),
		},
	}
}

// ApplyCliFlags applies CLI flags to configuration (called from command handlers)
// MUST handle CLI precedence properly
func ApplyCliFlags(config *CLIConfig, cmd *cobra.Command) {
	config.mu.Lock()
	defer config.mu.Unlock()

	// Registry settings
	if cmd.Flags().Changed("registry-port") {
		if val, err := cmd.Flags().GetInt("registry-port"); err == nil {
			config.RegistryPort = val
		}
	}

	if cmd.Flags().Changed("registry-host") {
		if val, err := cmd.Flags().GetString("registry-host"); err == nil {
			config.RegistryHost = val
		}
	}

	if cmd.Flags().Changed("db-path") {
		if val, err := cmd.Flags().GetString("db-path"); err == nil {
			config.DBPath = val
		}
	}

	if cmd.Flags().Changed("log-level") {
		if val, err := cmd.Flags().GetString("log-level"); err == nil {
			config.LogLevel = strings.ToUpper(val)
		}
	}

	if cmd.Flags().Changed("health-check-interval") {
		if val, err := cmd.Flags().GetInt("health-check-interval"); err == nil {
			config.HealthCheckInterval = val
		}
	}

	if cmd.Flags().Changed("debug") {
		if val, err := cmd.Flags().GetBool("debug"); err == nil {
			config.DebugMode = val
		}
	}

	if cmd.Flags().Changed("startup-timeout") {
		if val, err := cmd.Flags().GetInt("startup-timeout"); err == nil {
			config.StartupTimeout = val
		}
	}

	if cmd.Flags().Changed("shutdown-timeout") {
		if val, err := cmd.Flags().GetInt("shutdown-timeout"); err == nil {
			config.ShutdownTimeout = val
		}
	}

	if cmd.Flags().Changed("background") {
		if val, err := cmd.Flags().GetBool("background"); err == nil {
			config.EnableBackground = val
		}
	}

	if cmd.Flags().Changed("pid-file") {
		if val, err := cmd.Flags().GetString("pid-file"); err == nil {
			config.PIDFile = val
		}
	}

	// Update metadata after CLI changes
	config.LastModified = time.Now()
}

// Validate ensures configuration is valid
// MUST match Python configuration validation
func (c *CLIConfig) Validate() error {
	c.mu.RLock()
	defer c.mu.RUnlock()

	// Port validation
	if c.RegistryPort < 1 || c.RegistryPort > 65535 {
		return fmt.Errorf("invalid registry port: %d (must be 1-65535)", c.RegistryPort)
	}

	// Host validation
	if strings.TrimSpace(c.RegistryHost) == "" {
		return fmt.Errorf("registry host cannot be empty")
	}

	// Database path validation
	if strings.TrimSpace(c.DBPath) == "" {
		return fmt.Errorf("database path cannot be empty")
	}

	// Log level validation
	validLogLevels := map[string]bool{
		"TRACE": true, // Most verbose - includes SQL queries
		"DEBUG": true,
		"INFO":  true,
		"WARN":  true,
		"ERROR": true,
		"FATAL": true,
	}
	if !validLogLevels[strings.ToUpper(c.LogLevel)] {
		return fmt.Errorf("invalid log level: %s (must be TRACE, DEBUG, INFO, WARN, ERROR, or FATAL)", c.LogLevel)
	}

	// Health check interval validation
	if c.HealthCheckInterval < 1 {
		return fmt.Errorf("health check interval must be positive: %d", c.HealthCheckInterval)
	}

	// Timeout validation
	if c.StartupTimeout < 1 {
		return fmt.Errorf("startup timeout must be positive: %d", c.StartupTimeout)
	}
	if c.ShutdownTimeout < 1 {
		return fmt.Errorf("shutdown timeout must be positive: %d", c.ShutdownTimeout)
	}

	// PID file validation
	if strings.TrimSpace(c.PIDFile) == "" {
		return fmt.Errorf("PID file path cannot be empty")
	}

	return nil
}

// Migrate performs configuration migration if needed
func (c *CLIConfig) Migrate() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	// Check if migration is needed
	if c.Version == "" || c.Version != ConfigVersion {
		// Perform migration based on version
		switch c.Version {
		case "", "0.1.0", "0.2.0":
			// Migrate from early versions
			c.Version = ConfigVersion
			c.LastModified = time.Now()
			// Add any version-specific migration logic here
		default:
			// Future version, no migration needed
			c.Version = ConfigVersion
			c.LastModified = time.Now()
		}
	}

	return nil
}

// Clone creates a deep copy of the configuration
func (c *CLIConfig) Clone() *CLIConfig {
	c.mu.RLock()
	defer c.mu.RUnlock()

	return &CLIConfig{
		RegistryPort:        c.RegistryPort,
		RegistryHost:        c.RegistryHost,
		DBPath:              c.DBPath,
		LogLevel:            c.LogLevel,
		HealthCheckInterval: c.HealthCheckInterval,
		DebugMode:           c.DebugMode,
		StartupTimeout:      c.StartupTimeout,
		ShutdownTimeout:     c.ShutdownTimeout,
		EnableBackground:    c.EnableBackground,
		PIDFile:             c.PIDFile,
		Version:             c.Version,
		LastModified:        c.LastModified,
	}
}

// GetSafeValue returns a field value in a thread-safe manner
func (c *CLIConfig) GetRegistryURL() string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return fmt.Sprintf("http://%s:%d", c.RegistryHost, c.RegistryPort)
}

// GetEnvironmentVariables returns environment variables for agent processes
func (c *CLIConfig) GetEnvironmentVariables() []string {
	c.mu.RLock()
	defer c.mu.RUnlock()

	return []string{
		fmt.Sprintf("MCP_MESH_REGISTRY_URL=%s", c.GetRegistryURL()),
		fmt.Sprintf("MCP_MESH_REGISTRY_HOST=%s", c.RegistryHost),
		fmt.Sprintf("MCP_MESH_REGISTRY_PORT=%d", c.RegistryPort),
		fmt.Sprintf("MCP_MESH_DATABASE_URL=sqlite:///%s", c.DBPath),
		fmt.Sprintf("MCP_MESH_LOG_LEVEL=%s", c.LogLevel),
		fmt.Sprintf("MCP_MESH_HEALTH_CHECK_INTERVAL=%d", c.HealthCheckInterval),
	}
}

// GetRegistryEnvironmentVariables returns environment variables for the registry service
func (c *CLIConfig) GetRegistryEnvironmentVariables() []string {
	c.mu.RLock()
	defer c.mu.RUnlock()

	// Determine effective log level (debug mode forces DEBUG level)
	effectiveLogLevel := c.LogLevel
	if c.DebugMode {
		effectiveLogLevel = "DEBUG"
	}

	return []string{
		fmt.Sprintf("HOST=%s", c.RegistryHost),
		fmt.Sprintf("PORT=%d", c.RegistryPort),
		fmt.Sprintf("DATABASE_URL=%s", c.DBPath),
		fmt.Sprintf("MCP_MESH_LOG_LEVEL=%s", strings.ToUpper(effectiveLogLevel)),
		fmt.Sprintf("MCP_MESH_DEBUG_MODE=%t", c.DebugMode),
		fmt.Sprintf("HEALTH_CHECK_INTERVAL=%d", c.HealthCheckInterval),
	}
}

// Global configuration instance
var globalConfig *CLIConfig
var configMutex sync.Mutex

// GetCLIConfig returns the global CLI configuration
func GetCLIConfig() *CLIConfig {
	configMutex.Lock()
	defer configMutex.Unlock()

	if globalConfig == nil {
		var err error
		globalConfig, err = LoadConfig()
		if err != nil {
			// Fallback to default config
			globalConfig = DefaultConfig()
		}
	}

	return globalConfig
}

// Load reloads the configuration
func (c *CLIConfig) Load() error {
	newConfig, err := LoadConfig()
	if err != nil {
		return err
	}

	c.mu.Lock()
	defer c.mu.Unlock()

	// Copy new values (preserve the mutex)
	c.RegistryPort = newConfig.RegistryPort
	c.RegistryHost = newConfig.RegistryHost
	c.DBPath = newConfig.DBPath
	c.LogLevel = newConfig.LogLevel
	c.HealthCheckInterval = newConfig.HealthCheckInterval
	c.DebugMode = newConfig.DebugMode
	c.StartupTimeout = newConfig.StartupTimeout
	c.ShutdownTimeout = newConfig.ShutdownTimeout
	c.EnableBackground = newConfig.EnableBackground
	c.PIDFile = newConfig.PIDFile
	c.StateDir = newConfig.StateDir
	c.Version = newConfig.Version
	c.LastModified = newConfig.LastModified

	return nil
}
