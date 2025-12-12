#!/bin/bash
set -e

# Build npm packages for meshctl and mcp-mesh-registry
# Downloads pre-built binaries from GitHub releases instead of building from source
# Usage: ./build-npm-packages.sh [VERSION]

VERSION="${VERSION:-${1:-dev}}"
VERSION_WITH_V="v${VERSION#v}"  # Ensure v prefix for download URLs
VERSION="${VERSION#v}"          # Remove 'v' prefix for npm version

NPM_DIR="${NPM_DIR:-dist/npm}"
GITHUB_REPO="${GITHUB_REPO:-dhyansraj/mcp-mesh}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-dist/downloads}"

echo "Building npm packages for version: $VERSION"
echo "Downloading from: https://github.com/$GITHUB_REPO/releases/tag/$VERSION_WITH_V"

# Platforms to package (Linux and macOS only)
# Format: "goos:goarch:npm-platform"
PLATFORMS=(
  "linux:amd64:linux-x64"
  "linux:arm64:linux-arm64"
  "darwin:amd64:darwin-x64"
  "darwin:arm64:darwin-arm64"
)

# Clean and create output directories
rm -rf "$NPM_DIR" "$DOWNLOAD_DIR"
mkdir -p "$NPM_DIR" "$DOWNLOAD_DIR"

# Download and extract release assets
echo ""
echo "Downloading release assets..."
for platform in "${PLATFORMS[@]}"; do
  IFS=':' read -r GOOS GOARCH NPM_PLATFORM <<< "$platform"

  TARBALL_NAME="mcp-mesh_${VERSION_WITH_V}_${GOOS}_${GOARCH}.tar.gz"
  DOWNLOAD_URL="https://github.com/$GITHUB_REPO/releases/download/$VERSION_WITH_V/$TARBALL_NAME"

  echo "  Downloading $TARBALL_NAME..."

  if curl -sL -f "$DOWNLOAD_URL" -o "$DOWNLOAD_DIR/$TARBALL_NAME"; then
    echo "    ✓ Downloaded $TARBALL_NAME"
  else
    echo "    ✗ Failed to download $TARBALL_NAME"
    echo "    URL: $DOWNLOAD_URL"
    exit 1
  fi
done

# Create platform-specific npm packages
echo ""
echo "Creating npm packages..."
for platform in "${PLATFORMS[@]}"; do
  IFS=':' read -r GOOS GOARCH NPM_PLATFORM <<< "$platform"

  PKG_NAME="@mcpmesh/cli-${NPM_PLATFORM}"
  PKG_DIR="$NPM_DIR/cli-${NPM_PLATFORM}"
  TARBALL_NAME="mcp-mesh_${VERSION_WITH_V}_${GOOS}_${GOARCH}.tar.gz"

  echo "  Creating ${PKG_NAME}..."

  # Create package directory
  mkdir -p "$PKG_DIR/bin"

  # Extract binaries from tarball
  # The tarball structure is: ${goos}_${goarch}/meshctl and ${goos}_${goarch}/mcp-mesh-registry
  EXTRACT_DIR=$(mktemp -d)
  tar -xzf "$DOWNLOAD_DIR/$TARBALL_NAME" -C "$EXTRACT_DIR"

  # Find and copy binaries
  PLATFORM_DIR="$EXTRACT_DIR/${GOOS}_${GOARCH}"
  if [ -d "$PLATFORM_DIR" ]; then
    if [ -f "$PLATFORM_DIR/meshctl" ]; then
      cp "$PLATFORM_DIR/meshctl" "$PKG_DIR/bin/"
      chmod +x "$PKG_DIR/bin/meshctl"
      echo "    ✓ Extracted meshctl"
    else
      echo "    ✗ meshctl not found in tarball"
      rm -rf "$EXTRACT_DIR"
      exit 1
    fi

    if [ -f "$PLATFORM_DIR/mcp-mesh-registry" ]; then
      cp "$PLATFORM_DIR/mcp-mesh-registry" "$PKG_DIR/bin/"
      chmod +x "$PKG_DIR/bin/mcp-mesh-registry"
      echo "    ✓ Extracted mcp-mesh-registry"
    else
      echo "    ✗ mcp-mesh-registry not found in tarball"
      rm -rf "$EXTRACT_DIR"
      exit 1
    fi
  else
    echo "    ✗ Platform directory not found: $PLATFORM_DIR"
    ls -la "$EXTRACT_DIR"
    rm -rf "$EXTRACT_DIR"
    exit 1
  fi

  rm -rf "$EXTRACT_DIR"

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
    "url": "git+https://github.com/dhyansraj/mcp-mesh.git"
  },
  "publishConfig": {
    "access": "public"
  }
}
EOF

  echo "    ✓ Created ${PKG_NAME}"
done

# Copy and update main CLI package
echo ""
echo "Preparing main @mcpmesh/cli package..."
CLI_PKG_DIR="$NPM_DIR/cli"
mkdir -p "$CLI_PKG_DIR/bin"

# Copy npm package files
cp npm/cli/package.json "$CLI_PKG_DIR/"
cp npm/cli/install.js "$CLI_PKG_DIR/"
cp npm/cli/README.md "$CLI_PKG_DIR/"
cp npm/cli/bin/meshctl "$CLI_PKG_DIR/bin/"
cp npm/cli/bin/mcp-mesh-registry "$CLI_PKG_DIR/bin/"

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

# Clean up downloads
rm -rf "$DOWNLOAD_DIR"

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
