package cli

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

// Language constants for agent detection
const (
	langPython     = "python"
	langTypeScript = "typescript"
	langJava       = "java"
)

// NewStartCommand creates the start command
func NewStartCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "start [agents...]",
		Short: "Start MCP agent with mesh runtime",
		Long: `Start one or more MCP agents with mesh runtime support.

Supports Python (.py), TypeScript (.ts, .js), and Java (Maven/Spring Boot) agents.
If no registry is running, a local registry will be started automatically.
The registry service can also be started independently using --registry-only.

Examples:
  meshctl start                              # Start registry only
  meshctl start examples/hello_world.py     # Start Python agent
  meshctl start src/index.ts                # Start TypeScript agent
  meshctl start examples/java/my-agent      # Start Java agent (Maven project)
  meshctl start my-agent.jar                # Start Java agent (JAR file)
  meshctl start --registry-only              # Start only the registry service
  meshctl start agent1.py agent2.ts         # Start multiple agents (mixed languages)`,
		Args: cobra.ArbitraryArgs,
		RunE: runStartCommand,
	}

	// Core functionality flags
	cmd.Flags().Bool("registry-only", false, "Start registry service only")
	cmd.Flags().String("registry-url", "", "External registry URL to connect to")
	cmd.Flags().Bool("connect-only", false, "Connect to external registry without embedding")

	// Registry configuration flags
	cmd.Flags().String("registry-host", "", "Registry host address (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port number (default: 8000)")
	cmd.Flags().String("db-path", "", "Database file path (default: ~/.mcp-mesh/mcp_mesh_registry.db)")

	// Logging and debug flags
	cmd.Flags().Bool("debug", false, "Enable debug mode")
	cmd.Flags().String("log-level", "", "Set log level (TRACE, DEBUG, INFO, WARN, ERROR) (default: INFO). TRACE enables SQL logging.")
	cmd.Flags().Bool("verbose", false, "Enable verbose output")
	cmd.Flags().Bool("quiet", false, "Suppress non-error output")

	// Health monitoring flags
	cmd.Flags().Int("health-check-interval", 0, "Health check interval in seconds (default: 30)")
	cmd.Flags().Int("startup-timeout", 0, "Agent startup timeout in seconds (default: 30)")
	cmd.Flags().Int("shutdown-timeout", 0, "Graceful shutdown timeout in seconds (default: 30)")

	// Background service flags
	cmd.Flags().BoolP("detach", "d", false, "Run in detached mode (detach)")
	cmd.Flags().String("pid-file", "", "Deprecated: PID files are now per-agent in ~/.mcp-mesh/pids/")
	cmd.Flags().MarkDeprecated("pid-file", "PID files are now managed per-agent in ~/.mcp-mesh/pids/")

	// Advanced configuration flags
	cmd.Flags().StringArray("env", []string{}, "Additional environment variables (KEY=VALUE)")
	cmd.Flags().String("env-file", "", "Environment file to load (.env format)")

	// Agent-specific flags
	cmd.Flags().String("agent-name", "", "Override agent name")
	cmd.Flags().StringArray("capabilities", []string{}, "Override agent capabilities")
	cmd.Flags().String("agent-version", "", "Override agent version")
	cmd.Flags().String("working-dir", "", "Working directory for agent processes")

	// User and security flags
	cmd.Flags().String("user", "", "Run agent as specific user (Unix only)")
	cmd.Flags().String("group", "", "Run agent as specific group (Unix only)")
	cmd.Flags().Bool("secure", false, "Enable secure connections")
	cmd.Flags().String("cert-file", "", "TLS certificate file")
	cmd.Flags().String("key-file", "", "TLS private key file")
	cmd.Flags().Bool("tls-auto", false, "Auto-generate TLS certificates for development")

	// Development flags
	cmd.Flags().BoolP("watch", "w", false, "Watch files and restart on changes")
	cmd.Flags().Bool("dte", false, "Enable distributed tracing (sets MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true)")

	// UI server flags
	cmd.Flags().Bool("ui", false, "Start the dashboard UI server alongside agents")
	cmd.Flags().Int("ui-port", 0, "UI server port (default: 3080, overrides MCP_MESH_UI_PORT)")
	cmd.Flags().Bool("dashboard", false, "Open browser to dashboard after start")

	return cmd
}

func runStartCommand(cmd *cobra.Command, args []string) error {
	// Load configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Load environment file if specified
	envFile, _ := cmd.Flags().GetString("env-file")
	if envFile != "" {
		if err := loadEnvironmentFile(envFile); err != nil {
			return fmt.Errorf("failed to load environment file %s: %w", envFile, err)
		}
	}

	// Enable distributed tracing if --dte flag is set
	if dte, _ := cmd.Flags().GetBool("dte"); dte {
		os.Setenv("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "true")
	}

	// Apply additional environment variables
	envVars, _ := cmd.Flags().GetStringArray("env")
	for _, envVar := range envVars {
		if err := setEnvironmentVariable(envVar); err != nil {
			return fmt.Errorf("invalid environment variable %s: %w", envVar, err)
		}
	}

	// Override config with command line flags
	if err := applyAllStartFlags(cmd, config); err != nil {
		return err
	}

	// Handle --tls-auto
	tlsAuto, _ := cmd.Flags().GetBool("tls-auto")
	quiet, _ := cmd.Flags().GetBool("quiet")
	if tlsAuto {
		if !quiet {
			fmt.Println("Setting up auto TLS certificates...")
		}
		tlsAutoConfig, err := SetupTLSAuto(config.StateDir)
		if err != nil {
			return fmt.Errorf("TLS auto-setup failed: %w", err)
		}
		config.TLSAuto = true
		config.TLSAutoConfigRef = tlsAutoConfig
		if !quiet {
			fmt.Println("TLS certificates generated successfully")
		}
	}

	// Parse core mode flags
	registryOnly, _ := cmd.Flags().GetBool("registry-only")
	registryURL, _ := cmd.Flags().GetString("registry-url")
	connectOnly, _ := cmd.Flags().GetBool("connect-only")
	detach, _ := cmd.Flags().GetBool("detach")

	// Validate flag combinations
	if err := validateFlagCombinations(cmd); err != nil {
		return err
	}

	// Resolve folder paths to entry point files (issue #474)
	// This allows `meshctl start my-agent` instead of `meshctl start my-agent/main.py`
	resolvedArgs := args
	if len(args) > 0 {
		var err error
		resolvedArgs, err = resolveAllAgentPaths(args)
		if err != nil {
			return err
		}
	}

	// Run pre-flight checks BEFORE forking to background (issue #444)
	// This ensures validation errors are shown to the user, not hidden in log files
	quiet, _ = cmd.Flags().GetBool("quiet")
	if len(resolvedArgs) > 0 {
		if err := runPrerequisiteValidation(resolvedArgs, quiet); err != nil {
			return err
		}
	}

	// Handle detach mode FIRST - before other modes
	// This ensures log redirection is set up before any other processing
	if detach {
		return startBackgroundMode(cmd, resolvedArgs, config)
	}

	// Handle registry-only mode
	if registryOnly {
		return startRegistryOnlyMode(cmd, config)
	}

	// Handle connect-only mode
	if connectOnly {
		if registryURL == "" {
			return fmt.Errorf("--registry-url required with --connect-only")
		}
		return startConnectOnlyMode(cmd, resolvedArgs, registryURL, config)
	}

	// If no agents provided, start registry only
	if len(resolvedArgs) == 0 {
		fmt.Println("No agents specified, starting registry only")
		return startRegistryOnlyMode(cmd, config)
	}

	// Standard agent startup mode
	return startStandardMode(cmd, resolvedArgs, config)
}
