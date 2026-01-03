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

// DetectPythonEnvironment finds the Python environment to use.
// Strictly requires .venv in current directory - no fallback to system Python.
func DetectPythonEnvironment() (*PythonEnvironment, error) {
	env := &PythonEnvironment{}

	// Strictly require .venv in current directory - no fallback
	venvPython := detectVirtualEnv()
	if venvPython == "" {
		cwd, _ := os.Getwd()
		return nil, fmt.Errorf("virtual environment not found at %s/.venv", cwd)
	}

	env.PythonExecutable = venvPython
	env.IsVirtualEnv = true
	env.VenvPath = ".venv"
	fmt.Printf("🐍 Using virtual environment: %s\n", venvPython)

	// Verify Python version (require >= 3.11)
	version, err := getPythonVersion(env.PythonExecutable)
	if err != nil {
		return nil, fmt.Errorf("failed to get Python version: %w", err)
	}
	env.Version = version

	if !isValidPythonVersion(version) {
		return nil, fmt.Errorf("Python %s detected. MCP Mesh requires Python 3.11+", version)
	}

	// Check for mcp-mesh-runtime availability
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
	// Version check - require 3.11+ (per pyproject.toml requires-python = ">=3.11")
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

	return major == 3 && minor >= 11
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
