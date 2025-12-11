#!/bin/bash
set -e

# Build npm packages for meshctl and mcp-mesh-registry
# Usage: ./build-npm-packages.sh [VERSION]

VERSION="${VERSION:-${1:-dev}}"
VERSION="${VERSION#v}" # Remove 'v' prefix if present

NPM_DIR="${NPM_DIR:-dist/npm}"
GO_VERSION="${GO_VERSION:-1.23}"

echo "Building npm packages for version: $VERSION"

# Platforms to build (Linux and macOS only - Windows not supported due to CGO requirements)
PLATFORMS=(
  "linux:amd64:linux-x64"
  "linux:arm64:linux-arm64"
  "darwin:amd64:darwin-x64"
  "darwin:arm64:darwin-arm64"
)

# Clean and create output directory
rm -rf "$NPM_DIR"
mkdir -p "$NPM_DIR"

# Function to get CC for cross-compilation
get_cc_for_platform() {
  local goos="$1"
  local goarch="$2"
  local host_arch=$(uname -m)

  case "$goos-$goarch" in
    "linux-arm64")
      echo "aarch64-linux-gnu-gcc"
      ;;
    "linux-amd64")
      if [[ "$host_arch" == "aarch64" || "$host_arch" == "arm64" ]]; then
        echo "x86_64-linux-gnu-gcc"
      else
        echo ""  # Native build
      fi
      ;;
    *)
      echo ""
      ;;
  esac
}

# Build platform-specific packages
for platform in "${PLATFORMS[@]}"; do
  IFS=':' read -r GOOS GOARCH NPM_PLATFORM <<< "$platform"

  PKG_NAME="@mcpmesh/cli-${NPM_PLATFORM}"
  PKG_DIR="$NPM_DIR/cli-${NPM_PLATFORM}"

  echo "Building ${PKG_NAME}..."

  # Create package directory
  mkdir -p "$PKG_DIR/bin"

  # Build meshctl (no CGO required)
  if CGO_ENABLED=0 GOOS=$GOOS GOARCH=$GOARCH go build \
    -ldflags="-s -w -X main.version=${VERSION}" \
    -o "$PKG_DIR/bin/meshctl" \
    ./cmd/meshctl 2>/dev/null; then
    echo "  ✓ Built meshctl for ${NPM_PLATFORM}"
  else
    echo "  ⚠ Failed to build meshctl for ${NPM_PLATFORM}"
    rm -rf "$PKG_DIR"
    continue
  fi

  # Build mcp-mesh-registry (requires CGO for SQLite)
  CC=$(get_cc_for_platform "$GOOS" "$GOARCH")

  BUILD_ENV="CGO_ENABLED=1 GOOS=$GOOS GOARCH=$GOARCH"
  if [ -n "$CC" ]; then
    BUILD_ENV="$BUILD_ENV CC=$CC"
  fi

  if eval "$BUILD_ENV go build \
    -ldflags='-s -w -X main.Version=${VERSION}' \
    -o '$PKG_DIR/bin/mcp-mesh-registry' \
    ./cmd/mcp-mesh-registry" 2>/dev/null; then
    echo "  ✓ Built mcp-mesh-registry for ${NPM_PLATFORM}"
  else
    echo "  ⚠ Failed to build mcp-mesh-registry for ${NPM_PLATFORM} (CGO cross-compile may not be available)"
  fi

  # Determine npm os/cpu values (map Go values to npm values)
  NPM_OS="$GOOS"
  NPM_CPU="$GOARCH"

  if [ "$GOARCH" = "amd64" ]; then
    NPM_CPU="x64"
  fi

  # Create package.json for platform package
  cat > "$PKG_DIR/package.json" << EOF
{
  "name": "${PKG_NAME}",
  "version": "${VERSION}",
  "description": "MCP Mesh CLI binaries for ${NPM_PLATFORM}",
  "license": "MIT",
  "preferUnplugged": true,
  "engines": {
    "node": ">=18"
  },
  "os": ["${NPM_OS}"],
  "cpu": ["${NPM_CPU}"],
  "repository": {
    "type": "git",
    "url": "git+https://github.com/mcpmesh/mcp-mesh.git"
  },
  "publishConfig": {
    "access": "public"
  }
}
EOF
done

# Copy and update main CLI package
echo "Preparing main @mcpmesh/cli package..."
CLI_PKG_DIR="$NPM_DIR/cli"
mkdir -p "$CLI_PKG_DIR/bin"

# Copy npm package files
cp npm/cli/package.json "$CLI_PKG_DIR/"
cp npm/cli/install.js "$CLI_PKG_DIR/"
cp npm/cli/README.md "$CLI_PKG_DIR/"
cp npm/cli/bin/meshctl "$CLI_PKG_DIR/bin/"

# Update version in main package.json
sed -i.bak "s/\"version\": \".*\"/\"version\": \"${VERSION}\"/" "$CLI_PKG_DIR/package.json"

# Update optionalDependencies versions
for platform in "${PLATFORMS[@]}"; do
  IFS=':' read -r _ _ NPM_PLATFORM <<< "$platform"
  sed -i.bak "s/\"@mcpmesh\/cli-${NPM_PLATFORM}\": \".*\"/\"@mcpmesh\/cli-${NPM_PLATFORM}\": \"${VERSION}\"/" "$CLI_PKG_DIR/package.json"
done

# Remove backup files created by sed
rm -f "$CLI_PKG_DIR/"*.bak

echo "  ✓ Prepared @mcpmesh/cli"

# Create a summary
echo ""
echo "=== npm packages built ==="
echo "Version: $VERSION"
echo "Output: $NPM_DIR"
echo ""
ls -la "$NPM_DIR"
echo ""
echo "Platform packages:"
for platform in "${PLATFORMS[@]}"; do
  IFS=':' read -r _ _ NPM_PLATFORM <<< "$platform"
  PKG_DIR="$NPM_DIR/cli-${NPM_PLATFORM}"
  if [ -d "$PKG_DIR" ]; then
    echo "  @mcpmesh/cli-${NPM_PLATFORM}:"
    for bin in "$PKG_DIR/bin/"*; do
      if [ -f "$bin" ]; then
        SIZE=$(du -sh "$bin" 2>/dev/null | cut -f1)
        echo "    - $(basename "$bin"): ${SIZE}"
      fi
    done
  fi
done

echo ""
echo "To publish (after npm login):"
echo "  cd $NPM_DIR"
echo "  for pkg in cli-*; do cd \$pkg && npm publish --access public && cd ..; done"
echo "  cd cli && npm publish --access public"
