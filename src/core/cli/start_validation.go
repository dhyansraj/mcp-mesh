package cli

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"mcp-mesh/src/core/cli/handlers"
)

// PrerequisiteError represents a failed prerequisite check with remediation info
type PrerequisiteError struct {
	Check       string
	Message     string
	Remediation string
}

func (e *PrerequisiteError) Error() string {
	return e.Message
}

// runPrerequisiteValidation validates agent prerequisites and displays errors.
// Extracted to avoid duplication between startStandardMode and startConnectOnlyMode.
func runPrerequisiteValidation(agentPaths []string, quiet bool) error {
	if err := validateAgentPrerequisites(agentPaths, quiet); err != nil {
		if prereqErr, ok := err.(*PrerequisiteError); ok {
			fmt.Printf("\n❌ Prerequisite check failed: %s\n\n", prereqErr.Check)
			fmt.Printf("%s\n\n", prereqErr.Message)
			fmt.Printf("%s\n", prereqErr.Remediation)
			return fmt.Errorf("prerequisite check failed")
		}
		return err
	}
	return nil
}

// validateAgentPrerequisites performs upfront validation of all prerequisites
// before spawning any agents. Returns nil if all checks pass.
func validateAgentPrerequisites(agentPaths []string, quiet bool) error {
	if !quiet {
		fmt.Println("Validating prerequisites...")
	}

	// Group agents by language using handlers package
	var pythonAgents []string
	var tsAgents []string
	var javaAgents []string
	for _, agentPath := range agentPaths {
		handler := handlers.DetectLanguage(agentPath)
		lang := handler.Language()
		switch lang {
		case langPython:
			pythonAgents = append(pythonAgents, agentPath)
		case langTypeScript:
			tsAgents = append(tsAgents, agentPath)
		case langJava:
			javaAgents = append(javaAgents, agentPath)
		default:
			return &PrerequisiteError{
				Check:   "Agent file",
				Message: fmt.Sprintf("Unknown file type: %s", agentPath),
				Remediation: `MCP Mesh supports .py, .ts, .js, .java, and .jar files.
Use 'meshctl scaffold' to generate a new agent.`,
			}
		}
	}

	// Validate Python prerequisites if we have Python agents
	var pythonEnv *PythonEnvironment
	if len(pythonAgents) > 0 {
		var err error
		pythonEnv, err = DetectPythonEnvironment()
		if err != nil {
			cwd, _ := os.Getwd()
			return &PrerequisiteError{
				Check:   "Python environment",
				Message: fmt.Sprintf("Python environment check failed: %v", err),
				Remediation: fmt.Sprintf(`MCP Mesh requires a .venv directory in your current working directory.

Current directory: %s

To fix this issue:
  1. Navigate to your project directory (where your agents are)
  2. Create a virtual environment: python3.11 -m venv .venv
  3. Activate it: source .venv/bin/activate
  4. Install mcp-mesh: pip install mcp-mesh
  5. Run meshctl start from this directory

Run 'meshctl man prerequisite' for detailed setup instructions.`, cwd),
			}
		}

		// Check for mcp-mesh package
		if !checkMcpMeshPackage(pythonEnv.PythonExecutable) {
			return &PrerequisiteError{
				Check:   "mcp-mesh package",
				Message: "mcp-mesh package not found in Python environment.",
				Remediation: fmt.Sprintf(`To fix this issue:
  1. Activate your virtual environment (if using one)
  2. Install the mcp-mesh package:
     %s -m pip install mcp-mesh

Run 'meshctl man prerequisite' for detailed setup instructions.`, pythonEnv.PythonExecutable),
			}
		}
	}

	// Validate TypeScript prerequisites if we have TypeScript agents
	if len(tsAgents) > 0 {
		if err := validateTypeScriptPrerequisites(tsAgents, quiet); err != nil {
			return err
		}
	}

	// Validate Java prerequisites if we have Java agents
	if len(javaAgents) > 0 {
		if err := validateJavaPrerequisites(javaAgents, quiet); err != nil {
			return err
		}
	}

	// Validate agent file/directory paths exist
	for _, agentPath := range agentPaths {
		absPath, err := AbsolutePath(agentPath)
		if err != nil {
			return &PrerequisiteError{
				Check:   "Agent path",
				Message: fmt.Sprintf("Invalid agent path: %s", agentPath),
				Remediation: `To fix this issue:
  1. Verify the agent file/directory exists at the specified path
  2. Use an absolute path or ensure the relative path is correct from your current directory
  3. Check file permissions`,
			}
		}

		// Check if path exists (file or directory - Java agents use directories)
		if _, err := os.Stat(absPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "Agent path",
				Message: fmt.Sprintf("Agent path not found: %s", absPath),
				Remediation: fmt.Sprintf(`To fix this issue:
  1. Verify the path exists: ls -la %s
  2. Check if you're in the correct directory
  3. Create the agent or use 'meshctl scaffold' to generate one`, absPath),
			}
		}
	}

	if !quiet {
		fmt.Printf("✅ All prerequisites validated successfully\n")
		if pythonEnv != nil {
			fmt.Printf("   Python: %s (%s)\n", pythonEnv.Version, pythonEnv.PythonExecutable)
			if pythonEnv.IsVirtualEnv {
				fmt.Printf("   Virtual environment: %s\n", pythonEnv.VenvPath)
			}
		}
		if len(tsAgents) > 0 {
			fmt.Printf("   TypeScript: node_modules with @mcpmesh/sdk\n")
		}
		if len(javaAgents) > 0 {
			fmt.Printf("   Java: Maven project with mcp-mesh-spring-boot-starter\n")
		}
	}

	return nil
}

// validateTypeScriptPrerequisites checks TypeScript-specific requirements
// Checks each agent's directory for node_modules and @mcpmesh/sdk
func validateTypeScriptPrerequisites(agentPaths []string, quiet bool) error {
	// 1. Check npx is available (for running tsx)
	if _, err := exec.LookPath("npx"); err != nil {
		return &PrerequisiteError{
			Check:   "npx command",
			Message: "npx command not found.",
			Remediation: `npx is required to run TypeScript agents.

To fix this issue:
  1. Install Node.js (v18+) which includes npx
  2. Verify installation: npx --version`,
		}
	}

	// 2. Check each agent's directory for node_modules and @mcpmesh/sdk
	for _, agentPath := range agentPaths {
		absPath, err := AbsolutePath(agentPath)
		if err != nil {
			return &PrerequisiteError{
				Check:   "Agent file path",
				Message: fmt.Sprintf("Invalid agent path: %s", agentPath),
				Remediation: fmt.Sprintf(`The specified agent path could not be resolved.

Agent: %s

To fix this issue:
  1. Verify the path is correct
  2. Use an absolute path or a path relative to the current directory
  3. Run meshctl start again`, agentPath),
			}
		}

		// Check agent file exists BEFORE walking up directories
		if _, err := os.Stat(absPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "Agent file",
				Message: fmt.Sprintf("Agent file not found: %s", absPath),
				Remediation: fmt.Sprintf(`The specified TypeScript agent file does not exist.

Agent: %s

To fix this issue:
  1. Verify the file path is correct
  2. Ensure you're running meshctl from the correct directory
  3. Check that the agent file has been created
  4. Run meshctl start again`, agentPath),
			}
		}

		// Find project root by looking for node_modules or package.json
		agentDir := filepath.Dir(absPath)
		projectDir := findNodeProjectRoot(agentDir)
		if projectDir == "" {
			return &PrerequisiteError{
				Check:   "Node.js project",
				Message: fmt.Sprintf("No package.json or node_modules found for agent: %s", agentPath),
				Remediation: fmt.Sprintf(`MCP Mesh TypeScript agents require a Node.js project setup.

Agent: %s

To fix this issue:
  1. Navigate to the agent's project directory
  2. Run: npm init -y
  3. Install dependencies: npm install @mcpmesh/sdk
  4. Run meshctl start again`, agentPath),
			}
		}

		// Check node_modules exists
		nodeModulesPath := filepath.Join(projectDir, "node_modules")
		if _, err := os.Stat(nodeModulesPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "Node.js dependencies",
				Message: fmt.Sprintf("node_modules not found in: %s", projectDir),
				Remediation: fmt.Sprintf(`MCP Mesh TypeScript agents require npm dependencies.

Project: %s

To fix this issue:
  1. Navigate to: %s
  2. Install dependencies: npm install
  3. Run meshctl start again`, projectDir, projectDir),
			}
		}

		// Check @mcpmesh/sdk is installed
		sdkPath := filepath.Join(nodeModulesPath, "@mcpmesh", "sdk")
		if _, err := os.Stat(sdkPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "@mcpmesh/sdk package",
				Message: fmt.Sprintf("@mcpmesh/sdk not found in: %s", projectDir),
				Remediation: fmt.Sprintf(`To fix this issue:
  1. Navigate to: %s
  2. Install the package: npm install @mcpmesh/sdk
  3. Run meshctl start again`, projectDir),
			}
		}
	}

	return nil
}

// validateJavaPrerequisites checks Java-specific requirements
// Checks for Java 17+ and Maven installation
func validateJavaPrerequisites(agentPaths []string, quiet bool) error {
	// 1. Check Java is available
	javaPath, err := exec.LookPath("java")
	if err != nil {
		return &PrerequisiteError{
			Check:   "java command",
			Message: "java command not found.",
			Remediation: `Java 17+ is required to run Java agents.

To fix this issue:
  1. Install JDK 17+ from https://adoptium.net/
  2. Verify installation: java -version`,
		}
	}

	// 2. Check Java version is 17+
	javaVersion, err := getJavaMajorVersion()
	if err != nil {
		return &PrerequisiteError{
			Check:   "java version",
			Message: fmt.Sprintf("Could not determine Java version: %v", err),
			Remediation: `Java 17+ is required to run Java agents.

To fix this issue:
  1. Install JDK 17+ from https://adoptium.net/
  2. Verify installation: java -version`,
		}
	}

	if javaVersion < 17 {
		return &PrerequisiteError{
			Check:   "java version",
			Message: fmt.Sprintf("Java %d found, but Java 17+ is required.", javaVersion),
			Remediation: fmt.Sprintf(`Java 17+ is required to run Java agents.

Current Java: %s (version %d)

To fix this issue:
  1. Install JDK 17+ from https://adoptium.net/
  2. Update your PATH to use the new Java
  3. Verify: java -version`, javaPath, javaVersion),
		}
	}

	// 3. Check Maven is available
	if _, err := exec.LookPath("mvn"); err != nil {
		return &PrerequisiteError{
			Check:   "mvn command",
			Message: "mvn command not found.",
			Remediation: `Maven is required to build and run Java agents.

To fix this issue:
  1. Install Maven from https://maven.apache.org/
  2. Verify installation: mvn --version`,
		}
	}

	// 4. Check each agent's directory for pom.xml
	for _, agentPath := range agentPaths {
		// Handle JAR files - they don't need pom.xml
		if strings.HasSuffix(strings.ToLower(agentPath), ".jar") {
			if _, err := os.Stat(agentPath); os.IsNotExist(err) {
				return &PrerequisiteError{
					Check:   "JAR file",
					Message: fmt.Sprintf("JAR file not found: %s", agentPath),
					Remediation: fmt.Sprintf(`The specified JAR file does not exist.

JAR: %s

To fix this issue:
  1. Verify the path is correct
  2. Build the JAR: mvn package
  3. Run meshctl start again`, agentPath),
				}
			}
			continue
		}

		// For directories or pom.xml paths, check for pom.xml
		projectDir := agentPath
		if info, err := os.Stat(agentPath); err == nil && !info.IsDir() {
			projectDir = filepath.Dir(agentPath)
		}

		pomPath := filepath.Join(projectDir, "pom.xml")
		if _, err := os.Stat(pomPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "Maven project",
				Message: fmt.Sprintf("pom.xml not found in: %s", projectDir),
				Remediation: fmt.Sprintf(`MCP Mesh Java agents require a Maven project with pom.xml.

Project: %s

To fix this issue:
  1. Ensure the path points to a Maven project
  2. Verify pom.xml exists in the project root
  3. Run meshctl start again`, projectDir),
			}
		}
	}

	return nil
}

// getJavaMajorVersion returns the major Java version (e.g., 17, 21)
func getJavaMajorVersion() (int, error) {
	cmd := exec.Command("java", "-version")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return 0, err
	}

	// Parse version from output like:
	// openjdk version "17.0.13" 2024-10-15
	// or: java version "1.8.0_291"
	outputStr := string(output)
	versionRe := regexp.MustCompile(`version "(\d+)(?:\.(\d+))?`)
	matches := versionRe.FindStringSubmatch(outputStr)
	if len(matches) < 2 {
		return 0, fmt.Errorf("could not parse Java version from: %s", outputStr)
	}

	majorVersion, err := strconv.Atoi(matches[1])
	if err != nil {
		return 0, fmt.Errorf("invalid Java version number: %s", matches[1])
	}

	// Handle old versioning (1.8 = Java 8)
	if majorVersion == 1 && len(matches) > 2 {
		minorVersion, _ := strconv.Atoi(matches[2])
		return minorVersion, nil
	}

	return majorVersion, nil
}

// findNodeProjectRoot walks up directories to find package.json or node_modules
func findNodeProjectRoot(startDir string) string {
	dir := startDir
	for {
		// Check for package.json
		if _, err := os.Stat(filepath.Join(dir, "package.json")); err == nil {
			return dir
		}
		// Check for node_modules
		if _, err := os.Stat(filepath.Join(dir, "node_modules")); err == nil {
			return dir
		}

		// Move up one directory
		parent := filepath.Dir(dir)
		if parent == dir {
			// Reached root
			return ""
		}
		dir = parent
	}
}

// checkMcpMeshPackage checks if mcp-mesh package is installed.
// This checks for the user-facing "mcp-mesh" pip package (imports as mcp_mesh or mesh).
// Note: checkMcpMeshRuntime in python_env.go checks for mcp_mesh_runtime (the internal runtime)
// and mcp (the base MCP package). Both are needed but serve different purposes.
func checkMcpMeshPackage(pythonExec string) bool {
	// Check for mcp_mesh (the actual package)
	cmd := exec.Command(pythonExec, "-c", "import mcp_mesh")
	if cmd.Run() == nil {
		return true
	}

	// Also check for the mesh module (alternative import)
	cmd = exec.Command(pythonExec, "-c", "import mesh")
	return cmd.Run() == nil
}
