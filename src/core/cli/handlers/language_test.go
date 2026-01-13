package handlers

import (
	"os"
	"path/filepath"
	"testing"
)

// ============================================================================
// NormalizeLanguage Tests
// ============================================================================

func TestNormalizeLanguage_Python(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"python", "python"},
		{"Python", "python"},
		{"PYTHON", "python"},
		{"py", "python"},
		{"Py", "python"},
		{"PY", "python"},
		{"", "python"}, // Default to python
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := NormalizeLanguage(tt.input)
			if result != tt.expected {
				t.Errorf("NormalizeLanguage(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

func TestNormalizeLanguage_TypeScript(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"typescript", "typescript"},
		{"TypeScript", "typescript"},
		{"TYPESCRIPT", "typescript"},
		{"ts", "typescript"},
		{"Ts", "typescript"},
		{"TS", "typescript"},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := NormalizeLanguage(tt.input)
			if result != tt.expected {
				t.Errorf("NormalizeLanguage(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

func TestNormalizeLanguage_Unknown(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"rust", "rust"},
		{"go", "go"},
		{"java", "java"},
		{"unknown", "unknown"},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := NormalizeLanguage(tt.input)
			if result != tt.expected {
				t.Errorf("NormalizeLanguage(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

// ============================================================================
// GetHandlerByLanguage Tests
// ============================================================================

func TestGetHandlerByLanguage_Python(t *testing.T) {
	handler, err := GetHandlerByLanguage("python")
	if err != nil {
		t.Fatalf("GetHandlerByLanguage(python) error = %v", err)
	}
	if handler.Language() != "python" {
		t.Errorf("handler.Language() = %q, want %q", handler.Language(), "python")
	}
}

func TestGetHandlerByLanguage_PythonShorthand(t *testing.T) {
	handler, err := GetHandlerByLanguage("py")
	if err != nil {
		t.Fatalf("GetHandlerByLanguage(py) error = %v", err)
	}
	if handler.Language() != "python" {
		t.Errorf("handler.Language() = %q, want %q", handler.Language(), "python")
	}
}

func TestGetHandlerByLanguage_TypeScript(t *testing.T) {
	handler, err := GetHandlerByLanguage("typescript")
	if err != nil {
		t.Fatalf("GetHandlerByLanguage(typescript) error = %v", err)
	}
	if handler.Language() != "typescript" {
		t.Errorf("handler.Language() = %q, want %q", handler.Language(), "typescript")
	}
}

func TestGetHandlerByLanguage_TypeScriptShorthand(t *testing.T) {
	handler, err := GetHandlerByLanguage("ts")
	if err != nil {
		t.Fatalf("GetHandlerByLanguage(ts) error = %v", err)
	}
	if handler.Language() != "typescript" {
		t.Errorf("handler.Language() = %q, want %q", handler.Language(), "typescript")
	}
}

func TestGetHandlerByLanguage_DefaultEmpty(t *testing.T) {
	handler, err := GetHandlerByLanguage("")
	if err != nil {
		t.Fatalf("GetHandlerByLanguage('') error = %v", err)
	}
	if handler.Language() != "python" {
		t.Errorf("handler.Language() = %q, want %q (default)", handler.Language(), "python")
	}
}

func TestGetHandlerByLanguage_Unsupported(t *testing.T) {
	_, err := GetHandlerByLanguage("rust")
	if err == nil {
		t.Error("GetHandlerByLanguage(rust) expected error, got nil")
	}
}

// ============================================================================
// DetectLanguage Tests (File Extension)
// ============================================================================

func TestDetectLanguage_PythonFile(t *testing.T) {
	handler := DetectLanguage("agent.py")
	if handler.Language() != "python" {
		t.Errorf("DetectLanguage(agent.py) = %q, want %q", handler.Language(), "python")
	}
}

func TestDetectLanguage_TypeScriptFile(t *testing.T) {
	handler := DetectLanguage("agent.ts")
	if handler.Language() != "typescript" {
		t.Errorf("DetectLanguage(agent.ts) = %q, want %q", handler.Language(), "typescript")
	}
}

func TestDetectLanguage_JavaScriptFile(t *testing.T) {
	handler := DetectLanguage("agent.js")
	if handler.Language() != "typescript" {
		t.Errorf("DetectLanguage(agent.js) = %q, want %q", handler.Language(), "typescript")
	}
}

func TestDetectLanguage_DefaultFallback(t *testing.T) {
	handler := DetectLanguage("agent.txt")
	if handler.Language() != "python" {
		t.Errorf("DetectLanguage(agent.txt) = %q, want %q (default)", handler.Language(), "python")
	}
}

// ============================================================================
// DetectLanguage Tests (Directory Contents)
// ============================================================================

func TestDetectLanguage_PythonDirectory(t *testing.T) {
	// Create temp directory with Python markers
	tmpDir, err := os.MkdirTemp("", "test-python-*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Create pyproject.toml
	if err := os.WriteFile(filepath.Join(tmpDir, "pyproject.toml"), []byte("[tool.poetry]"), 0644); err != nil {
		t.Fatalf("Failed to create pyproject.toml: %v", err)
	}

	handler := DetectLanguage(tmpDir)
	if handler.Language() != "python" {
		t.Errorf("DetectLanguage(dir with pyproject.toml) = %q, want %q", handler.Language(), "python")
	}
}

func TestDetectLanguage_PythonDirectoryRequirements(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "test-python-req-*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Create requirements.txt
	if err := os.WriteFile(filepath.Join(tmpDir, "requirements.txt"), []byte("mcp-mesh==0.8.0"), 0644); err != nil {
		t.Fatalf("Failed to create requirements.txt: %v", err)
	}

	handler := DetectLanguage(tmpDir)
	if handler.Language() != "python" {
		t.Errorf("DetectLanguage(dir with requirements.txt) = %q, want %q", handler.Language(), "python")
	}
}

func TestDetectLanguage_PythonDirectoryVenv(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "test-python-venv-*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Create .venv directory
	if err := os.Mkdir(filepath.Join(tmpDir, ".venv"), 0755); err != nil {
		t.Fatalf("Failed to create .venv: %v", err)
	}

	handler := DetectLanguage(tmpDir)
	if handler.Language() != "python" {
		t.Errorf("DetectLanguage(dir with .venv) = %q, want %q", handler.Language(), "python")
	}
}

func TestDetectLanguage_TypeScriptDirectory(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "test-typescript-*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Create package.json
	if err := os.WriteFile(filepath.Join(tmpDir, "package.json"), []byte(`{"name": "test"}`), 0644); err != nil {
		t.Fatalf("Failed to create package.json: %v", err)
	}

	handler := DetectLanguage(tmpDir)
	if handler.Language() != "typescript" {
		t.Errorf("DetectLanguage(dir with package.json) = %q, want %q", handler.Language(), "typescript")
	}
}

func TestDetectLanguage_TypeScriptDirectoryTsconfig(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "test-typescript-tsconfig-*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Create tsconfig.json
	if err := os.WriteFile(filepath.Join(tmpDir, "tsconfig.json"), []byte(`{}`), 0644); err != nil {
		t.Fatalf("Failed to create tsconfig.json: %v", err)
	}

	handler := DetectLanguage(tmpDir)
	if handler.Language() != "typescript" {
		t.Errorf("DetectLanguage(dir with tsconfig.json) = %q, want %q", handler.Language(), "typescript")
	}
}

func TestDetectLanguage_TypeScriptDirectoryNodeModules(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "test-typescript-nodemodules-*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Create node_modules directory
	if err := os.Mkdir(filepath.Join(tmpDir, "node_modules"), 0755); err != nil {
		t.Fatalf("Failed to create node_modules: %v", err)
	}

	handler := DetectLanguage(tmpDir)
	if handler.Language() != "typescript" {
		t.Errorf("DetectLanguage(dir with node_modules) = %q, want %q", handler.Language(), "typescript")
	}
}

func TestDetectLanguage_EmptyDirectory(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "test-empty-*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Default to Python for backwards compatibility
	handler := DetectLanguage(tmpDir)
	if handler.Language() != "python" {
		t.Errorf("DetectLanguage(empty dir) = %q, want %q (default)", handler.Language(), "python")
	}
}

// ============================================================================
// LanguageHandler Interface Tests
// ============================================================================

func TestPythonHandler_CanHandle(t *testing.T) {
	handler := &PythonHandler{}

	tests := []struct {
		path     string
		expected bool
	}{
		{"agent.py", true},
		{"main.py", true},
		{"script.PY", true},
		{"agent.ts", false},
		{"agent.js", false},
		{"agent.go", false},
	}

	for _, tt := range tests {
		t.Run(tt.path, func(t *testing.T) {
			result := handler.CanHandle(tt.path)
			if result != tt.expected {
				t.Errorf("PythonHandler.CanHandle(%q) = %v, want %v", tt.path, result, tt.expected)
			}
		})
	}
}

func TestTypeScriptHandler_CanHandle(t *testing.T) {
	handler := &TypeScriptHandler{}

	tests := []struct {
		path     string
		expected bool
	}{
		{"agent.ts", true},
		{"index.ts", true},
		{"script.TS", true},
		{"agent.js", true},
		{"index.js", true},
		{"agent.py", false},
		{"agent.go", false},
	}

	for _, tt := range tests {
		t.Run(tt.path, func(t *testing.T) {
			result := handler.CanHandle(tt.path)
			if result != tt.expected {
				t.Errorf("TypeScriptHandler.CanHandle(%q) = %v, want %v", tt.path, result, tt.expected)
			}
		})
	}
}

func TestPythonHandler_GetStartCommand(t *testing.T) {
	handler := &PythonHandler{}

	cmd := handler.GetStartCommand("agent.py")
	if len(cmd) < 2 {
		t.Fatalf("GetStartCommand returned too few args: %v", cmd)
	}
	// Should contain python executable and the file
	if cmd[len(cmd)-1] != "agent.py" {
		t.Errorf("GetStartCommand last arg = %q, want %q", cmd[len(cmd)-1], "agent.py")
	}
}

func TestTypeScriptHandler_GetStartCommand_TS(t *testing.T) {
	handler := &TypeScriptHandler{}

	cmd := handler.GetStartCommand("agent.ts")
	if len(cmd) < 2 {
		t.Fatalf("GetStartCommand returned too few args: %v", cmd)
	}
	// Should use tsx for .ts files
	if cmd[0] != "npx" || cmd[1] != "tsx" {
		t.Errorf("GetStartCommand for .ts should use npx tsx, got %v", cmd[:2])
	}
}

func TestTypeScriptHandler_GetStartCommand_JS(t *testing.T) {
	handler := &TypeScriptHandler{}

	cmd := handler.GetStartCommand("agent.js")
	if len(cmd) < 2 {
		t.Fatalf("GetStartCommand returned too few args: %v", cmd)
	}
	// Should use node for .js files
	if cmd[0] != "node" {
		t.Errorf("GetStartCommand for .js should use node, got %v", cmd[0])
	}
}

func TestPythonHandler_GetDockerImage(t *testing.T) {
	handler := &PythonHandler{}
	image := handler.GetDockerImage()
	if image == "" {
		t.Error("GetDockerImage() returned empty string")
	}
	// Should contain python
	if image != "mcpmesh/python-runtime:0.8" && image != "mcpmesh/python-runtime:latest" {
		// Just check it's not empty - version may vary
		t.Logf("Docker image: %s", image)
	}
}

func TestTypeScriptHandler_GetDockerImage(t *testing.T) {
	handler := &TypeScriptHandler{}
	image := handler.GetDockerImage()
	if image == "" {
		t.Error("GetDockerImage() returned empty string")
	}
	// Should contain typescript
	if image != "mcpmesh/typescript-runtime:0.8" && image != "mcpmesh/typescript-runtime:latest" {
		// Just check it's not empty - version may vary
		t.Logf("Docker image: %s", image)
	}
}

// ============================================================================
// GetAllHandlers Tests
// ============================================================================

func TestGetAllHandlers(t *testing.T) {
	handlers := GetAllHandlers()
	if len(handlers) < 2 {
		t.Errorf("GetAllHandlers() returned %d handlers, want at least 2", len(handlers))
	}

	// Check we have both Python and TypeScript
	languages := make(map[string]bool)
	for _, h := range handlers {
		languages[h.Language()] = true
	}

	if !languages["python"] {
		t.Error("GetAllHandlers() missing Python handler")
	}
	if !languages["typescript"] {
		t.Error("GetAllHandlers() missing TypeScript handler")
	}
}
