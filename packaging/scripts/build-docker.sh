#!/bin/bash
set -euo pipefail

# MCP Mesh Docker Build Script with Multi-Architecture Support
# Builds and optionally pushes Docker images for multiple architectures

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PACKAGING_DIR="$PROJECT_ROOT/packaging"

# Configuration
REGISTRY="${DOCKER_REGISTRY:-mcpmesh}"
TAG="${DOCKER_TAG:-latest}"
PUSH="${DOCKER_PUSH:-false}"
PLATFORMS="${DOCKER_PLATFORMS:-linux/amd64,linux/arm64}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check dependencies
check_dependencies() {
    log "Checking dependencies..."

    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
        exit 1
    fi

    # Check if buildx is available and configured
    if ! docker buildx inspect multiarch &> /dev/null; then
        log "Setting up Docker buildx for multi-architecture builds..."
        docker buildx create --name multiarch --use --bootstrap
    else
        docker buildx use multiarch
    fi

    success "Dependencies check passed"
}

# Build function for a specific image
build_image() {
    local image_name="$1"
    local dockerfile="$2"
    local context="$3"
    local full_tag="$REGISTRY/$image_name:$TAG"

    log "Building $image_name..."
    log "  Dockerfile: $dockerfile"
    log "  Context: $context"
    log "  Platforms: $PLATFORMS"
    log "  Tag: $full_tag"

    # Build command
    local build_cmd=(
        docker buildx build
        --platform "$PLATFORMS"
        --file "$dockerfile"
        --tag "$full_tag"
        --progress=plain
    )

    # Add push flag if enabled
    if [[ "$PUSH" == "true" ]]; then
        build_cmd+=(--push)
        log "  Will push to registry"
    else
        build_cmd+=(--load)
        warn "  Build only (not pushing)"
    fi

    # Add context
    build_cmd+=("$context")

    # Execute build
    if "${build_cmd[@]}"; then
        success "Built $image_name successfully"
        return 0
    else
        error "Failed to build $image_name"
        return 1
    fi
}

# Main build function
build_all_images() {
    log "Starting multi-architecture Docker builds..."
    log "Registry: $REGISTRY"
    log "Tag: $TAG"
    log "Platforms: $PLATFORMS"
    log "Push: $PUSH"

    local failed_builds=()

    # Build registry image
    if ! build_image "registry" "$PACKAGING_DIR/docker/registry.Dockerfile" "$PROJECT_ROOT"; then
        failed_builds+=("registry")
    fi

    # Build Python runtime image
    if ! build_image "python-runtime" "$PACKAGING_DIR/docker/python-runtime.Dockerfile" "$PROJECT_ROOT"; then
        failed_builds+=("python-runtime")
    fi

    # Build CLI tools image
    if ! build_image "cli" "$PACKAGING_DIR/docker/cli.Dockerfile" "$PROJECT_ROOT"; then
        failed_builds+=("cli")
    fi

    # Report results
    if [[ ${#failed_builds[@]} -eq 0 ]]; then
        success "All images built successfully!"

        if [[ "$PUSH" == "true" ]]; then
            success "Images pushed to $REGISTRY"
        else
            log "To push images, run with DOCKER_PUSH=true"
        fi

        log "Available images:"
        log "  $REGISTRY/registry:$TAG"
        log "  $REGISTRY/python-runtime:$TAG"
        log "  $REGISTRY/cli:$TAG"
    else
        error "Failed to build images: ${failed_builds[*]}"
        exit 1
    fi
}

# Show usage
usage() {
    cat << EOF
Usage: $0 [options]

Build MCP Mesh Docker images with multi-architecture support.

Environment Variables:
    DOCKER_REGISTRY     Registry to use (default: mcpmesh)
    DOCKER_TAG         Tag to use (default: latest)
    DOCKER_PUSH        Push to registry (default: false)
    DOCKER_PLATFORMS   Target platforms (default: linux/amd64,linux/arm64)

Examples:
    # Build all images locally
    $0

    # Build and push to Docker Hub
    DOCKER_PUSH=true $0

    # Build for specific platforms
    DOCKER_PLATFORMS=linux/amd64,linux/arm64,linux/arm/v7 $0

    # Use custom registry
    DOCKER_REGISTRY=ghcr.io/myorg/mcp-mesh DOCKER_PUSH=true $0

EOF
}

# Main execution
main() {
    case "${1:-}" in
        -h|--help)
            usage
            exit 0
            ;;
        *)
            check_dependencies
            build_all_images
            ;;
    esac
}

main "$@"
