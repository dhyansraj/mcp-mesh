#!/bin/bash
# MCP Mesh Binary Installer
# Downloads and installs MCP Mesh binaries from GitHub releases

set -e

# Default values
VERSION="latest"
INSTALL_DIR="/usr/local/bin"
REPO="dhyansraj/mcp-mesh"
INSTALL_MESHCTL="true"
INSTALL_REGISTRY="true"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print functions
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Help function
show_help() {
    cat << EOF
MCP Mesh Binary Installer

Usage: $0 [OPTIONS]

Options:
    --meshctl-only       Install only meshctl CLI binary
    --registry-only      Install only mcp-mesh-registry binary
    --all                Install both binaries (default)
    --version VERSION    Install specific version (default: latest)
    --install-dir DIR    Install directory (default: /usr/local/bin)
    --help              Show this help message

Examples:
    # Install both binaries (default)
    curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash

    # Install only meshctl CLI
    curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --meshctl-only

    # Install only registry (useful for Docker)
    curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --registry-only

    # Install specific patch version
    curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --version v0.2.0

    # Install latest patch in v0.2.x series (recommended)
    curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --version v0.2

    # Install latest in v0.x.x series
    curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --version v0

    # Install to custom directory
    curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --install-dir /usr/bin

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --meshctl-only)
            INSTALL_MESHCTL="true"
            INSTALL_REGISTRY="false"
            shift
            ;;
        --registry-only)
            INSTALL_MESHCTL="false"
            INSTALL_REGISTRY="true"
            shift
            ;;
        --all)
            INSTALL_MESHCTL="true"
            INSTALL_REGISTRY="true"
            shift
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Detect platform
detect_platform() {
    local os=$(uname -s | tr '[:upper:]' '[:lower:]')
    local arch=$(uname -m)

    case $os in
        linux)
            OS="linux"
            ;;
        darwin)
            OS="darwin"
            ;;
        *)
            print_error "Unsupported OS: $os"
            exit 1
            ;;
    esac

    case $arch in
        x86_64|amd64)
            ARCH="amd64"
            ;;
        arm64|aarch64)
            ARCH="arm64"
            ;;
        *)
            print_error "Unsupported architecture: $arch"
            exit 1
            ;;
    esac

    PLATFORM="${OS}-${ARCH}"
    print_info "Detected platform: $PLATFORM"
}

# Get the latest version from GitHub
get_latest_version() {
    print_info "Fetching latest version from GitHub..."
    VERSION=$(curl -sSL "https://api.github.com/repos/$REPO/releases/latest" | grep '"tag_name":' | cut -d'"' -f4)
    if [[ -z "$VERSION" ]]; then
        print_error "Failed to fetch latest version"
        exit 1
    fi
    print_info "Latest version: $VERSION"
}

# Resolve minor version (e.g., v0.1) to latest patch version (e.g., v0.1.6)
resolve_minor_version() {
    local requested_version="$1"

    # If it's already a full version (e.g., v0.1.6), return as-is
    if [[ "$requested_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "$requested_version"
        return
    fi

    # If it's a minor version (e.g., v0.1), find the latest patch
    if [[ "$requested_version" =~ ^v[0-9]+\.[0-9]+$ ]]; then
        print_info "Resolving minor version $requested_version to latest patch..." >&2

        # Get all releases and filter for the requested minor version
        local latest_patch
        latest_patch=$(curl -sSL "https://api.github.com/repos/$REPO/releases" | \
            grep '"tag_name":' | \
            cut -d'"' -f4 | \
            grep "^${requested_version}\." | \
            sort -V | \
            tail -1)

        if [[ -z "$latest_patch" ]]; then
            print_error "No releases found for version $requested_version" >&2
            exit 1
        fi

        print_info "Resolved $requested_version to $latest_patch" >&2
        echo "$latest_patch"
        return
    fi

    # If it's a major version (e.g., v0), find the latest minor.patch
    if [[ "$requested_version" =~ ^v[0-9]+$ ]]; then
        print_info "Resolving major version $requested_version to latest minor.patch..." >&2

        local latest_release
        latest_release=$(curl -sSL "https://api.github.com/repos/$REPO/releases" | \
            grep '"tag_name":' | \
            cut -d'"' -f4 | \
            grep "^${requested_version}\." | \
            sort -V | \
            tail -1)

        if [[ -z "$latest_release" ]]; then
            print_error "No releases found for version $requested_version" >&2
            exit 1
        fi

        print_info "Resolved $requested_version to $latest_release" >&2
        echo "$latest_release"
        return
    fi

    # If it's not a semantic version pattern, return as-is (e.g., "latest")
    echo "$requested_version"
}

# Generic function to download and install a binary
install_binary() {
    local binary_name="$1"
    # Convert platform dashes to underscores for release asset naming
    local platform_for_url="${PLATFORM//-/_}"
    local download_url="https://github.com/$REPO/releases/download/$VERSION/mcp-mesh_${VERSION}_$platform_for_url.tar.gz"
    local temp_dir=$(mktemp -d)

    print_info "Downloading $binary_name $VERSION for $PLATFORM..."
    print_info "URL: $download_url"

    # Download the archive
    if ! curl -sSL "$download_url" -o "$temp_dir/mcp-mesh.tar.gz"; then
        print_error "Failed to download from $download_url"
        print_error "Please check if the version and platform are correct"
        exit 1
    fi

    # Extract the binary
    print_info "Extracting $binary_name..."
    if ! tar -xzf "$temp_dir/mcp-mesh.tar.gz" -C "$temp_dir"; then
        print_error "Failed to extract archive"
        exit 1
    fi

    # Create install directory if it doesn't exist
    if [[ ! -d "$INSTALL_DIR" ]]; then
        print_info "Creating install directory: $INSTALL_DIR"
        sudo mkdir -p "$INSTALL_DIR"
    fi

    # Install the binary
    print_info "Installing $binary_name to $INSTALL_DIR..."
    local extracted_binary
    # Use the same platform format as the release assets (with underscores)
    local platform_for_path="${PLATFORM//-/_}"
    if [[ "$binary_name" == "registry" ]]; then
        extracted_binary="$temp_dir/$platform_for_path/registry"
    else
        extracted_binary="$temp_dir/$platform_for_path/$binary_name"
    fi

    if [[ -w "$INSTALL_DIR" ]]; then
        cp "$extracted_binary" "$INSTALL_DIR/$binary_name"
        chmod +x "$INSTALL_DIR/$binary_name"
    else
        sudo cp "$extracted_binary" "$INSTALL_DIR/$binary_name"
        sudo chmod +x "$INSTALL_DIR/$binary_name"
    fi

    # Cleanup
    rm -rf "$temp_dir"

    print_info "✅ $binary_name installed successfully!"
}

# Install meshctl
install_meshctl() {
    install_binary "meshctl"

    # Verify installation
    if command -v meshctl >/dev/null 2>&1; then
        print_info "Verification: $(meshctl version 2>/dev/null || echo 'meshctl is installed')"
    else
        print_warn "meshctl was installed to $INSTALL_DIR but is not in PATH"
        print_warn "Add $INSTALL_DIR to your PATH or use the full path: $INSTALL_DIR/meshctl"
    fi
}

# Install mcp-mesh-registry
install_registry() {
    install_binary "registry"

    # Verify installation
    if command -v registry >/dev/null 2>&1; then
        print_info "Verification: registry installed to $INSTALL_DIR/registry"
    else
        print_warn "registry was installed to $INSTALL_DIR but is not in PATH"
        print_warn "Add $INSTALL_DIR to your PATH or use the full path: $INSTALL_DIR/registry"
    fi
}

# Main execution
main() {
    print_info "MCP Mesh Binary Installer"
    print_info "========================="

    detect_platform

    # Get latest version if not specified
    if [[ "$VERSION" == "latest" ]]; then
        get_latest_version
    else
        # Resolve minor/major versions to specific patch versions
        VERSION=$(resolve_minor_version "$VERSION")
    fi

    # Install selected binaries
    local installed_count=0
    if [[ "$INSTALL_MESHCTL" == "true" ]]; then
        install_meshctl
        installed_count=$((installed_count + 1))
    fi

    if [[ "$INSTALL_REGISTRY" == "true" ]]; then
        install_registry
        installed_count=$((installed_count + 1))
    fi

    # Final message
    print_info ""
    if [[ $installed_count -eq 0 ]]; then
        print_warn "No binaries were selected for installation"
        print_info "Use --help to see available options"
    else
        print_info "🎉 Installation completed!"
        if [[ "$INSTALL_MESHCTL" == "true" ]]; then
            print_info "Run 'meshctl --help' to get started with the CLI"
        fi
        if [[ "$INSTALL_REGISTRY" == "true" ]]; then
            print_info "Run 'registry --help' to get started with the registry"
        fi
    fi
}

# Run main function
main "$@"# Updated Sat Jun 21 09:51:42 EDT 2025
