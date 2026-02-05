# Prerequisites

> What you need before building MCP Mesh agents with TypeScript

**MCP Mesh supports Python, Java, and TypeScript.** Choose the language that fits your needs—or use all three in the same mesh.

## Windows Users

`meshctl` and `mcp-mesh-registry` require a Unix-like environment on Windows:

- **WSL2** (recommended) - Full Linux environment
- **Git Bash** - Lightweight option

Alternatively, use Docker Desktop for containerized development.

## Local Development

### Node.js 18+

```bash
# Check version
node --version   # Need 18+
npm --version

# Install if needed
brew install node          # macOS
sudo apt install nodejs    # Ubuntu/Debian
```

### TypeScript SDK

```bash
# In your agent directory
npm init -y
npm install @mcpmesh/sdk

# Verify
npx tsx -e "import { mesh } from '@mcpmesh/sdk'; console.log('Ready!')"
```

### meshctl CLI

```bash
npm install -g @mcpmesh/cli

# Verify
meshctl --version
```

### Quick Start (TypeScript)

```bash
# 1. Scaffold TypeScript agent
meshctl scaffold --name hello --agent-type basic --lang typescript

# 2. Install dependencies
cd hello
npm install

# 3. Run agent - meshctl uses npx tsx automatically
meshctl start src/index.ts --debug
```

## Docker Deployment

For containerized deployments.

### Docker & Docker Compose

```bash
# Check installation
docker --version
docker compose version
```

### MCP Mesh Images

| Image                            | Description                 |
| -------------------------------- | --------------------------- |
| `mcpmesh/registry:0.9`           | Registry service            |
| `mcpmesh/python-runtime:0.9`     | Python runtime with SDK     |
| `mcpmesh/java-runtime:0.9`       | Java runtime with SDK       |
| `mcpmesh/typescript-runtime:0.9` | TypeScript runtime with SDK |

```bash
# Pull images
docker pull mcpmesh/registry:0.9
docker pull mcpmesh/python-runtime:0.9
docker pull mcpmesh/java-runtime:0.9
docker pull mcpmesh/typescript-runtime:0.9
```

### Generate Docker Compose

```bash
meshctl scaffold --compose              # Basic stack
meshctl scaffold --compose --observability  # With Grafana/Tempo
```

## Kubernetes Deployment

For production Kubernetes clusters.

### kubectl & Helm

```bash
kubectl version --client
helm version
```

## Version Compatibility

| Component  | Minimum | Recommended |
| ---------- | ------- | ----------- |
| Node.js    | 18      | 20+         |
| Docker     | 20.10   | Latest      |
| Kubernetes | 1.25    | 1.28+       |
| Helm       | 3.10    | 3.14+       |

## See Also

- `meshctl man deployment` - Deployment patterns
- `meshctl man environment` - Configuration options
- `meshctl scaffold --help` - Generate agents
