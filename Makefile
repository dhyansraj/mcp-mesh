# MCP Mesh Registry - Go Implementation Makefile

# Variables
APP_NAME = mcp-mesh-registry
VERSION = 1.0.0
BUILD_DIR = build
CMD_DIR = cmd/mcp-mesh-registry

# Go build flags
LDFLAGS = -ldflags="-s -w -X main.version=$(VERSION)"
BUILD_FLAGS = $(LDFLAGS)

# Default target
.PHONY: all
all: build

# Build for current platform
.PHONY: build
build:
	@echo "🔨 Building $(APP_NAME)..."
	@mkdir -p $(BUILD_DIR)
	go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(APP_NAME) ./$(CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(APP_NAME)"

# Build for multiple platforms
.PHONY: build-all
build-all: build-linux build-darwin build-windows

.PHONY: build-linux
build-linux:
	@echo "🔨 Building for Linux..."
	@mkdir -p $(BUILD_DIR)
	GOOS=linux GOARCH=amd64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(APP_NAME)-linux-amd64 ./$(CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(APP_NAME)-linux-amd64"

.PHONY: build-darwin
build-darwin:
	@echo "🔨 Building for macOS..."
	@mkdir -p $(BUILD_DIR)
	GOOS=darwin GOARCH=amd64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(APP_NAME)-darwin-amd64 ./$(CMD_DIR)
	GOOS=darwin GOARCH=arm64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(APP_NAME)-darwin-arm64 ./$(CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(APP_NAME)-darwin-amd64 and $(BUILD_DIR)/$(APP_NAME)-darwin-arm64"

.PHONY: build-windows
build-windows:
	@echo "🔨 Building for Windows..."
	@mkdir -p $(BUILD_DIR)
	GOOS=windows GOARCH=amd64 go build $(BUILD_FLAGS) -o $(BUILD_DIR)/$(APP_NAME)-windows-amd64.exe ./$(CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(APP_NAME)-windows-amd64.exe"

# Development build (no optimizations, includes debug info)
.PHONY: build-dev
build-dev:
	@echo "🔨 Building development version..."
	@mkdir -p $(BUILD_DIR)
	go build -race -o $(BUILD_DIR)/$(APP_NAME)-dev ./$(CMD_DIR)
	@echo "✅ Built $(BUILD_DIR)/$(APP_NAME)-dev"

# Run the application
.PHONY: run
run: build
	@echo "🚀 Starting $(APP_NAME)..."
	./$(BUILD_DIR)/$(APP_NAME)

# Run in development mode
.PHONY: run-dev
run-dev: build-dev
	@echo "🚀 Starting $(APP_NAME) in development mode..."
	./$(BUILD_DIR)/$(APP_NAME)-dev

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

# Clean build artifacts
.PHONY: clean
clean:
	@echo "🧹 Cleaning build artifacts..."
	rm -rf $(BUILD_DIR)
	rm -f coverage.out coverage.html
	@echo "✅ Cleaned"

# Install the binary
.PHONY: install
install: build
	@echo "📥 Installing $(APP_NAME)..."
	cp $(BUILD_DIR)/$(APP_NAME) /usr/local/bin/
	@echo "✅ Installed $(APP_NAME) to /usr/local/bin/"

# Uninstall the binary
.PHONY: uninstall
uninstall:
	@echo "🗑️  Uninstalling $(APP_NAME)..."
	rm -f /usr/local/bin/$(APP_NAME)
	@echo "✅ Uninstalled $(APP_NAME)"

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
	@echo "MCP Mesh Registry - Go Implementation"
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
	@echo "  clean         - Clean build artifacts"
	@echo "  install       - Install binary to /usr/local/bin"
	@echo "  uninstall     - Remove binary from /usr/local/bin"
	@echo "  docker-build  - Build Docker image"
	@echo "  docker-run    - Run with Docker"
	@echo "  help          - Show this help"
	@echo ""
	@echo "Environment variables:"
	@echo "  HOST                     - Host to bind to (default: localhost)"
	@echo "  PORT                     - Port to bind to (default: 8000)"
	@echo "  DATABASE_URL             - Database connection URL"
	@echo "  LOG_LEVEL                - Log level (debug, info, warn, error)"
	@echo ""
	@echo "Examples:"
	@echo "  make build                # Build for current platform"
	@echo "  make run                  # Build and run"
	@echo "  HOST=0.0.0.0 make run     # Run on all interfaces"
	@echo "  make test                 # Run tests"
	@echo "  make docker-build         # Build Docker image"

# Show version
.PHONY: version
version:
	@echo "$(APP_NAME) version $(VERSION)"

# Default help target
.DEFAULT_GOAL := help
