#!/bin/bash
set -euo pipefail

# MCP Mesh Binary Build Script with Cross-Compilation Support
# Builds Go binaries for multiple platforms and architectures

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
VERSION="${VERSION:-dev}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64,darwin/amd64,darwin/arm64}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_ROOT/dist}"
COMPRESS="${COMPRESS:-true}"

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

    if ! command -v go &> /dev/null; then
        error "Go is not installed"
        exit 1
    fi

    # Check Go version
    go_version=$(go version | cut -d' ' -f3 | sed 's/go//')
    log "Using Go version: $go_version"

    # Check if tar is available for compression
    if [[ "$COMPRESS" == "true" ]] && ! command -v tar &> /dev/null; then
        warn "tar not available, disabling compression"
        COMPRESS="false"
    fi

    success "Dependencies check passed"
}

# Build binary for specific platform
build_binary() {
    local cmd="$1"
    local goos="$2"
    local goarch="$3"
    local output_name="$4"

    local platform="${goos}_${goarch}"
    local output_dir="$OUTPUT_DIR/$platform"
    local binary_name="$output_name"

    # Add .exe extension for Windows
    if [[ "$goos" == "windows" ]]; then
        binary_name="${output_name}.exe"
    fi

    local output_path="$output_dir/$binary_name"

    log "Building $cmd for $platform..."

    # Create output directory
    mkdir -p "$output_dir"

    # Set build environment
    # Enable CGO for registry (needs SQLite), disable for others
    if [[ "$cmd" == "registry" ]]; then
        export CGO_ENABLED=1
    else
        export CGO_ENABLED=0
    fi
    export GOOS="$goos"
    export GOARCH="$goarch"

    # Build flags
    local ldflags=(
        "-w"                                    # Omit debug info
        "-s"                                    # Omit symbol table
        "-X main.Version=$VERSION"              # Set version
        "-X main.BuildTime=$(date -u +%Y-%m-%dT%H:%M:%SZ)"  # Set build time
        "-X main.GitCommit=$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"  # Set git commit
    )

    # Map cmd names to actual paths
    local cmd_path
    case "$cmd" in
        "meshctl")
            cmd_path="./cmd/meshctl"
            ;;
        "registry")
            cmd_path="./cmd/mcp-mesh-registry"
            ;;
        *)
            cmd_path="./cmd/$cmd"
            ;;
    esac

    # Execute build
    if go build -ldflags="${ldflags[*]}" -o "$output_path" "$cmd_path"; then
        success "Built $cmd for $platform: $output_path"

        # Show binary info
        local size=$(du -h "$output_path" | cut -f1)
        log "  Size: $size"

        return 0
    else
        error "Failed to build $cmd for $platform"
        return 1
    fi
}

# Create compressed archive
create_archive() {
    local platform="$1"
    local archive_name="mcp-mesh_${VERSION}_${platform}"
    local platform_dir="$OUTPUT_DIR/$platform"

    if [[ ! -d "$platform_dir" ]]; then
        warn "Platform directory $platform_dir does not exist, skipping archive"
        return 1
    fi

    log "Creating archive for $platform..."

    # Determine archive format based on platform
    local archive_ext="tar.gz"
    local archive_path="$OUTPUT_DIR/${archive_name}.${archive_ext}"

    if [[ "$platform" == *"windows"* ]]; then
        archive_ext="zip"
        archive_path="$OUTPUT_DIR/${archive_name}.${archive_ext}"

        if command -v zip &> /dev/null; then
            (cd "$OUTPUT_DIR" && zip -r "${archive_name}.${archive_ext}" "$platform/")
        else
            warn "zip not available, skipping Windows archive"
            return 1
        fi
    else
        tar -czf "$archive_path" -C "$OUTPUT_DIR" "$platform/"
    fi

    if [[ -f "$archive_path" ]]; then
        success "Created archive: $archive_path"
        local size=$(du -h "$archive_path" | cut -f1)
        log "  Archive size: $size"
        return 0
    else
        error "Failed to create archive for $platform"
        return 1
    fi
}

# Generate checksums
generate_checksums() {
    log "Generating checksums..."

    local checksum_file="$OUTPUT_DIR/checksums.txt"

    # Remove existing checksum file
    rm -f "$checksum_file"

    # Generate checksums for all archives
    find "$OUTPUT_DIR" -name "*.tar.gz" -o -name "*.zip" | while read -r file; do
        local filename=$(basename "$file")
        local checksum

        if command -v sha256sum &> /dev/null; then
            checksum=$(sha256sum "$file" | cut -d' ' -f1)
        elif command -v shasum &> /dev/null; then
            checksum=$(shasum -a 256 "$file" | cut -d' ' -f1)
        else
            warn "No checksum tool available, skipping checksums"
            return 1
        fi

        echo "$checksum  $filename" >> "$checksum_file"
    done

    if [[ -f "$checksum_file" ]]; then
        success "Generated checksums: $checksum_file"
        cat "$checksum_file"
    fi
}

# Main build function
build_all_binaries() {
    log "Starting cross-compilation builds..."
    log "Version: $VERSION"
    log "Platforms: $PLATFORMS"
    log "Output directory: $OUTPUT_DIR"
    log "Compression: $COMPRESS"

    # Clean output directory
    rm -rf "$OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"

    # Parse platforms and build
    local failed_builds=()
    local built_platforms=()

    IFS=',' read -ra PLATFORM_ARRAY <<< "$PLATFORMS"
    for platform in "${PLATFORM_ARRAY[@]}"; do
        IFS='/' read -ra PARTS <<< "$platform"
        local goos="${PARTS[0]}"
        local goarch="${PARTS[1]}"

        # Build meshctl
        if build_binary "meshctl" "$goos" "$goarch" "meshctl"; then
            # Build registry
            if build_binary "registry" "$goos" "$goarch" "registry"; then
                built_platforms+=("${goos}_${goarch}")
            else
                failed_builds+=("registry-${goos}_${goarch}")
            fi
        else
            failed_builds+=("meshctl-${goos}_${goarch}")
        fi
    done

    # Create archives if compression is enabled
    if [[ "$COMPRESS" == "true" ]]; then
        for platform in "${built_platforms[@]}"; do
            create_archive "$platform"
        done

        # Generate checksums
        generate_checksums
    fi

    # Report results
    if [[ ${#failed_builds[@]} -eq 0 ]]; then
        success "All binaries built successfully!"
        log "Built platforms: ${built_platforms[*]}"
        log "Output directory: $OUTPUT_DIR"
    else
        error "Failed builds: ${failed_builds[*]}"
        exit 1
    fi
}

# Show usage
usage() {
    cat << EOF
Usage: $0 [options]

Build MCP Mesh binaries for multiple platforms.

Environment Variables:
    VERSION      Version to embed (default: dev)
    PLATFORMS    Target platforms (default: linux/amd64,linux/arm64,darwin/amd64,darwin/arm64,windows/amd64,windows/arm64)
    OUTPUT_DIR   Output directory (default: ./dist)
    COMPRESS     Create compressed archives (default: true)

Examples:
    # Build all platforms
    $0

    # Build specific platforms
    PLATFORMS=linux/amd64,darwin/arm64 $0

    # Build with version
    VERSION=v1.0.0 $0

    # Build without compression
    COMPRESS=false $0

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
            cd "$PROJECT_ROOT"
            check_dependencies
            build_all_binaries
            ;;
    esac
}

main "$@"
