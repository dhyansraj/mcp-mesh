#!/bin/bash
set -e

# Build npm packages for meshctl
# Usage: ./build-npm-packages.sh [VERSION]

VERSION="${VERSION:-${1:-dev}}"
VERSION="${VERSION#v}" # Remove 'v' prefix if present

NPM_DIR="${NPM_DIR:-dist/npm}"
GO_VERSION="${GO_VERSION:-1.23}"

echo "Building npm packages for version: $VERSION"

# Platforms to build
PLATFORMS=(
  "linux:amd64:linux-x64"
  "linux:arm64:linux-arm64"
  "darwin:amd64:darwin-x64"
  "darwin:arm64:darwin-arm64"
  "windows:amd64:win32-x64"
  "windows:arm64:win32-arm64"
)

# Clean and create output directory
rm -rf "$NPM_DIR"
mkdir -p "$NPM_DIR"

# Build platform-specific packages
for platform in "${PLATFORMS[@]}"; do
  IFS=':' read -r GOOS GOARCH NPM_PLATFORM <<< "$platform"

  PKG_NAME="@mcpmesh/cli-${NPM_PLATFORM}"
  PKG_DIR="$NPM_DIR/cli-${NPM_PLATFORM}"

  echo "Building ${PKG_NAME}..."

  # Create package directory
  mkdir -p "$PKG_DIR/bin"

  # Determine binary name
  BINARY_NAME="meshctl"
  if [ "$GOOS" = "windows" ]; then
    BINARY_NAME="meshctl.exe"
  fi

  # Build the binary
  if CGO_ENABLED=0 GOOS=$GOOS GOARCH=$GOARCH go build \
    -ldflags="-s -w -X main.version=${VERSION}" \
    -o "$PKG_DIR/bin/$BINARY_NAME" \
    ./cmd/meshctl 2>/dev/null; then
    echo "  ✓ Built ${PKG_NAME}"
  else
    echo "  ⚠ Failed to build ${PKG_NAME} (cross-compile may require different host)"
    rm -rf "$PKG_DIR"
    continue
  fi

  # Determine npm os/cpu values
  NPM_OS="$GOOS"
  NPM_CPU="$GOARCH"

  # Map Go values to npm values
  if [ "$GOOS" = "darwin" ]; then
    NPM_OS="darwin"
  elif [ "$GOOS" = "windows" ]; then
    NPM_OS="win32"
  fi

  if [ "$GOARCH" = "amd64" ]; then
    NPM_CPU="x64"
  fi

  # Create package.json for platform package
  cat > "$PKG_DIR/package.json" << EOF
{
  "name": "${PKG_NAME}",
  "version": "${VERSION}",
  "description": "meshctl binary for ${NPM_PLATFORM}",
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
    SIZE=$(du -sh "$PKG_DIR/bin/"* 2>/dev/null | cut -f1)
    echo "  @mcpmesh/cli-${NPM_PLATFORM}: ${SIZE}"
  fi
done

echo ""
echo "To publish (after npm login):"
echo "  cd $NPM_DIR"
echo "  for pkg in cli-*; do cd \$pkg && npm publish --access public && cd ..; done"
echo "  cd cli && npm publish --access public"
