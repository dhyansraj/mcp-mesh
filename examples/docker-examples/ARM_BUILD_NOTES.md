# ARM Build Notes for MCP Mesh Docker Examples

## The Issues You Encountered

### 1. Go Version Mismatch (Fixed)

```
go: /src/go.mod requires go >= 1.23 (running go 1.21.13; GOTOOLCHAIN=local)
```

### 2. SQLite CGO Compilation Issue (New)

```
sqlite3-binding.c:37644:42: error: 'pread64' undeclared here (not in a function)
```

This is a common issue with `github.com/mattn/go-sqlite3` on Alpine Linux with musl libc. The `pread64`/`pwrite64` functions aren't available in musl.

## Fixes Applied

### 1. Updated Go Version

- Changed from `golang:1.21-alpine` to `golang:1.23-alpine` in registry Dockerfile
- This matches the project's `go.mod` requirement

### 2. SQLite Compatibility Fixes

- Added `CGO_CFLAGS="-D_LARGEFILE64_SOURCE"` for musl compatibility
- Added `sqlite_omit_load_extension` build tag
- Added `build-base` package for complete build tools

### 3. Added Build Dependencies

- Added `gcc musl-dev sqlite-dev build-base` for CGO builds with SQLite
- Required for the Go registry to compile with SQLite support

### 4. Alternative Debian Dockerfile

- Created `Dockerfile.debian` as a backup that uses Debian instead of Alpine
- Debian has better SQLite compatibility and avoids musl issues

### 5. Added Runtime Dependencies

- Added `wget` to runtime image for health checks

## Testing on ARM

### Option 1: Try the fixed Alpine build

```bash
cd examples/docker-examples

# Build just the registry first to test Go compilation
docker-compose build registry

# If that works, build everything
docker-compose build

# Start the services
docker-compose up
```

### Option 2: Use Debian build if Alpine fails

```bash
# Modify docker-compose.yml to use Dockerfile.debian
# Or build manually:
cd registry
docker build -f Dockerfile.debian ../../ -t mcp-mesh-registry-debian

# Then update docker-compose.yml to use this image
```

## ARM-Specific Optimizations

### If you still have issues:

1. **Use buildx for explicit ARM builds**:

```bash
docker buildx build --platform linux/arm64 -f registry/Dockerfile ../../
```

2. **Check Docker buildx support**:

```bash
docker buildx ls
```

3. **Force platform specification**:

```bash
export DOCKER_DEFAULT_PLATFORM=linux/arm64
docker-compose build
```

## Alternative: Using Pre-built Images

If builds are slow or problematic on ARM, you can modify the Dockerfiles to use pre-built binaries:

### Option 1: Build Binary Separately

```bash
# Build Go binary on host
cd ../../cmd/mcp-mesh-registry
CGO_ENABLED=1 go build -o mcp-mesh-registry

# Then use a simple runtime Dockerfile that just copies the binary
```

### Option 2: Use Multi-Stage Build Optimization

The current Dockerfiles already use multi-stage builds which should be ARM-friendly.

## Performance Notes

- ARM builds may be slower than x86 builds
- Go compilation is generally good on ARM64 (Apple Silicon)
- Python package compilation might take longer for some packages

## Verification

After building, verify the images work:

```bash
# Check image architecture
docker image inspect mcp-mesh-registry | grep Architecture

# Test registry startup
docker run --rm -p 8000:8000 mcp-mesh-registry

# Test in another terminal
curl http://localhost:8000/health
```

## If Problems Persist

1. **Check available platforms**:

```bash
docker buildx inspect --bootstrap
```

2. **Use native build without Docker Compose**:

```bash
# Build registry manually
cd registry
docker build -f Dockerfile ../../ -t mcp-mesh-registry

# Build base image manually
cd ../agents/base
docker build -f Dockerfile.base ../../ -t mcp-mesh-base
```

3. **Enable buildx if needed**:

```bash
docker buildx create --use
docker buildx inspect --bootstrap
```

The main fix was updating to Go 1.23 - this should resolve your build issue!
