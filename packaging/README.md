# MCP Mesh Packaging

This directory contains all packaging configurations and build scripts for distributing MCP Mesh across multiple platforms and package managers.

## 📁 Structure

```
packaging/
├── docker/              # Docker configurations for multi-architecture builds
│   ├── registry.Dockerfile       # Go registry service (linux/amd64, linux/arm64)
│   ├── python-runtime.Dockerfile # Python agent runtime base image
│   └── cli.Dockerfile            # CLI tools container (includes meshctl + Python)
├── pypi/               # Python package configuration
│   └── pyproject.toml           # Complete PyPI package setup
├── homebrew/           # macOS/Linux package manager
│   └── mcp-mesh.rb             # Homebrew formula
├── scoop/              # Windows package manager
│   └── mcp-mesh.json           # Scoop manifest
└── scripts/            # Build automation scripts
    ├── build-docker.sh         # Multi-arch Docker builds
    └── build-binaries.sh       # Cross-platform Go binary builds
```

## 🚀 Distribution Channels

### Docker Images (Multi-Architecture)

```bash
# Registry service
docker pull mcpmesh/registry:latest

# Python runtime base
docker pull mcpmesh/python-runtime:latest

# CLI tools
docker pull mcpmesh/cli:latest
```

**Supported Platforms**: `linux/amd64`, `linux/arm64`

### Go Binaries (Cross-Platform)

```bash
# macOS ARM64
curl -L https://github.com/dhyansraj/mcp-mesh/releases/latest/download/mcp-mesh_latest_darwin_arm64.tar.gz

# Linux AMD64
curl -L https://github.com/dhyansraj/mcp-mesh/releases/latest/download/mcp-mesh_latest_linux_amd64.tar.gz

# For Windows: Use Docker or WSL2
docker run --rm mcpmesh/cli:latest version
```

**Supported Platforms**: Linux, macOS (AMD64 + ARM64)
**Note**: Windows binaries temporarily unavailable due to syscall compatibility issues. Use Docker or WSL2.

### Python Package

```bash
# Install from PyPI
pip install mcp-mesh

# Install with Kubernetes support
pip install mcp-mesh[kubernetes]

# Install development dependencies
pip install mcp-mesh[dev]
```

### Package Managers

```bash
# macOS/Linux (Homebrew)
brew install mcp-mesh

# Windows (Scoop)
scoop install mcp-mesh
```

## 🛠️ Local Building

### Build Docker Images

```bash
# Build all images for local development
./packaging/scripts/build-docker.sh

# Build and push to registry
DOCKER_PUSH=true ./packaging/scripts/build-docker.sh

# Build for specific platforms
DOCKER_PLATFORMS=linux/amd64,linux/arm64,linux/arm/v7 ./packaging/scripts/build-docker.sh
```

### Build Go Binaries

```bash
# Build all platforms
./packaging/scripts/build-binaries.sh

# Build specific platforms
PLATFORMS=linux/amd64,darwin/arm64 ./packaging/scripts/build-binaries.sh

# Build with version
VERSION=v1.0.0 ./packaging/scripts/build-binaries.sh
```

### Build Python Package

```bash
# Copy packaging configuration
cp packaging/pypi/pyproject.toml src/runtime/python/

# Build wheel and source distribution
cd src/runtime/python
python -m build

# Check package
twine check dist/*
```

## 🔐 Secure Release Process

### Required GitHub Secrets:

- `PYPI_API_TOKEN` - PyPI publishing token
- `DOCKER_HUB_USERNAME` - Docker Hub username
- `DOCKER_HUB_ACCESS_TOKEN` - Docker Hub access token

### Automated Release Workflow:

1. **Tag Creation**: Push git tag (e.g., `v1.0.0`)
2. **Multi-Platform Builds**: Automatically builds binaries for 6 platforms
3. **Docker Images**: Builds and pushes multi-arch images to Docker Hub + GHCR
4. **PyPI Publishing**: Uploads Python package to PyPI
5. **Security Scanning**: Runs Trivy vulnerability scans
6. **Package Updates**: Updates Homebrew and Scoop manifests

### Manual Release:

```bash
# Trigger release workflow manually
gh workflow run release.yml -f version=v1.0.0
```

### Release Re-runs:

When a release workflow fails (e.g., PyPI conflicts, Docker registry issues), you can re-run the workflow without recreating the GitHub release:

```bash
# Re-run for production deployment (pushes to registries and PyPI)
gh workflow run release.yml -f version=v1.0.1 -f environment=production

# Re-run for testing (builds only, no publishing)
gh workflow run release.yml -f version=v1.0.1 -f environment=test
```

**Benefits:**
- Preserves original release timestamp and history
- No need to delete and recreate GitHub releases
- Allows iterative fixes without losing release context
- Supports both production deploys and test builds

## 📋 Supported Architectures

### Docker Images:

- `linux/amd64` - Intel/AMD 64-bit
- `linux/arm64` - ARM 64-bit (Apple Silicon, Graviton)

### Go Binaries:

- `linux/amd64` - Linux Intel/AMD 64-bit
- `linux/arm64` - Linux ARM 64-bit
- `darwin/amd64` - macOS Intel
- `darwin/arm64` - macOS Apple Silicon

**Windows Support**: Use Docker containers or WSL2 with Linux binaries

## 🔍 Quality Assurance

### Automated Checks:

- **Security Scanning**: Trivy vulnerability scanning for Docker images
- **Package Verification**: Automated testing of Python package installation
- **Binary Testing**: Cross-platform binary functionality tests
- **Checksum Generation**: SHA256 checksums for all release artifacts

### Manual Testing:

```bash
# Test Docker images
docker run --rm mcpmesh/registry:latest --version
docker run --rm mcpmesh/cli:latest version

# Test binaries
./dist/linux_amd64/meshctl version
./dist/darwin_arm64/registry --help

# Test Python package
pip install dist/*.whl
python -c "import mcp_mesh; print(mcp_mesh.__version__)"
```

## 🎯 Release Checklist

Before creating a release:

- [ ] Update version in `src/runtime/python/src/mcp_mesh/__init__.py`
- [ ] Update CHANGELOG.md with new features and fixes
- [ ] Test local builds: `./packaging/scripts/build-binaries.sh`
- [ ] Test Docker builds: `./packaging/scripts/build-docker.sh`
- [ ] Verify all tests pass: `make test-all`
- [ ] Create and push git tag: `git tag v1.0.0 && git push origin v1.0.0`
- [ ] Monitor GitHub Actions for successful release
- [ ] Verify packages are available on all channels

## 📞 Support

For packaging issues:

- **Docker**: Check [build-docker.sh](scripts/build-docker.sh) script
- **Binaries**: Check [build-binaries.sh](scripts/build-binaries.sh) script
- **PyPI**: Check [pyproject.toml](pypi/pyproject.toml) configuration
- **CI/CD**: Check [release.yml](../.github/workflows/release.yml) workflow

Create issues at: https://github.com/dhyansraj/mcp-mesh/issues
