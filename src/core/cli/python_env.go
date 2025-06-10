package cli

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
)

type PythonEnvironment struct {
	PythonExecutable  string
	IsVirtualEnv      bool
	Version           string
	HasMcpMeshRuntime bool
	VenvPath          string
}

// DetectPythonEnvironment finds the best Python environment to use
func DetectPythonEnvironment() (*PythonEnvironment, error) {
	env := &PythonEnvironment{}

	// 1. Check for .venv in current directory first (highest priority)
	if venvPython := detectVirtualEnv(); venvPython != "" {
		env.PythonExecutable = venvPython
		env.IsVirtualEnv = true
		env.VenvPath = ".venv"
		fmt.Printf("🐍 Using virtual environment: %s\n", venvPython)
	} else {
		// 2. Fall back to system Python
		systemPython, err := findSystemPython()
		if err != nil {
			return nil, fmt.Errorf("Python not found: %w", err)
		}
		env.PythonExecutable = systemPython
		env.IsVirtualEnv = false
		fmt.Printf("🐍 Using system Python: %s\n", systemPython)
	}

	// 3. Verify Python version (require >= 3.7)
	version, err := getPythonVersion(env.PythonExecutable)
	if err != nil {
		return nil, fmt.Errorf("failed to get Python version: %w", err)
	}
	env.Version = version

	if !isValidPythonVersion(version) {
		return nil, fmt.Errorf("Python %s detected. MCP Mesh requires Python 3.7+", version)
	}

	// 4. Check for mcp-mesh-runtime availability
	env.HasMcpMeshRuntime = checkMcpMeshRuntime(env.PythonExecutable)

	return env, nil
}

func detectVirtualEnv() string {
	venvPath := ".venv"
	if !dirExists(venvPath) {
		return ""
	}

	var pythonPath string
	if runtime.GOOS == "windows" {
		pythonPath = filepath.Join(venvPath, "Scripts", "python.exe")
	} else {
		pythonPath = filepath.Join(venvPath, "bin", "python")
	}

	if fileExists(pythonPath) {
		// Convert to absolute path
		absPath, err := filepath.Abs(pythonPath)
		if err != nil {
			return ""
		}
		return absPath
	}
	return ""
}

func findSystemPython() (string, error) {
	// Try common Python executable names in order of preference
	candidates := []string{"python3", "python"}

	for _, candidate := range candidates {
		if path, err := exec.LookPath(candidate); err == nil {
			// LookPath already returns absolute path, but ensure it
			absPath, err := filepath.Abs(path)
			if err != nil {
				return path, nil // fallback to original path
			}
			return absPath, nil
		}
	}

	return "", fmt.Errorf("no Python executable found in PATH")
}

func getPythonVersion(pythonExec string) (string, error) {
	cmd := exec.Command(pythonExec, "--version")
	output, err := cmd.Output()
	if err != nil {
		return "", err
	}

	// Parse "Python 3.9.7" -> "3.9.7"
	versionStr := strings.TrimPrefix(strings.TrimSpace(string(output)), "Python ")
	return versionStr, nil
}

func isValidPythonVersion(version string) bool {
	// Simple version check - require 3.7+
	parts := strings.Split(version, ".")
	if len(parts) < 2 {
		return false
	}

	major, err := strconv.Atoi(parts[0])
	if err != nil {
		return false
	}

	minor, err := strconv.Atoi(parts[1])
	if err != nil {
		return false
	}

	return major == 3 && minor >= 7
}

func checkMcpMeshRuntime(pythonExec string) bool {
	// Check for mcp_mesh_runtime first (ideal)
	cmd := exec.Command(pythonExec, "-c", "import mcp_mesh_runtime")
	if cmd.Run() == nil {
		return true
	}

	// Fall back to checking for mcp (basic requirement)
	cmd = exec.Command(pythonExec, "-c", "import mcp")
	return cmd.Run() == nil
}

func dirExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
