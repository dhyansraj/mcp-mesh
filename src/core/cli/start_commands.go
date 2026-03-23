package cli

import (
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"

	"mcp-mesh/src/core/cli/handlers"
)

// Create agent command with language detection and environment setup
func createAgentCommand(agentPath string, env []string, workingDir, user, group string, watch bool) (*exec.Cmd, error) {
	handler := handlers.DetectLanguage(agentPath)
	lang := handler.Language()

	switch lang {
	case langTypeScript:
		return createTypeScriptAgentCommand(agentPath, env, workingDir, user, group, watch)
	case langPython:
		return createPythonAgentCommand(agentPath, env, workingDir, user, group, watch)
	case langJava:
		return createJavaAgentCommand(agentPath, env, workingDir, user, group, watch)
	default:
		return nil, fmt.Errorf("unsupported file type: %s (use .py, .ts, .js, .java, or .jar)", agentPath)
	}
}

// createTypeScriptAgentCommand creates a command for TypeScript/JavaScript agents
func createTypeScriptAgentCommand(agentPath string, env []string, workingDir, userName, groupName string, watch bool) (*exec.Cmd, error) {
	// Convert script path to absolute path
	absScriptPath, err := filepath.Abs(agentPath)
	if err != nil {
		return nil, fmt.Errorf("failed to get absolute path for %s: %w", agentPath, err)
	}

	finalWorkingDir := filepath.Dir(absScriptPath)

	// Override working directory if specified in command line
	if workingDir != "" {
		absWorkingDir, err := AbsolutePath(workingDir)
		if err != nil {
			return nil, fmt.Errorf("invalid working directory: %w", err)
		}
		finalWorkingDir = absWorkingDir
	}

	// Create command based on file extension
	var cmd *exec.Cmd
	ext := filepath.Ext(agentPath)

	if watch {
		// For watch mode with TypeScript, use npx tsx --watch
		if ext == ".ts" {
			cmd = exec.Command("npx", "tsx", "--watch", absScriptPath)
		} else {
			// For .js files, use node with --watch (Node 18+)
			cmd = exec.Command("node", "--watch", absScriptPath)
		}
	} else {
		if ext == ".ts" {
			// Use npx tsx for TypeScript files
			cmd = exec.Command("npx", "tsx", absScriptPath)
		} else {
			// Use node for JavaScript files
			cmd = exec.Command("node", absScriptPath)
		}
	}

	cmd.Env = env
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	cmd.Dir = finalWorkingDir

	// Set up process group for proper signal handling (Unix only)
	// This ensures that when we stop the agent, we kill the entire process tree
	// (npx -> tsx -> node) rather than just the parent process
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	// Set user and group (Unix only)
	if userName != "" || groupName != "" {
		if err := setProcessCredentials(cmd, userName, groupName); err != nil {
			return nil, fmt.Errorf("failed to set process credentials: %w", err)
		}
	}

	return cmd, nil
}

// createPythonAgentCommand creates a command for Python agents (including YAML configs)
func createPythonAgentCommand(agentPath string, env []string, workingDir, userName, groupName string, watch bool) (*exec.Cmd, error) {
	var pythonExec string
	var scriptPath string
	var finalWorkingDir string

	// Check if this is a YAML config file or Python script
	if filepath.Ext(agentPath) == ".yaml" || filepath.Ext(agentPath) == ".yml" {
		// YAML config mode
		config, err := LoadAgentConfig(agentPath)
		if err != nil {
			return nil, fmt.Errorf("failed to load agent config: %w", err)
		}

		// Validate config
		if err := ValidateAgentConfig(config); err != nil {
			return nil, fmt.Errorf("invalid agent config: %w", err)
		}

		// Use specified Python interpreter or detect environment
		if config.PythonInterpreter != "" {
			pythonExec = config.PythonInterpreter
		} else {
			pythonEnv, err := DetectPythonEnvironment()
			if err != nil {
				return nil, fmt.Errorf("Python environment detection failed: %w", err)
			}

			// Ensure mcp-mesh-runtime is available
			if err := EnsureMcpMeshRuntime(pythonEnv); err != nil {
				return nil, fmt.Errorf("package management failed: %w", err)
			}

			pythonExec = pythonEnv.PythonExecutable
		}

		// Resolve script path relative to YAML file's directory (not CWD)
		scriptRef := config.Script
		if !filepath.IsAbs(scriptRef) {
			scriptRef = filepath.Join(filepath.Dir(agentPath), scriptRef)
		}
		absScriptPath, err := filepath.Abs(scriptRef)
		if err != nil {
			return nil, fmt.Errorf("failed to get absolute path for %s: %w", config.Script, err)
		}
		scriptPath = absScriptPath
		finalWorkingDir = config.GetWorkingDirectory()

		// Merge environment variables from config
		configEnv := config.GetEnvironmentVariables()
		env = mergeEnvironmentVariables(env, configEnv)
	} else {
		// Simple .py mode - detect Python environment
		pythonEnv, err := DetectPythonEnvironment()
		if err != nil {
			return nil, fmt.Errorf("Python environment detection failed: %w", err)
		}

		// Ensure mcp-mesh-runtime is available
		if err := EnsureMcpMeshRuntime(pythonEnv); err != nil {
			return nil, fmt.Errorf("package management failed: %w", err)
		}

		pythonExec = pythonEnv.PythonExecutable

		// Convert script path to absolute path
		absScriptPath, err := filepath.Abs(agentPath)
		if err != nil {
			return nil, fmt.Errorf("failed to get absolute path for %s: %w", agentPath, err)
		}
		scriptPath = absScriptPath
		finalWorkingDir = filepath.Dir(absScriptPath)
	}

	// Override working directory if specified in command line
	if workingDir != "" {
		absWorkingDir, err := AbsolutePath(workingDir)
		if err != nil {
			return nil, fmt.Errorf("invalid working directory: %w", err)
		}
		finalWorkingDir = absWorkingDir
	}

	// Create command to run the Python script
	// The mcp_mesh_runtime will be auto-imported via site-packages
	// Watch mode is handled by AgentWatcher at the caller level
	cmd := exec.Command(pythonExec, scriptPath)
	cmd.Env = env
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	cmd.Dir = finalWorkingDir

	// Set up process group for proper signal handling (Unix only)
	// This ensures that when we stop the agent, we kill the entire process tree
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	// Set user and group (Unix only)
	if userName != "" || groupName != "" {
		if err := setProcessCredentials(cmd, userName, groupName); err != nil {
			return nil, fmt.Errorf("failed to set process credentials: %w", err)
		}
	}

	return cmd, nil
}

// createJavaAgentCommand creates a command for Java agents (Maven/Spring Boot or JAR)
func createJavaAgentCommand(agentPath string, env []string, workingDir, userName, groupName string, watch bool) (*exec.Cmd, error) {
	var cmd *exec.Cmd
	var finalWorkingDir string

	// Check if it's a JAR file
	if strings.HasSuffix(strings.ToLower(agentPath), ".jar") {
		// Convert JAR path to absolute path
		absJarPath, err := filepath.Abs(agentPath)
		if err != nil {
			return nil, fmt.Errorf("failed to get absolute path for %s: %w", agentPath, err)
		}

		finalWorkingDir = filepath.Dir(absJarPath)

		// Override working directory if specified in command line
		if workingDir != "" {
			absWorkingDir, err := AbsolutePath(workingDir)
			if err != nil {
				return nil, fmt.Errorf("invalid working directory: %w", err)
			}
			finalWorkingDir = absWorkingDir
		}

		// Run JAR directly with java -jar
		cmd = exec.Command("java", "-jar", absJarPath)
	} else {
		// Maven project - find the project root (directory with pom.xml)
		projectDir := agentPath

		// If agentPath is a file, get its directory
		if info, err := os.Stat(agentPath); err == nil && !info.IsDir() {
			projectDir = filepath.Dir(agentPath)
		}

		// Convert to absolute path
		absProjectDir, err := filepath.Abs(projectDir)
		if err != nil {
			return nil, fmt.Errorf("failed to get absolute path for %s: %w", projectDir, err)
		}

		// Walk up to find pom.xml if not in current directory
		javaHandler := &handlers.JavaHandler{}
		projectRoot, err := javaHandler.FindProjectRoot(absProjectDir)
		if err != nil {
			return nil, fmt.Errorf("cannot find Maven project: %w", err)
		}

		finalWorkingDir = projectRoot

		// Override working directory if specified in command line
		if workingDir != "" {
			absWorkingDir, err := AbsolutePath(workingDir)
			if err != nil {
				return nil, fmt.Errorf("invalid working directory: %w", err)
			}
			finalWorkingDir = absWorkingDir
		}

		// Use mvn spring-boot:run
		cmd = exec.Command("mvn", "spring-boot:run", "-q")
	}

	// Add Java-specific environment variables
	javaEnv := []string{
		"SPRING_MAIN_BANNER_MODE=off", // Disable Spring Boot banner for cleaner output
	}
	env = append(env, javaEnv...)

	cmd.Env = env
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	cmd.Dir = finalWorkingDir

	// Set up process group for proper signal handling (Unix only)
	// This ensures that when we stop the agent, we kill the entire process tree
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	// Set user and group (Unix only)
	if userName != "" || groupName != "" {
		if err := setProcessCredentials(cmd, userName, groupName); err != nil {
			return nil, fmt.Errorf("failed to set process credentials: %w", err)
		}
	}

	return cmd, nil
}

// mergeEnvironmentVariables merges two environment variable slices
func mergeEnvironmentVariables(env1, env2 []string) []string {
	envMap := make(map[string]string)

	// Parse first environment
	for _, envVar := range env1 {
		parts := strings.SplitN(envVar, "=", 2)
		if len(parts) == 2 {
			envMap[parts[0]] = parts[1]
		}
	}

	// Parse and merge second environment (overwrites)
	for _, envVar := range env2 {
		parts := strings.SplitN(envVar, "=", 2)
		if len(parts) == 2 {
			envMap[parts[0]] = parts[1]
		}
	}

	// Convert back to slice
	var result []string
	for key, value := range envMap {
		result = append(result, fmt.Sprintf("%s=%s", key, value))
	}

	return result
}

// Set process credentials (Unix only)
func setProcessCredentials(cmd *exec.Cmd, username, groupname string) error {
	// This is Unix-specific functionality
	if username == "" && groupname == "" {
		return nil
	}

	// Parse user ID
	uid := uint32(os.Getuid())
	gid := uint32(os.Getgid())
	if username != "" {
		u, err := user.Lookup(username)
		if err != nil {
			return fmt.Errorf("user %s not found: %w", username, err)
		}
		parsedUID, err := strconv.ParseUint(u.Uid, 10, 32)
		if err != nil {
			return fmt.Errorf("invalid user ID for %s: %w", username, err)
		}
		uid = uint32(parsedUID)

		// Use primary group if no specific group provided
		if groupname == "" {
			parsedGID, err := strconv.ParseUint(u.Gid, 10, 32)
			if err != nil {
				return fmt.Errorf("invalid group ID for user %s: %w", username, err)
			}
			gid = uint32(parsedGID)
		}
	}

	// Parse group ID
	if groupname != "" {
		g, err := user.LookupGroup(groupname)
		if err != nil {
			return fmt.Errorf("group %s not found: %w", groupname, err)
		}
		parsedGID, err := strconv.ParseUint(g.Gid, 10, 32)
		if err != nil {
			return fmt.Errorf("invalid group ID for %s: %w", groupname, err)
		}
		gid = uint32(parsedGID)
	}

	// Set credentials while preserving existing SysProcAttr (e.g., Setpgid)
	if cmd.SysProcAttr == nil {
		cmd.SysProcAttr = &syscall.SysProcAttr{}
	}
	cmd.SysProcAttr.Credential = &syscall.Credential{
		Uid: uid,
		Gid: gid,
	}

	return nil
}
