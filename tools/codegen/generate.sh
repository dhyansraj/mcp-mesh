#!/bin/bash
# Code Generation Script for MCP Mesh Contract-First Development
#
# This script generates Go server stubs from Registry OpenAPI spec.
#
# NOTE: Python/TypeScript SDKs communicate with the registry via Rust core,
# which uses a manually written client (auto-generated Rust clients are too verbose).
#
# WHAT THIS SCRIPT DOES:
# 1. Validates the OpenAPI specification
# 2. Generates Go registry server handlers from registry spec
# 3. Validates generated code compiles
#
# IF THIS SCRIPT FAILS:
# - Check OpenAPI spec syntax and schema
# - Ensure oapi-codegen is installed
# - Verify output directories exist and are writable
# - Check that generated code matches expected interfaces

set -euo pipefail

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.yaml"

# API specifications
REGISTRY_SPEC="$PROJECT_ROOT/api/mcp-mesh-registry.openapi.yaml"

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

    # Check if python3 is available (required for YAML validation)
    if ! command -v python3 &> /dev/null; then
        log_error "python3 not found. Install Python 3 to validate OpenAPI specs."
        exit 1
    fi

    # Check if PyYAML module is available (required for YAML parsing)
    if ! python3 -c 'import yaml' &> /dev/null; then
        log_error "PyYAML module not found. Install with:"
        log_error "pip install pyyaml"
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
// 3. Implement business logic in ent_handlers.go
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

# Validate generated code
validate_generated_code() {
    log_info "Validating generated code..."

    # Validate Go code compiles
    local go_file="$PROJECT_ROOT/src/core/registry/generated/server.go"
    if [[ -f "$go_file" ]]; then
        log_info "Checking Go registry code compilation..."
        if ! go build -o /dev/null "$PROJECT_ROOT/src/core/registry/..." 2>/dev/null; then
            log_error "Generated Go registry code does not compile"
            log_error "Check the business logic implementation in ent_handlers.go"
            exit 1
        fi
        log_success "Go registry code compilation check passed"
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
    local target="${1:-go}"

    log_info "Starting code generation for MCP Mesh (target: $target)"
    log_info "Project root: $PROJECT_ROOT"
    log_info "Registry spec: $REGISTRY_SPEC"

    case "$target" in
        "go"|"all"|"")
            check_prerequisites
            validate_openapi_spec "$REGISTRY_SPEC" "Registry"
            generate_go_registry_server
            validate_generated_code
            update_dependencies
            ;;
        *)
            log_error "Unknown target: $target"
            log_error "Usage: $0 [go|all]"
            exit 1
            ;;
    esac

    log_success "Code generation completed successfully!"
    log_info ""
    log_info "📋 Generated files:"
    log_info "  Go registry server: src/core/registry/generated/server.go"
    log_info ""
    log_info "🔧 Next steps:"
    log_info "  1. Implement registry business logic in src/core/registry/ent_handlers.go"
    log_info "  2. Run: make build && make test"
}

# Show help if requested
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    echo "MCP Mesh Code Generation Script"
    echo ""
    echo "Usage: $0 [target]"
    echo ""
    echo "Targets:"
    echo "  go   - Generate Go registry server (default)"
    echo "  all  - Generate all code (same as go)"
    echo ""
    echo "Examples:"
    echo "  $0        # Generate Go server from OpenAPI spec"
    echo "  $0 go     # Same as above"
    echo ""
    echo "Note: Python/TypeScript SDKs use Rust core for registry communication."
    echo "      The Rust client is manually written (not auto-generated)."
    exit 0
fi

# Execute main function
main "$@"
