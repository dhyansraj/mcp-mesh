# Task 9: Cross-Platform Build System and Production Deployment (2 hours)

## Overview: Critical Architecture Preservation

**⚠️ IMPORTANT**: This migration only replaces the registry service and CLI with Go. ALL Python decorator functionality must remain unchanged:

- `@mesh_agent` decorator analysis and metadata extraction (Python)
- Dependency injection and resolution (Python)
- Service discovery and proxy creation (Python)
- Auto-registration and heartbeat mechanisms (Python)

**Reference Documents**:

- `ARCHITECTURAL_CONCEPTS_AND_DEVELOPER_RULES.md` - Complete architecture overview
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/decorators/mesh_agent.py` - Core decorator implementation
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/server/registry_server.py` - Current registry API

## CRITICAL PRESERVATION REQUIREMENT

**MANDATORY**: This build system must preserve all Python code as reference and ensure complete validation.

**Reference Preservation**:

- **DO NOT DELETE** any Python packages during migration
- Keep ALL Python CLI, registry, and decorator code intact for reference
- Build system must validate Go implementation against Python reference
- Ensure Python packages remain functional during and after migration

**Code Preservation During Migration**:

- **KEEP** all Python CLI code as reference implementation
- **KEEP** all Python registry code for behavior validation
- **KEEP** all Python decorator code (unchanged functionality)
- **DOCUMENT** any unavoidable behavior differences

## Registry Deployment Flexibility

The build system must support the registry deployment architecture:

- ✅ `mcp-mesh-registry` - Standalone binary for production (Docker/K8s)
- ✅ `mcp-mesh-dev` - CLI tool with embedded registry capability
- ✅ Same registry codebase works in both deployment modes
- ✅ Future K8s/Docker deployment ready without code changes

## Objective

Set up production-ready build pipeline while preserving all Python reference code

## Detailed Sub-tasks

### 9.1: Create comprehensive Makefile with reference preservation

```makefile
.PHONY: build-all build-registry build-cli test clean validate-python-reference

# Build all Go binaries
build-all: build-registry build-cli

# Build standalone registry binary (for Docker/K8s deployment)
build-registry:
	@echo "Building standalone registry binary..."
	GOOS=linux GOARCH=amd64 go build -o bin/mcp-mesh-registry-linux-amd64 ./cmd/mcp-mesh-registry
	GOOS=darwin GOARCH=amd64 go build -o bin/mcp-mesh-registry-darwin-amd64 ./cmd/mcp-mesh-registry
	GOOS=darwin GOARCH=arm64 go build -o bin/mcp-mesh-registry-darwin-arm64 ./cmd/mcp-mesh-registry
	GOOS=windows GOARCH=amd64 go build -o bin/mcp-mesh-registry-windows-amd64.exe ./cmd/mcp-mesh-registry

# Build CLI tool with embedded registry capability (for development)
build-cli:
	@echo "Building CLI tool with embedded registry..."
	GOOS=linux GOARCH=amd64 go build -o bin/mcp-mesh-dev-linux-amd64 ./cmd/mcp-mesh-dev
	GOOS=darwin GOARCH=amd64 go build -o bin/mcp-mesh-dev-darwin-amd64 ./cmd/mcp-mesh-dev
	GOOS=darwin GOARCH=arm64 go build -o bin/mcp-mesh-dev-darwin-arm64 ./cmd/mcp-mesh-dev
	GOOS=windows GOARCH=amd64 go build -o bin/mcp-mesh-dev-windows-amd64.exe ./cmd/mcp-mesh-dev

# Comprehensive testing: Go + Python reference validation
test: validate-python-reference
	@echo "Running Go implementation tests..."
	go test ./... -v
	@echo "Running Python reference tests (must still pass)..."
	cd packages/mcp_mesh && python -m pytest -v
	cd packages/mcp_mesh_runtime && python -m pytest -v
	@echo "Running integration tests: Go backend + Python decorators..."
	./test/integration/test_go_python_integration.sh

# CRITICAL: Validate Python reference code remains functional
validate-python-reference:
	@echo "Validating Python reference implementation..."
	@python -c "import packages.mcp_mesh.src.mcp_mesh as mesh; print('✅ Python mcp_mesh package intact')"
	@python -c "import packages.mcp_mesh_runtime.src.mcp_mesh_runtime as runtime; print('✅ Python mcp_mesh_runtime package intact')"
	@python packages/mcp_mesh_runtime/src/mcp_mesh_runtime/cli/main.py --help > /dev/null && echo "✅ Python CLI functional"

# Test deployment flexibility
test-deployment-modes:
	@echo "Testing registry deployment flexibility..."
	# Test standalone registry
	./bin/mcp-mesh-registry-linux-amd64 --help
	# Test CLI with embedded registry
	./bin/mcp-mesh-dev-linux-amd64 start --registry-only --help

clean:
	rm -rf bin/
	@echo "Preserved all Python reference code (not deleted)"
```

### 9.2: Create Docker images with deployment flexibility

```dockerfile
# docker/registry.Dockerfile - Standalone registry for production
FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o mcp-mesh-registry ./cmd/mcp-mesh-registry

FROM scratch
COPY --from=builder /app/mcp-mesh-registry .
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
EXPOSE 8080
CMD ["./mcp-mesh-registry"]

# docker/cli.Dockerfile - CLI tool for development
FROM golang:1.21-alpine AS go-builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o mcp-mesh-dev ./cmd/mcp-mesh-dev

FROM python:3.11-alpine
RUN apk add --no-cache curl
COPY --from=go-builder /app/mcp-mesh-dev /usr/local/bin/
COPY packages/ /app/packages/
COPY examples/ /app/examples/
WORKDIR /app
RUN pip install -e packages/mcp_mesh/ -e packages/mcp_mesh_runtime/
EXPOSE 8080
CMD ["mcp-mesh-dev", "start", "--registry-only"]
```

### 9.3: Create integration test suite for Go + Python validation

```bash
#!/bin/bash
# test/integration/test_go_python_integration.sh

echo "🔍 Testing Go registry + Python decorators integration..."

# Start Go registry
./bin/mcp-mesh-dev start --registry-only &
REGISTRY_PID=$!
sleep 2

# Test Python agent registration with Go registry
echo "🐍 Testing Python agent with Go registry..."
timeout 10 python examples/hello_world.py &
AGENT_PID=$!
sleep 5

# Verify registration
curl -s http://localhost:8080/agents | grep -q "hello-world-demo"
if [ $? -eq 0 ]; then
    echo "✅ Python agent registered with Go registry"
else
    echo "❌ Python agent failed to register with Go registry"
    exit 1
fi

# Cleanup
kill $AGENT_PID $REGISTRY_PID
echo "✅ Integration test passed: Go registry + Python decorators work together"
```

### 9.4: Create deployment mode validation

```bash
#!/bin/bash
# test/deployment/test_deployment_flexibility.sh

echo "🚀 Testing registry deployment flexibility..."

# Test 1: Standalone registry binary
echo "📦 Testing standalone registry binary..."
./bin/mcp-mesh-registry &
STANDALONE_PID=$!
sleep 2

curl -s http://localhost:8080/health | grep -q "ok"
if [ $? -eq 0 ]; then
    echo "✅ Standalone registry binary works"
else
    echo "❌ Standalone registry binary failed"
    exit 1
fi
kill $STANDALONE_PID

# Test 2: CLI embedded registry
echo "🛠️ Testing CLI embedded registry..."
./bin/mcp-mesh-dev start --registry-only &
CLI_PID=$!
sleep 2

curl -s http://localhost:8080/health | grep -q "ok"
if [ $? -eq 0 ]; then
    echo "✅ CLI embedded registry works"
else
    echo "❌ CLI embedded registry failed"
    exit 1
fi
kill $CLI_PID

echo "✅ Deployment flexibility validated: same registry code works in both modes"
```

### 9.5: Create CI/CD pipeline configuration

```yaml
# .github/workflows/go-migration-validation.yml
name: Go Migration Validation

on:
  push:
    branches: [main, alpha-*]
  pull_request:
    branches: [main]

jobs:
  validate-python-reference:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - name: Install Python dependencies
        run: |
          pip install -e packages/mcp_mesh/
          pip install -e packages/mcp_mesh_runtime/
          pip install pytest
      - name: Validate Python reference still works
        run: |
          python -c "import packages.mcp_mesh.src.mcp_mesh; print('✅ mcp_mesh import success')"
          python -c "import packages.mcp_mesh_runtime.src.mcp_mesh_runtime; print('✅ mcp_mesh_runtime import success')"
          cd packages/mcp_mesh && python -m pytest
          cd ../mcp_mesh_runtime && python -m pytest

  build-go-binaries:
    runs-on: ubuntu-latest
    needs: validate-python-reference
    steps:
      - uses: actions/checkout@v3
      - name: Set up Go
        uses: actions/setup-go@v4
        with:
          go-version: "1.21"
      - name: Build cross-platform binaries
        run: |
          make build-all
      - name: Upload artifacts
        uses: actions/upload-artifact@v3
        with:
          name: go-binaries
          path: bin/

  integration-testing:
    runs-on: ubuntu-latest
    needs: build-go-binaries
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - name: Set up Go
        uses: actions/setup-go@v4
        with:
          go-version: "1.21"
      - name: Download Go binaries
        uses: actions/download-artifact@v3
        with:
          name: go-binaries
          path: bin/
      - name: Make binaries executable
        run: chmod +x bin/*
      - name: Install Python dependencies
        run: |
          pip install -e packages/mcp_mesh/
          pip install -e packages/mcp_mesh_runtime/
      - name: Run integration tests
        run: |
          make test
          ./test/integration/test_go_python_integration.sh
          ./test/deployment/test_deployment_flexibility.sh

  docker-build:
    runs-on: ubuntu-latest
    needs: integration-testing
    steps:
      - uses: actions/checkout@v3
      - name: Build Docker images
        run: |
          docker build -f docker/registry.Dockerfile -t mcp-mesh-registry:latest .
          docker build -f docker/cli.Dockerfile -t mcp-mesh-cli:latest .
      - name: Test Docker images
        run: |
          docker run --rm -d --name test-registry -p 8080:8080 mcp-mesh-registry:latest
          sleep 5
          curl -f http://localhost:8080/health
          docker stop test-registry
```

### 9.6: Create load testing and performance validation

```bash
#!/bin/bash
# test/performance/test_load_performance.sh

echo "⚡ Load testing Go registry performance (target: 10x improvement)..."

# Start Go registry
./bin/mcp-mesh-dev start --registry-only &
REG_PID=$!
sleep 3

# Test 1: Concurrent agent registrations
echo "📊 Testing 50 concurrent agent registrations..."
START_TIME=$(date +%s%N)

for i in {1..50}; do
    (
        timeout 30 python examples/hello_world.py
    ) &
done

wait

END_TIME=$(date +%s%N)
TOTAL_TIME=$((($END_TIME - $START_TIME) / 1000000))
echo "✅ 50 agent registrations completed in: ${TOTAL_TIME}ms"
echo "📊 Average per agent: $((TOTAL_TIME / 50))ms"

# Test 2: API throughput
echo "📊 Testing API request throughput..."
START_API=$(date +%s%N)

for i in {1..1000}; do
    curl -s http://localhost:8080/agents >/dev/null &
    if [ $((i % 100)) -eq 0 ]; then
        wait
    fi
done
wait

END_API=$(date +%s%N)
API_TIME=$((($END_API - $START_API) / 1000000))
echo "✅ 1000 API requests completed in: ${API_TIME}ms"
echo "📊 Requests per second: $((1000 * 1000 / API_TIME))"

# Test 3: Memory usage under load
MEMORY_USAGE=$(ps -o rss= -p $REG_PID)
echo "📊 Memory usage under load: ${MEMORY_USAGE}KB"

if [ $MEMORY_USAGE -lt 51200 ]; then
    echo "✅ Memory usage within target (<50MB)"
else
    echo "⚠️ Memory usage above target (${MEMORY_USAGE}KB > 50MB)"
fi

# Cleanup
kill $REG_PID
echo "✅ Load testing completed"
```

## Success Criteria

- [ ] Cross-platform binaries build successfully for all target platforms (Linux, macOS, Windows)
- [ ] Makefile provides easy build automation for development and CI/CD
- [ ] Docker images are optimized and production-ready (<50MB for registry)
- [ ] All tests (Go and Python) run successfully in build pipeline
- [ ] **CRITICAL**: Python reference code remains functional and preserved
- [ ] **CRITICAL**: Go + Python integration tests pass (decorators work with Go registry)
- [ ] **CRITICAL**: Registry deployment flexibility validated (standalone + embedded modes)
- [ ] **CRITICAL**: Build system validates Python reference against Go implementation
- [ ] **CRITICAL**: No Python code deleted during migration process
- [ ] **CRITICAL**: CI/CD pipeline validates compatibility on every commit
- [ ] **CRITICAL**: Load testing demonstrates 10x performance improvement
- [ ] **CRITICAL**: Memory usage targets achieved (50% reduction)
