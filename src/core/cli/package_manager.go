package cli

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// EnsureMcpMeshRuntime checks if mcp-mesh-runtime is available and offers installation
func EnsureMcpMeshRuntime(env *PythonEnvironment) error {
	if env.HasMcpMeshRuntime {
		fmt.Printf("✅ mcp-mesh-runtime found and ready\n")
		return nil
	}

	// Interactive installation prompt
	fmt.Printf("⚠️  mcp-mesh-runtime not found in Python environment\n")
	fmt.Printf("📦 Required packages: mcp, mcp-mesh, mcp-mesh-runtime\n")
	fmt.Printf("📍 Python environment: %s\n", env.PythonExecutable)

	if env.IsVirtualEnv {
		fmt.Printf("🔧 Virtual environment detected - packages will be installed locally\n")
		fmt.Printf("📁 Virtual environment path: %s\n", env.VenvPath)
	} else {
		fmt.Printf("🌐 System Python detected - packages will be installed globally\n")
	}

	fmt.Printf("\nOptions:\n")
	fmt.Printf("  i - Install packages automatically\n")
	fmt.Printf("  c - Continue without packages (agent may not connect to registry)\n")
	fmt.Printf("  q - Quit\n")
	fmt.Printf("Choice [i/c/q]: ")

	reader := bufio.NewReader(os.Stdin)
	input, _ := reader.ReadString('\n')
	choice := strings.TrimSpace(strings.ToLower(input))

	switch choice {
	case "i", "": // Default to install
		return installMcpMeshRuntime(env.PythonExecutable)
	case "c":
		fmt.Printf("⚠️  Continuing without mcp-mesh-runtime - agent may not connect to registry\n")
		return nil
	case "q":
		return fmt.Errorf("installation cancelled by user")
	default:
		fmt.Printf("Invalid choice. Continuing without installation.\n")
		return nil
	}
}

func installMcpMeshRuntime(pythonExec string) error {
	fmt.Printf("📦 Installing mcp-mesh-runtime and dependencies...\n")

	// For now, just install MCP (the base package that exists)
	// In a real implementation, mcp-mesh and mcp-mesh-runtime would be published packages
	packages := []string{"mcp"}

	for i, pkg := range packages {
		fmt.Printf("Installing %s (%d/%d)...\n", pkg, i+1, len(packages))

		cmd := exec.Command(pythonExec, "-m", "pip", "install", pkg)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr

		if err := cmd.Run(); err != nil {
			fmt.Printf("⚠️ Failed to install %s: %v\n", pkg, err)
			fmt.Printf("💡 You may need to install MCP packages manually\n")
			// Don't return error - continue gracefully
		}
	}

	fmt.Printf("✅ Package installation attempt complete.\n")
	fmt.Printf("💡 Note: mcp-mesh and mcp-mesh-runtime are development packages\n")
	return nil
}

// CheckPackageAvailability checks if a specific package is available
func CheckPackageAvailability(pythonExec, packageName string) bool {
	cmd := exec.Command(pythonExec, "-c", fmt.Sprintf("import %s", packageName))
	return cmd.Run() == nil
}

// InstallPackage installs a single package
func InstallPackage(pythonExec, packageName string) error {
	fmt.Printf("📦 Installing %s...\n", packageName)

	cmd := exec.Command(pythonExec, "-m", "pip", "install", packageName)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("failed to install %s: %w", packageName, err)
	}

	fmt.Printf("✅ %s installed successfully.\n", packageName)
	return nil
}

// findSystemPython finds a Python executable in the system PATH.
// Used for creating new virtual environments.
func findSystemPython() (string, error) {
	candidates := []string{"python3", "python"}
	for _, candidate := range candidates {
		if path, err := exec.LookPath(candidate); err == nil {
			return path, nil
		}
	}
	return "", fmt.Errorf("no Python executable found in PATH")
}

// CreateVirtualEnvironment creates a new virtual environment
func CreateVirtualEnvironment(venvPath string) error {
	fmt.Printf("🔧 Creating virtual environment at %s...\n", venvPath)

	// Find system Python
	pythonExec, err := findSystemPython()
	if err != nil {
		return fmt.Errorf("failed to find system Python: %w", err)
	}

	// Create virtual environment
	cmd := exec.Command(pythonExec, "-m", "venv", venvPath)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("failed to create virtual environment: %w", err)
	}

	fmt.Printf("✅ Virtual environment created successfully at %s\n", venvPath)
	return nil
}

// ActivateVirtualEnvironment provides instructions for activating venv
func ActivateVirtualEnvironment(venvPath string) {
	fmt.Printf("\n🔧 To activate the virtual environment:\n")
	if strings.Contains(os.Getenv("OS"), "Windows") {
		fmt.Printf("   %s\\Scripts\\activate\n", venvPath)
	} else {
		fmt.Printf("   source %s/bin/activate\n", venvPath)
	}
	fmt.Printf("\n")
}
