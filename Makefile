# MCP Mesh: Of the agents, by the agents, for the agents - shall not perish from the cloud.

# Variables
REGISTRY_NAME = mcp-mesh-registry
DEV_NAME = mcp-mesh-dev
VERSION = 1.0.0
BUILD_DIR = bin
REGISTRY_CMD_DIR = cmd/mcp-mesh-registry
DEV_CMD_DIR = cmd/mcp-mesh-dev

# Go build flags
LDFLAGS = -ldflags="-s -w -X main.version=$(VERSION)"
BUILD_FLAGS = $(LDFLAGS)

# Default target
.PHONY: all
all: build

# Build for current platform
.PHONY: build
build:
	@echo "🔨 Building $(REGISTRY_NAME)..."
	@mkdir -p $(BUILD_DIR)
	go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(REGISTRY_NAME) ./$(REGISTRY_CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(REGISTRY_NAME)"
	@echo "🔨 Building $(DEV_NAME)..."
	go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(DEV_NAME) ./$(DEV_CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(DEV_NAME)"

# Build for multiple platforms
.PHONY: build-all
build-all: build-linux build-darwin build-windows

.PHONY: build-linux
build-linux:
	@echo "🔨 Building for Linux..."
	@mkdir -p $(BUILD_DIR)
	GOOS=linux GOARCH=amd64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(REGISTRY_NAME)-linux-amd64 ./$(REGISTRY_CMD_DIR)
	GOOS=linux GOARCH=amd64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(DEV_NAME)-linux-amd64 ./$(DEV_CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(REGISTRY_NAME)-linux-amd64 and $(BUILD_DIR)/$(DEV_NAME)-linux-amd64"

.PHONY: build-darwin
build-darwin:
	@echo "🔨 Building for macOS..."
	@mkdir -p $(BUILD_DIR)
	GOOS=darwin GOARCH=amd64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(REGISTRY_NAME)-darwin-amd64 ./$(REGISTRY_CMD_DIR)
	GOOS=darwin GOARCH=arm64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(REGISTRY_NAME)-darwin-arm64 ./$(REGISTRY_CMD_DIR)
	GOOS=darwin GOARCH=amd64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(DEV_NAME)-darwin-amd64 ./$(DEV_CMD_DIR)
	GOOS=darwin GOARCH=arm64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(DEV_NAME)-darwin-arm64 ./$(DEV_CMD_DIR)
	@echo "✅ Built binaries for macOS (amd64 and arm64)"

.PHONY: build-windows
build-windows:
	@echo "🔨 Building for Windows..."
	@mkdir -p $(BUILD_DIR)
	GOOS=windows GOARCH=amd64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(REGISTRY_NAME)-windows-amd64.exe ./$(REGISTRY_CMD_DIR)
	GOOS=windows GOARCH=amd64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(DEV_NAME)-windows-amd64.exe ./$(DEV_CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(REGISTRY_NAME)-windows-amd64.exe and $(BUILD_DIR)/$(DEV_NAME)-windows-amd64.exe"

# Development build (no optimizations, includes debug info)
.PHONY: build-dev
build-dev:
	@echo "🔨 Building development versions..."
	@mkdir -p $(BUILD_DIR)
	go build -race -o $(BUILD_DIR)/$(REGISTRY_NAME)-debug ./$(REGISTRY_CMD_DIR)
	go build -race -o $(BUILD_DIR)/$(DEV_NAME)-debug ./$(DEV_CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(REGISTRY_NAME)-debug and $(BUILD_DIR)/$(DEV_NAME)-debug"

# Run the registry
.PHONY: run
run: build
	@echo "🚀 Starting $(REGISTRY_NAME)..."
	./$(BUILD_DIR)/$(REGISTRY_NAME)

# Run in development mode
.PHONY: run-dev
run-dev: build-dev
	@echo "🚀 Starting $(REGISTRY_NAME) in development mode..."
	./$(BUILD_DIR)/$(REGISTRY_NAME)-debug

# Run tests
.PHONY: test
test:
	@echo "🧪 Running tests..."
	go test -v ./...

# Run tests with coverage
.PHONY: test-coverage
test-coverage:
	@echo "🧪 Running tests with coverage..."
	go test -v -coverprofile=coverage.out ./...
	go tool cover -html=coverage.out -o coverage.html
	@echo "📊 Coverage report generated: coverage.html"

# Run tests in race condition detection mode
.PHONY: test-race
test-race:
	@echo "🧪 Running tests with race detection..."
	go test -race -v ./...

# Lint code
.PHONY: lint
lint:
	@echo "🔍 Linting code..."
	@if command -v golangci-lint >/dev/null 2>&1; then \
		golangci-lint run; \
	else \
		echo "⚠️  golangci-lint not installed. Install with: go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest"; \
		go vet ./...; \
		go fmt ./...; \
	fi

# Format code
.PHONY: fmt
fmt:
	@echo "📝 Formatting code..."
	go fmt ./...

# Check formatting
.PHONY: fmt-check
fmt-check:
	@echo "📝 Checking code formatting..."
	@if [ -n "$(shell gofmt -l .)" ]; then \
		echo "❌ Code is not formatted. Run 'make fmt' to fix."; \
		gofmt -l .; \
		exit 1; \
	else \
		echo "✅ Code is properly formatted."; \
	fi

# Generate Go modules
.PHONY: mod-init
mod-init:
	@echo "📦 Initializing Go modules..."
	go mod init mcp-mesh

# Tidy Go modules
.PHONY: mod-tidy
mod-tidy:
	@echo "📦 Tidying Go modules..."
	go mod tidy

# Download dependencies
.PHONY: deps
deps:
	@echo "📦 Downloading dependencies..."
	go mod download

# Clean build artifacts and database files
.PHONY: clean
clean:
	@echo "🧹 Cleaning build artifacts..."
	rm -rf $(BUILD_DIR)
	rm -f coverage.out coverage.html
	# Clean binaries from project root (created by direct go build)
	rm -f $(REGISTRY_NAME) $(DEV_NAME)
	# Clean any stray binaries in cmd directories
	rm -f $(REGISTRY_CMD_DIR)/$(REGISTRY_NAME)
	rm -f $(DEV_CMD_DIR)/$(DEV_NAME)
	# Clean database files (SQLite main + WAL/SHM files)
	rm -f *.db *.db-shm *.db-wal
	@echo "✅ Cleaned build artifacts"

# Deep clean - removes all generated files, Python cache, and databases
.PHONY: clean-all
clean-all:
	@echo "⚠️  WARNING: This will remove:"
	@echo "  - Build artifacts ($(BUILD_DIR)/)"
	@echo "  - Binaries from project root ($(REGISTRY_NAME), $(DEV_NAME))"
	@echo "  - Python cache (__pycache__, *.pyc, .pytest_cache)"
	@echo "  - Database files (*.db)"
	@echo "  - Coverage reports"
	@echo "  - Log files (*.log)"
	@echo ""
	@echo "Press Ctrl+C to cancel or Enter to continue..."
	@read confirm
	$(MAKE) clean-all-force

# Force deep clean without confirmation
.PHONY: clean-all-force
clean-all-force:
	@echo "🧹 Deep cleaning..."
	# Go build artifacts
	rm -rf $(BUILD_DIR)
	# Binaries from project root (created by direct go build)
	rm -f $(REGISTRY_NAME) $(DEV_NAME)
	# Clean any stray binaries in cmd directories
	rm -f $(REGISTRY_CMD_DIR)/$(REGISTRY_NAME)
	rm -f $(DEV_CMD_DIR)/$(DEV_NAME)
	# Python cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	# Database files
	find . -maxdepth 2 -name "*.db" -delete 2>/dev/null || true
	# Coverage and test artifacts
	rm -f coverage.out coverage.html .coverage
	# Log files
	find . -maxdepth 2 -name "*.log" -delete 2>/dev/null || true
	# Process state files
	rm -f mcp_mesh_dev.pid .mcp_mesh_state.json
	@echo "✅ Deep clean complete"

# Quick install for users (usage-focused)
.PHONY: install
install: build install-python-user
	@echo "📥 Installing binaries to /usr/local/bin..."
	@echo "Note: This may require sudo privileges"
	@if [ -w /usr/local/bin ]; then \
		cp $(BUILD_DIR)/$(REGISTRY_NAME) /usr/local/bin/; \
		cp $(BUILD_DIR)/$(DEV_NAME) /usr/local/bin/; \
	else \
		echo "⚠️  Need sudo to install to /usr/local/bin"; \
		sudo cp $(BUILD_DIR)/$(REGISTRY_NAME) /usr/local/bin/; \
		sudo cp $(BUILD_DIR)/$(DEV_NAME) /usr/local/bin/; \
	fi
	@echo "✅ Installation complete!"
	@echo ""
	@echo "🚀 Next steps:"
	@echo "  1. Activate the virtual environment:"
	@echo "     source .venv/bin/activate"
	@echo "  2. Test the installation:"
	@echo "     mcp-mesh-dev --version"
	@echo "  3. Run your first agent:"
	@echo "     mcp-mesh-dev start examples/hello_world.py"

# Install Python package for users (always use .venv)
.PHONY: install-python-user
install-python-user:
	@echo "🐍 Setting up Python environment in .venv..."
	@if [ ! -d ".venv" ]; then \
		echo "🆕 Creating virtual environment in .venv..."; \
		python3 -m venv .venv || (echo "❌ Failed to create venv. Please install python3-venv" && exit 1); \
	fi
	@echo "📦 Installing Python package in .venv..."
	@.venv/bin/pip install --upgrade pip --quiet
	@.venv/bin/pip install src/runtime/python/
	@echo "✅ Python package installed in .venv"

# Development installation - editable Python package + Go binaries
.PHONY: install-dev
install-dev: build
	@echo "🔧 Setting up development environment..."
	# Create .venv if it doesn't exist
	@if [ ! -d ".venv" ]; then \
		echo "🆕 Creating virtual environment in .venv..."; \
		python3 -m venv .venv || (echo "❌ Failed to create venv. Please install python3-venv" && exit 1); \
	fi
	# Install Python package in editable mode
	@echo "📦 Installing Python package in editable mode..."
	@.venv/bin/pip install --upgrade pip --quiet
	@.venv/bin/pip install -e src/runtime/python/
	# Create symlinks for binaries in development
	@echo "🔗 Creating development symlinks..."
	@mkdir -p ~/.local/bin
	ln -sf $(PWD)/$(BUILD_DIR)/$(REGISTRY_NAME) ~/.local/bin/$(REGISTRY_NAME)
	ln -sf $(PWD)/$(BUILD_DIR)/$(DEV_NAME) ~/.local/bin/$(DEV_NAME)
	@echo "✅ Development installation complete"
	@echo ""
	@echo "📝 Note: Make sure ~/.local/bin is in your PATH"
	@echo "   Add this to your shell profile if needed:"
	@echo "   export PATH=\$$HOME/.local/bin:\$$PATH"

# Install all dependencies for development
.PHONY: install-deps
install-deps:
	@echo "📦 Installing all development dependencies..."
	# Go dependencies
	@echo "🔧 Installing Go dependencies..."
	go mod download
	# Python dependencies
	@echo "🐍 Installing Python dependencies..."
	pip install -e src/runtime/python/[dev]
	# Development tools
	@echo "🛠️  Installing development tools..."
	@if ! command -v golangci-lint >/dev/null 2>&1; then
		echo "Installing golangci-lint...";
		go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest;
	fi
	@echo "✅ All dependencies installed"

# Uninstall the binaries
.PHONY: uninstall
uninstall:
	@echo "🗑️  Uninstalling binaries..."
	rm -f /usr/local/bin/$(REGISTRY_NAME)
	rm -f /usr/local/bin/$(DEV_NAME)
	@echo "✅ Uninstalled $(REGISTRY_NAME) and $(DEV_NAME)"

# Docker build
.PHONY: docker-build
docker-build:
	@echo "🐳 Building Docker image..."
	docker build -t mcp-mesh-registry:$(VERSION) .
	docker tag mcp-mesh-registry:$(VERSION) mcp-mesh-registry:latest
	@echo "✅ Built Docker image: mcp-mesh-registry:$(VERSION)"

# Run with Docker
.PHONY: docker-run
docker-run:
	@echo "🐳 Running with Docker..."
	docker run -p 8000:8000 mcp-mesh-registry:latest

# Show help
.PHONY: help
help:
	@echo "MCP Mesh: Of the agents, by the agents, for the agents - shall not perish from the cloud."
	@echo ""
	@echo "Available targets:"
	@echo "  build         - Build for current platform"
	@echo "  build-all     - Build for all platforms (Linux, macOS, Windows)"
	@echo "  build-dev     - Build development version with debug info"
	@echo "  run           - Build and run the application"
	@echo "  run-dev       - Build and run in development mode"
	@echo "  test          - Run tests"
	@echo "  test-coverage - Run tests with coverage report"
	@echo "  test-race     - Run tests with race detection"
	@echo "  lint          - Lint code (requires golangci-lint)"
	@echo "  fmt           - Format code"
	@echo "  fmt-check     - Check code formatting"
	@echo "  mod-tidy      - Tidy Go modules"
	@echo "  deps          - Download dependencies"
	@echo "  clean         - Clean build artifacts and database files"
	@echo "  clean-all     - Deep clean (removes Python cache, DBs, logs) - asks for confirmation"
	@echo "  clean-all-force - Deep clean without confirmation"
	@echo "  install       - Quick install for users (binaries + Python package)"
	@echo "  install-dev   - Development install (editable Python package + local binaries)"
	@echo "  install-deps  - Install all development dependencies"
	@echo "  uninstall     - Remove binary from /usr/local/bin"
	@echo "  docker-build  - Build Docker image"
	@echo "  docker-run    - Run with Docker"
	@echo "  help          - Show this help"
	@echo ""
	@echo "Common environment variables:"
	@echo "  MCP_MESH_REGISTRY_HOST   - Registry host (default: localhost)"
	@echo "  MCP_MESH_REGISTRY_PORT   - Registry port (default: 8080)"
	@echo "  MCP_MESH_REGISTRY_URL    - Full registry URL for agents"
	@echo "  MCP_MESH_LOG_LEVEL       - Log level (DEBUG, INFO, WARN, ERROR)"
	@echo "  MCP_MESH_AGENT_NAME      - Override agent name (adds UUID suffix)"
	@echo ""
	@echo "Examples:"
	@echo "  make install              # Quick install for users"
	@echo "  make build                # Build for current platform"
	@echo "  make run                  # Build and run"
	@echo "  make install-dev          # Set up development environment"
	@echo "  make clean-all            # Deep clean everything (with confirmation)"
	@echo "  HOST=0.0.0.0 make run     # Run on all interfaces"
	@echo "  make test                 # Run tests"
	@echo "  make docker-build         # Build Docker image"

# Show version
.PHONY: version
version:
	@echo "MCP Mesh version $(VERSION)"
	@echo "  $(REGISTRY_NAME)"
	@echo "  $(DEV_NAME)"

# Default help target
.DEFAULT_GOAL := help
