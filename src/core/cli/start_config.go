package cli

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/spf13/cobra"
)

// Environment file loading
func loadEnvironmentFile(envFile string) error {
	file, err := os.Open(envFile)
	if err != nil {
		return fmt.Errorf("cannot open environment file: %w", err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if err := setEnvironmentVariable(line); err != nil {
			return fmt.Errorf("invalid environment variable in %s: %s", envFile, line)
		}
	}

	return scanner.Err()
}

// Set environment variable from KEY=VALUE format
func setEnvironmentVariable(envVar string) error {
	parts := strings.SplitN(envVar, "=", 2)
	if len(parts) != 2 {
		return fmt.Errorf("environment variable must be in KEY=VALUE format")
	}

	key := strings.TrimSpace(parts[0])
	value := strings.TrimSpace(parts[1])

	if key == "" {
		return fmt.Errorf("environment variable key cannot be empty")
	}

	return os.Setenv(key, value)
}

// Validate flag combinations
func validateFlagCombinations(cmd *cobra.Command) error {
	registryOnly, _ := cmd.Flags().GetBool("registry-only")
	connectOnly, _ := cmd.Flags().GetBool("connect-only")
	registryURL, _ := cmd.Flags().GetString("registry-url")

	if registryOnly && connectOnly {
		return fmt.Errorf("--registry-only and --connect-only flags are mutually exclusive")
	}

	if connectOnly && registryURL == "" {
		return fmt.Errorf("--registry-url is required when using --connect-only")
	}

	if registryOnly && registryURL != "" {
		return fmt.Errorf("--registry-url cannot be used with --registry-only")
	}

	return nil
}

// Apply all start flags to configuration
func applyAllStartFlags(cmd *cobra.Command, config *CLIConfig) error {
	// Registry configuration
	if cmd.Flags().Changed("registry-port") {
		port, _ := cmd.Flags().GetInt("registry-port")
		if port > 0 {
			config.RegistryPort = port
		}
	}

	if cmd.Flags().Changed("registry-host") {
		host, _ := cmd.Flags().GetString("registry-host")
		if host != "" {
			config.RegistryHost = host
		}
	}

	if cmd.Flags().Changed("db-path") {
		dbPath, _ := cmd.Flags().GetString("db-path")
		if dbPath != "" {
			absPath, err := AbsolutePath(dbPath)
			if err != nil {
				return fmt.Errorf("invalid db-path: %w", err)
			}
			config.DBPath = absPath
		}
	}

	// Logging configuration
	if cmd.Flags().Changed("log-level") {
		logLevel, _ := cmd.Flags().GetString("log-level")
		if logLevel != "" {
			if !ValidateLogLevel(logLevel) {
				return fmt.Errorf("invalid log level: %s (must be TRACE, DEBUG, INFO, WARNING, ERROR, or CRITICAL)", logLevel)
			}
			config.LogLevel = logLevel
		}
	}

	if cmd.Flags().Changed("debug") {
		debug, _ := cmd.Flags().GetBool("debug")
		config.DebugMode = debug
		if debug {
			config.LogLevel = "DEBUG"
		}
	}

	// Health and timeout configuration
	if cmd.Flags().Changed("health-check-interval") {
		interval, _ := cmd.Flags().GetInt("health-check-interval")
		if interval > 0 {
			config.HealthCheckInterval = interval
		}
	}

	if cmd.Flags().Changed("startup-timeout") {
		timeout, _ := cmd.Flags().GetInt("startup-timeout")
		if timeout > 0 {
			config.StartupTimeout = timeout
		}
	}

	if cmd.Flags().Changed("shutdown-timeout") {
		timeout, _ := cmd.Flags().GetInt("shutdown-timeout")
		if timeout > 0 {
			config.ShutdownTimeout = timeout
		}
	}

	// Background service configuration
	if cmd.Flags().Changed("detach") {
		detach, _ := cmd.Flags().GetBool("detach")
		config.EnableBackground = detach
	}

	return nil
}
