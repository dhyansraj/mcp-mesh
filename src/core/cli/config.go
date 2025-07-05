package cli

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
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
	RegistryPort int    `json:"registry_port"` // default: 8080
	RegistryHost string `json:"registry_host"` // default: "localhost"

	// Database settings
	DBPath string `json:"db_path"` // default: "./dev_registry.db"

	// Logging settings
	LogLevel string `json:"log_level"` // default: "INFO"

	// Health monitoring
	HealthCheckInterval int `json:"health_check_interval"` // default: 10

	// Development settings
	AutoRestart bool `json:"auto_restart"` // default: true
	WatchFiles  bool `json:"watch_files"`  // default: true
	DebugMode   bool `json:"debug_mode"`   // default: false

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
		AutoRestart:         true,
		WatchFiles:          true,
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

// LoadConfig loads configuration with proper precedence: CLI args > Config file > Environment vars > Defaults
// MUST match Python configuration loading behavior exactly
func LoadConfig() (*CLIConfig, error) {
	// Start with default values
	config := DefaultConfig()

	// 1. Load from environment variables (MCP_MESH_ prefix)
	loadFromEnvironment(config)

	// 2. Load from configuration file (~/.mcp_mesh/cli_config.json)
	if err := loadFromConfigFile(config); err != nil {
		// Config file errors are not fatal, just log and continue
		// This matches Python behavior
		fmt.Printf("Warning: Failed to load config file: %v\n", err)
	}

	// 3. Validate configuration
	if err := config.Validate(); err != nil {
		return nil, fmt.Errorf("configuration validation failed: %w", err)
	}

	// 4. Migrate configuration if needed
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
	if val := os.Getenv("MCP_MESH_AUTO_RESTART"); val != "" {
		config.AutoRestart = parseBoolEnv(val)
	}

	if val := os.Getenv("MCP_MESH_WATCH_FILES"); val != "" {
		config.WatchFiles = parseBoolEnv(val)
	}

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

// loadFromConfigFile loads configuration from ~/.mcp_mesh/cli_config.json
// MUST match Python config file handling exactly
func loadFromConfigFile(config *CLIConfig) error {
	configPath := getConfigFilePath()

	// Check if config file exists
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		// Config file doesn't exist, use current values (from defaults + env)
		return nil
	}

	// Create backup before loading
	if err := createConfigBackup(configPath); err != nil {
		// Backup creation failure is not fatal, just log warning
		fmt.Printf("Warning: Failed to create config backup: %v\n", err)
	}

	// Read config file with retry and recovery
	retry := 3
	for i := 0; i < retry; i++ {
		data, err := ioutil.ReadFile(configPath)
		if err != nil {
			if i == retry-1 {
				return fmt.Errorf("failed to read config file %s after %d attempts: %w", configPath, retry, err)
			}
			continue
		}

		// Parse JSON
		var fileConfig CLIConfig
		if err := json.Unmarshal(data, &fileConfig); err != nil {
			if i == retry-1 {
				// Try to recover from backup
				if recoverErr := recoverFromBackup(configPath); recoverErr != nil {
					return fmt.Errorf("failed to parse config file %s and backup recovery failed: parse_error=%w, recovery_error=%v", configPath, err, recoverErr)
				}
				// Try parsing backup
				if backupData, readErr := ioutil.ReadFile(configPath + ".backup"); readErr == nil {
					if backupErr := json.Unmarshal(backupData, &fileConfig); backupErr == nil {
						fmt.Println("Successfully recovered from config backup")
						break
					}
				}
				return fmt.Errorf("failed to parse config file %s: %w", configPath, err)
			}
			continue
		}

		// Successful parsing
		config.mu.Lock()
		mergeConfigurations(config, &fileConfig)
		config.mu.Unlock()
		break
	}

	return nil
}

// mergeConfigurations merges file config with current config (env vars + defaults)
// MUST match Python configuration merging behavior
func mergeConfigurations(target *CLIConfig, source *CLIConfig) {
	// Only override non-zero/non-empty values from file config
	if source.RegistryPort != 0 {
		target.RegistryPort = source.RegistryPort
	}
	if source.RegistryHost != "" {
		target.RegistryHost = source.RegistryHost
	}
	if source.DBPath != "" {
		target.DBPath = source.DBPath
	}
	if source.LogLevel != "" {
		target.LogLevel = source.LogLevel
	}
	if source.HealthCheckInterval != 0 {
		target.HealthCheckInterval = source.HealthCheckInterval
	}
	// Boolean fields need special handling since false is a valid value
	// We check if the source has been explicitly set (different from default)
	target.AutoRestart = source.AutoRestart
	target.WatchFiles = source.WatchFiles
	target.DebugMode = source.DebugMode
	target.EnableBackground = source.EnableBackground

	if source.StartupTimeout != 0 {
		target.StartupTimeout = source.StartupTimeout
	}
	if source.ShutdownTimeout != 0 {
		target.ShutdownTimeout = source.ShutdownTimeout
	}
	if source.PIDFile != "" {
		target.PIDFile = source.PIDFile
	}

	// Update metadata
	target.LastModified = time.Now()
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

// SaveConfig saves the configuration with atomic write and backup
// MUST match Python config saving behavior
func SaveConfig(config *CLIConfig) error {
	config.mu.Lock()
	defer config.mu.Unlock()

	configPath := getConfigFilePath()

	// Ensure directory exists
	dir := filepath.Dir(configPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("failed to create config directory %s: %w", dir, err)
	}

	// Update metadata before saving
	config.Version = ConfigVersion
	config.LastModified = time.Now()

	// Marshal configuration to JSON
	data, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal configuration: %w", err)
	}

	// Atomic write: write to temporary file first, then rename
	tempPath := configPath + ".tmp"
	if err := ioutil.WriteFile(tempPath, data, 0644); err != nil {
		return fmt.Errorf("failed to write temporary config file %s: %w", tempPath, err)
	}

	// Create backup of existing config
	if _, err := os.Stat(configPath); err == nil {
		if err := createConfigBackup(configPath); err != nil {
			// Backup failure is not fatal, just log warning
			fmt.Printf("Warning: Failed to create config backup: %v\n", err)
		}
	}

	// Atomic rename
	if err := os.Rename(tempPath, configPath); err != nil {
		// Cleanup temp file on failure
		os.Remove(tempPath)
		return fmt.Errorf("failed to save config file %s: %w", configPath, err)
	}

	return nil
}

// createConfigBackup creates a backup of the configuration file
func createConfigBackup(configPath string) error {
	backupPath := configPath + ".backup"
	data, err := ioutil.ReadFile(configPath)
	if err != nil {
		return err
	}
	return ioutil.WriteFile(backupPath, data, 0644)
}

// recoverFromBackup recovers configuration from backup
func recoverFromBackup(configPath string) error {
	backupPath := configPath + ".backup"
	if _, err := os.Stat(backupPath); os.IsNotExist(err) {
		return fmt.Errorf("backup file does not exist")
	}

	data, err := ioutil.ReadFile(backupPath)
	if err != nil {
		return fmt.Errorf("failed to read backup: %w", err)
	}

	return ioutil.WriteFile(configPath, data, 0644)
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
	if err := ioutil.WriteFile(tempFile, []byte("test"), 0644); err != nil {
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
			"auto_restart": c.AutoRestart,
			"watch_files":  c.WatchFiles,
			"debug_mode":   c.DebugMode,
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

	if cmd.Flags().Changed("auto-restart") {
		if val, err := cmd.Flags().GetBool("auto-restart"); err == nil {
			config.AutoRestart = val
		}
	}

	if cmd.Flags().Changed("watch-files") {
		if val, err := cmd.Flags().GetBool("watch-files"); err == nil {
			config.WatchFiles = val
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
		"DEBUG": true,
		"INFO":  true,
		"WARN":  true,
		"ERROR": true,
		"FATAL": true,
	}
	if !validLogLevels[strings.ToUpper(c.LogLevel)] {
		return fmt.Errorf("invalid log level: %s (must be DEBUG, INFO, WARN, ERROR, or FATAL)", c.LogLevel)
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
		AutoRestart:         c.AutoRestart,
		WatchFiles:          c.WatchFiles,
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

// LoadConfigFromFile loads configuration from a specific file path
func LoadConfigFromFile(configPath string) (*CLIConfig, error) {
	// Start with default configuration
	config := DefaultConfig()

	// Load environment variables first
	loadFromEnvironment(config)

	// Load from specified config file
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		return nil, fmt.Errorf("configuration file does not exist: %s", configPath)
	}

	data, err := ioutil.ReadFile(configPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file %s: %w", configPath, err)
	}

	if err := json.Unmarshal(data, config); err != nil {
		return nil, fmt.Errorf("failed to parse config file %s: %w", configPath, err)
	}

	// Validate configuration
	if err := config.Validate(); err != nil {
		return nil, fmt.Errorf("configuration validation failed: %w", err)
	}

	// Migrate configuration if needed
	if err := config.Migrate(); err != nil {
		return nil, fmt.Errorf("configuration migration failed: %w", err)
	}

	return config, nil
}

// ResetConfig resets configuration to defaults
func ResetConfig() error {
	configPath := getConfigFilePath()

	// Create backup if config exists
	if _, err := os.Stat(configPath); err == nil {
		if err := createConfigBackup(configPath); err != nil {
			fmt.Printf("Warning: Failed to create config backup: %v\n", err)
		}
	}

	// Create new default configuration
	config := DefaultConfig()

	// Save to file
	if err := SaveConfig(config); err != nil {
		return fmt.Errorf("failed to save reset configuration: %w", err)
	}

	return nil
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
	c.AutoRestart = newConfig.AutoRestart
	c.WatchFiles = newConfig.WatchFiles
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
