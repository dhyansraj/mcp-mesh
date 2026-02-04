# Prerequisites

> What you need before building MCP Mesh agents

**MCP Mesh supports Python, TypeScript, and Java.** Choose the language that fits your needs—or use multiple languages in the same mesh.

## Windows Users

`meshctl` and `mcp-mesh-registry` require a Unix-like environment on Windows:

- **WSL2** (recommended) - Full Linux environment
- **Git Bash** - Lightweight option

Alternatively, use Docker Desktop for containerized development.

## Local Development

For developing and testing agents locally. Choose your preferred language:

### Python 3.11+

```bash
# Check version
python3 --version  # Need 3.11+

# Install if needed
brew install python@3.11          # macOS
sudo apt install python3.11       # Ubuntu/Debian
```

### Virtual Environment (Recommended)

Create a virtual environment at your **project root** (where you run `meshctl`).
All agents share this single venv - do not create separate venvs inside agent folders.

> **Note:** `meshctl` is a Go binary that auto-detects `.venv` in the current directory.
> You only need to activate the venv for `pip` commands - meshctl commands work without activation.

```bash
# At project root - create venv (one-time setup)
python3.11 -m venv .venv

# Activate only when using pip
source .venv/bin/activate         # macOS/Linux
.venv\Scripts\activate            # Windows
pip install --upgrade pip
```

### MCP Mesh SDK

```bash
pip install "mcp-mesh>=0.8,<0.9"

# Verify
python -c "import mesh; print('Ready!')"
```

### Quick Start (Python)

```bash
# 1. Create venv and install SDK (one-time setup)
python3.11 -m venv .venv
source .venv/bin/activate    # Only needed for pip
pip install --upgrade pip
pip install "mcp-mesh>=0.8,<0.9"
deactivate                   # Can deactivate after pip install

# 2. Scaffold agents - meshctl auto-detects .venv (no activation needed)
meshctl scaffold --name hello --agent-type basic
meshctl scaffold --name assistant --agent-type llm-agent

# 3. Run agent - meshctl uses .venv/bin/python automatically
meshctl start hello/main.py --debug
```

### Node.js 18+ (for TypeScript)

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

### Java 17+ / Maven

```bash
# Check versions
java -version    # Need 17+
mvn -version     # Apache Maven 3.8+

# Install if needed
brew install openjdk@17      # macOS
brew install maven           # macOS
sudo apt install openjdk-17-jdk maven   # Ubuntu/Debian
```

### MCP Mesh Spring Boot Starter

```xml
<!-- In your pom.xml -->
<dependency>
    <groupId>io.mcp-mesh</groupId>
    <artifactId>mcp-mesh-spring-boot-starter</artifactId>
    <version>0.9.0-beta.3</version>
</dependency>
```

### Quick Start (Java)

```bash
# 1. Use an example as template
cp -r examples/java/basic-tool-agent my-agent
cd my-agent

# 2. Build and run
mvn spring-boot:run

# 3. Or use meshctl (auto-detects pom.xml)
meshctl start my-agent --debug
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
| `mcpmesh/registry:0.8`           | Registry service            |
| `mcpmesh/python-runtime:0.8`     | Python runtime with SDK     |
| `mcpmesh/typescript-runtime:0.8` | TypeScript runtime with SDK |

```bash
# Pull images
docker pull mcpmesh/registry:0.8
docker pull mcpmesh/python-runtime:0.8
docker pull mcpmesh/typescript-runtime:0.8
```

### Generate Docker Compose

```bash
meshctl scaffold --compose              # Basic stack
meshctl scaffold --compose --observability  # With Grafana/Tempo
```

## Kubernetes Deployment

For production Kubernetes clusters.

### kubectl

```bash
kubectl version --client
```

### Helm 3+

```bash
helm version
```

### MCP Mesh Helm Charts

Available from OCI registry (no `helm repo add` needed):

| Chart                                             | Description                   |
| ------------------------------------------------- | ----------------------------- |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core`  | Registry + DB + Observability |
| `oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent` | Deploy agents                 |

```bash
# Install core infrastructure
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.9.0-beta.3 \
  -n mcp-mesh --create-namespace

# Deploy an agent
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.9.0-beta.3 \
  -n mcp-mesh \
  -f helm-values.yaml
```

### Cluster Options

- **Minikube** - Local testing
- **Kind** - Lightweight local clusters
- **Cloud** - GKE, EKS, AKS for production

## Version Compatibility

| Component  | Minimum | Recommended |
| ---------- | ------- | ----------- |
| Python     | 3.11    | 3.12        |
| Node.js    | 18      | 20+         |
| Java       | 17      | 17+         |
| Maven      | 3.8     | 3.9+        |
| Docker     | 20.10   | Latest      |
| Kubernetes | 1.25    | 1.28+       |
| Helm       | 3.10    | 3.14+       |

## See Also

- `meshctl man deployment` - Deployment patterns
- `meshctl man environment` - Configuration options
- `meshctl scaffold --help` - Generate agents
