#!/bin/bash
# Code Generation Script for MCP Mesh Contract-First Development
#
# This script generates:
# 1. Go server stubs from Registry OpenAPI spec
# 2. Python client from Registry OpenAPI spec
# 3. Python server stubs from Agent OpenAPI spec
#
# 🤖 AI BEHAVIOR GUIDANCE:
# This script implements dual-contract development:
# - Registry API: Go server + Python client (for agent-registry communication)
# - Agent API: Python server (for agent HTTP wrapper endpoints)
#
# WHAT THIS SCRIPT DOES:
# 1. Validates both OpenAPI specifications
# 2. Generates Go registry server handlers from registry spec
# 3. Generates Python registry client from registry spec
# 4. Generates Python agent server handlers from agent spec
# 5. Validates all generated code compiles
#
# IF THIS SCRIPT FAILS:
# - Check both OpenAPI spec syntax and schema
# - Ensure Go and Python generators are installed
# - Verify output directories exist and are writable
# - Check that generated code matches expected interfaces

set -euo pipefail

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.yaml"

# API specifications
REGISTRY_SPEC="$PROJECT_ROOT/api/mcp-mesh-registry.openapi.yaml"
AGENT_SPEC="$PROJECT_ROOT/api/mcp-mesh-agent.openapi.yaml"

# Color output functions
log_info() {
    echo "🔧 $1"
}

log_success() {
    echo "✅ $1"
}

log_error() {
    echo "❌ $1" >&2
}

log_warning() {
    echo "⚠️  $1"
}

# Validate prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if oapi-codegen is installed
    if ! command -v oapi-codegen &> /dev/null; then
        log_error "oapi-codegen not found. Install with:"
        log_error "go install github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@latest"
        exit 1
    fi

    # Check if openapi-generator is installed
    if ! command -v openapi-generator-cli &> /dev/null; then
        log_error "openapi-generator-cli not found. Install with:"
        log_error "npm install -g @openapitools/openapi-generator-cli"
        exit 1
    fi

    # Check if jq is available for JSON processing
    if ! command -v jq &> /dev/null; then
        log_warning "jq not found. Some validation features may be limited."
    fi

    log_success "Prerequisites check passed"
}

# Validate OpenAPI specification
validate_openapi_spec() {
    local spec_file="$1"
    local spec_name="$2"
    log_info "Validating $spec_name OpenAPI specification: $spec_file"

    if [[ ! -f "$spec_file" ]]; then
        log_error "$spec_name OpenAPI spec file not found: $spec_file"
        exit 1
    fi

    # Basic YAML syntax check
    if ! python3 -c "import yaml; yaml.safe_load(open('$spec_file'))" 2>/dev/null; then
        log_error "Invalid YAML syntax in $spec_file"
        exit 1
    fi

    # More detailed validation using Python openapi-spec-validator if available
    if command -v python3 &> /dev/null; then
        if python3 -c "import openapi_spec_validator" 2>/dev/null; then
            if ! python3 -c "
import yaml
from openapi_spec_validator import validate_spec
try:
    with open('$spec_file') as f:
        spec = yaml.safe_load(f)
    validate_spec(spec)
    print('✅ $spec_name OpenAPI specification is valid')
except Exception as e:
    print(f'❌ $spec_name OpenAPI validation failed: {e}')
    exit(1)
"; then
                exit 1
            fi
        else
            log_warning "openapi-spec-validator not installed. Using basic validation only."
        fi
    fi

    log_success "$spec_name OpenAPI specification validation passed"
}

# Generate Go registry server code
generate_go_registry_server() {
    local output_file="$PROJECT_ROOT/src/core/registry/generated/server.go"
    local output_dir="$(dirname "$output_file")"

    log_info "Generating Go registry server code..."

    # Create output directory if it doesn't exist
    mkdir -p "$output_dir"

    # Generate server stubs with types included
    log_info "Generating Go server with Gin bindings and types..."
    oapi-codegen \
        -generate gin-server,types,spec \
        -package generated \
        "$REGISTRY_SPEC" > "$output_file"

    # Add AI behavior guidance header
    local temp_file=$(mktemp)
    cat > "$temp_file" << 'EOF'
// 🤖 AI BEHAVIOR GUIDANCE:
// This file contains generated REGISTRY server interfaces from OpenAPI spec.
// DO NOT modify this file directly - it will be overwritten.
//
// SCOPE: Registry API endpoints for agent registration and management
//
// TO ADD NEW REGISTRY ENDPOINTS:
// 1. Update api/mcp-mesh-registry.openapi.yaml
// 2. Run: make generate
// 3. Implement business logic in handlers_impl.go
//
// GENERATED FROM: api/mcp-mesh-registry.openapi.yaml
// CONTRACT: Registry service endpoints only

EOF
    cat "$output_file" >> "$temp_file"
    mv "$temp_file" "$output_file"

    # Format the generated Go code
    if command -v gofmt &> /dev/null; then
        gofmt -w "$output_file"
    fi

    log_success "Go registry server code generated: $output_file"
}

# Generate Python registry client code
generate_python_registry_client() {
    local output_dir="$PROJECT_ROOT/src/runtime/python/src/mcp_mesh/registry_client_generated"

    log_info "Generating Python registry client code..."

    # Remove existing generated code
    if [[ -d "$output_dir" ]]; then
        log_info "Removing existing generated Python registry client..."
        rm -rf "$output_dir"
    fi

    # Create parent directory
    mkdir -p "$(dirname "$output_dir")"

    # Generate Python client using openapi-generator
    log_info "Running openapi-generator for Python registry client..."
    openapi-generator-cli generate \
        -i "$REGISTRY_SPEC" \
        -g python \
        -o "$output_dir" \
        --additional-properties=packageName=mcp_mesh_registry_client \
        --additional-properties=packageVersion=1.0.0 \
        --additional-properties=projectName=mcp-mesh-registry-client \
        --additional-properties=packageUrl=https://github.com/anthropic/mcp-mesh \
        --skip-validate-spec

    # Add AI behavior guidance to __init__.py
    local init_file="$output_dir/mcp_mesh_registry_client/__init__.py"
    if [[ -f "$init_file" ]]; then
        local temp_file=$(mktemp)
        cat > "$temp_file" << 'EOF'
"""
🤖 AI BEHAVIOR GUIDANCE:
This package contains generated Python client for MCP Mesh REGISTRY API.
DO NOT modify files in this package directly - they will be overwritten.

SCOPE: Registry API - for agents to communicate with registry service

TO USE THIS CLIENT:
1. Import: from mcp_mesh.registry_client_generated.mcp_mesh_registry_client import AgentsApi
2. Configure: api_client = ApiClient(Configuration(host="http://registry:8000"))
3. Use: agents_api = AgentsApi(api_client)

GENERATED FROM: api/mcp-mesh-registry.openapi.yaml
CONTRACT: Registry service communication only
"""

EOF
        cat "$init_file" >> "$temp_file"
        mv "$temp_file" "$init_file"
    fi

    log_success "Python registry client code generated: $output_dir"
}

# Generate Python agent server code
generate_python_agent_server() {
    local output_dir="$PROJECT_ROOT/src/runtime/python/src/mcp_mesh/agent_server_generated"

    log_info "Generating Python agent server code..."

    # Remove existing generated code
    if [[ -d "$output_dir" ]]; then
        log_info "Removing existing generated Python agent server..."
        rm -rf "$output_dir"
    fi

    # Create parent directory
    mkdir -p "$(dirname "$output_dir")"

    # Generate Python FastAPI server using openapi-generator
    log_info "Running openapi-generator for Python agent server..."
    openapi-generator-cli generate \
        -i "$AGENT_SPEC" \
        -g python-fastapi \
        -o "$output_dir" \
        --additional-properties=packageName=mcp_mesh_agent_server \
        --additional-properties=packageVersion=1.0.0 \
        --additional-properties=projectName=mcp-mesh-agent-server \
        --additional-properties=packageUrl=https://github.com/anthropic/mcp-mesh \
        --skip-validate-spec

    # Add AI behavior guidance to main module
    local main_file="$output_dir/src/openapi_server/__init__.py"
    if [[ -f "$main_file" ]]; then
        local temp_file=$(mktemp)
        cat > "$temp_file" << 'EOF'
"""
🤖 AI BEHAVIOR GUIDANCE:
This package contains generated Python server for MCP Mesh AGENT API.
DO NOT modify files in this package directly - they will be overwritten.

SCOPE: Agent API - HTTP endpoints served by Python agent HTTP wrapper

TO USE THIS SERVER:
1. Import generated handlers and models
2. Implement business logic in your HTTP wrapper
3. Register handlers with FastAPI app

GENERATED FROM: api/mcp-mesh-agent.openapi.yaml
CONTRACT: Agent HTTP wrapper endpoints only
"""

EOF
        cat "$main_file" >> "$temp_file"
        mv "$temp_file" "$main_file"
    fi

    log_success "Python agent server code generated: $output_dir"
}

# Validate generated code
validate_generated_code() {
    log_info "Validating generated code..."

    # Validate Go code compiles
    local go_file="$PROJECT_ROOT/src/core/registry/generated/server.go"
    if [[ -f "$go_file" ]]; then
        log_info "Checking Go registry code compilation..."
        if ! go build -o /dev/null "$PROJECT_ROOT/src/core/registry/..." 2>/dev/null; then
            log_error "Generated Go registry code does not compile"
            log_error "Check the business logic implementation in handlers_impl.go"
            exit 1
        fi
        log_success "Go registry code compilation check passed"
    fi

    # Validate Python registry client imports
    local python_registry_client_dir="$PROJECT_ROOT/src/runtime/python/src/mcp_mesh/registry_client_generated"
    if [[ -d "$python_registry_client_dir" ]]; then
        log_info "Checking Python registry client imports..."
        cd "$PROJECT_ROOT/src/runtime/python"
        if ! python3 -c "
import sys
sys.path.insert(0, 'src')
try:
    from mcp_mesh.registry_client_generated.mcp_mesh_registry_client import AgentsApi, HealthApi
    print('✅ Python registry client imports successfully')
except ImportError as e:
    print(f'❌ Python registry client import failed: {e}')
    sys.exit(1)
" 2>/dev/null; then
            log_warning "Python registry client import check failed - may need additional dependencies"
        else
            log_success "Python registry client import check passed"
        fi
        cd "$PROJECT_ROOT"
    fi

    # Check Python agent server generation
    local python_agent_server_dir="$PROJECT_ROOT/src/runtime/python/src/mcp_mesh/agent_server_generated"
    if [[ -d "$python_agent_server_dir" ]]; then
        log_success "Python agent server code structure created"
    fi
}

# Update module dependencies
update_dependencies() {
    log_info "Updating module dependencies..."

    # Update Go modules
    if [[ -f "$PROJECT_ROOT/go.mod" ]]; then
        log_info "Running go mod tidy..."
        cd "$PROJECT_ROOT"
        go mod tidy
        cd "$SCRIPT_DIR"
    fi

    log_success "Dependencies updated"
}

# Main execution function
main() {
    local target="${1:-all}"

    log_info "Starting dual-contract code generation for MCP Mesh (target: $target)"
    log_info "Project root: $PROJECT_ROOT"
    log_info "Registry spec: $REGISTRY_SPEC"
    log_info "Agent spec: $AGENT_SPEC"

    case "$target" in
        "registry-go")
            check_prerequisites
            validate_openapi_spec "$REGISTRY_SPEC" "Registry"
            generate_go_registry_server
            ;;
        "registry-python")
            check_prerequisites
            validate_openapi_spec "$REGISTRY_SPEC" "Registry"
            generate_python_registry_client
            ;;
        "agent-python")
            check_prerequisites
            validate_openapi_spec "$AGENT_SPEC" "Agent"
            generate_python_agent_server
            ;;
        "registry")
            check_prerequisites
            validate_openapi_spec "$REGISTRY_SPEC" "Registry"
            generate_go_registry_server
            generate_python_registry_client
            ;;
        "agent")
            check_prerequisites
            validate_openapi_spec "$AGENT_SPEC" "Agent"
            generate_python_agent_server
            ;;
        "go")
            check_prerequisites
            validate_openapi_spec "$REGISTRY_SPEC" "Registry"
            generate_go_registry_server
            ;;
        "python")
            check_prerequisites
            validate_openapi_spec "$REGISTRY_SPEC" "Registry"
            validate_openapi_spec "$AGENT_SPEC" "Agent"
            generate_python_registry_client
            generate_python_agent_server
            ;;
        "all"|"")
            check_prerequisites
            validate_openapi_spec "$REGISTRY_SPEC" "Registry"
            validate_openapi_spec "$AGENT_SPEC" "Agent"
            generate_go_registry_server
            generate_python_registry_client
            generate_python_agent_server
            validate_generated_code
            update_dependencies
            ;;
        *)
            log_error "Unknown target: $target"
            log_error "Usage: $0 [registry-go|registry-python|agent-python|registry|agent|go|python|all]"
            exit 1
            ;;
    esac

    log_success "Code generation completed successfully!"
    log_info ""
    log_info "📋 Generated files:"
    log_info "  Go registry server: src/core/registry/generated/server.go"
    log_info "  Python registry client: src/runtime/python/src/mcp_mesh/registry_client_generated/"
    log_info "  Python agent server: src/runtime/python/src/mcp_mesh/agent_server_generated/"
    log_info ""
    log_info "🔧 Next steps:"
    log_info "  1. Implement registry business logic in src/core/registry/handlers_impl.go"
    log_info "  2. Integrate agent server handlers in HTTP wrapper"
    log_info "  3. Update tests to match both API contracts"
    log_info "  4. Run: make validate-contract"
    log_info "  5. Run: make build && make test"
}

# Show help if requested
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    echo "MCP Mesh Dual-Contract Code Generation Script"
    echo ""
    echo "Usage: $0 [target]"
    echo ""
    echo "Targets:"
    echo "  registry-go      - Generate only Go registry server"
    echo "  registry-python  - Generate only Python registry client"
    echo "  agent-python     - Generate only Python agent server"
    echo "  registry         - Generate both registry Go server and Python client"
    echo "  agent            - Generate agent Python server"
    echo "  go               - Generate all Go code"
    echo "  python           - Generate all Python code"
    echo "  all              - Generate everything (default)"
    echo ""
    echo "Examples:"
    echo "  $0               # Generate all code from both specs"
    echo "  $0 registry      # Generate registry Go server + Python client"
    echo "  $0 agent         # Generate agent Python server"
    echo ""
    echo "🤖 AI GUIDANCE:"
    echo "This script implements dual-contract development:"
    echo "- Registry API: For agent-registry communication"
    echo "- Agent API: For agent HTTP wrapper endpoints"
    exit 0
fi

# Execute main function
main "$@"
