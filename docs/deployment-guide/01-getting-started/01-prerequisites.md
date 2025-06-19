# Prerequisites

> Quick checklist before installing MCP Mesh

## Essential Requirements

You only need two things:

### 1. Python 3.9+

```bash
# Check your Python version
python --version

# Should show: Python 3.9.x or higher
```

**Don't have Python 3.9+?**

- **macOS**: `brew install python@3.11`
- **Ubuntu/Debian**: `sudo apt install python3.11`
- **Windows**: Download from [python.org](https://python.org)

### 2. pip (Python Package Manager)

```bash
# Check pip is installed
pip --version

# If not installed, get it with:
python -m ensurepip --upgrade
```

That's it! You're ready to install MCP Mesh.

## Recommended Setup

For the best experience, we recommend:

### Use a Virtual Environment

```bash
# Create a virtual environment
python -m venv mcp-env

# Activate it
source mcp-env/bin/activate  # Linux/macOS
# or
mcp-env\Scripts\activate     # Windows
```

### Have curl or wget

```bash
# For testing your agents
curl --version
```

## System Support

- ✅ **Linux**: All distributions with Python 3.9+
- ✅ **macOS**: 10.15 (Catalina) or later
- ✅ **Windows**: Windows 10/11 (WSL2 recommended for best experience)

## Quick Check Script

```bash
# Run this to check everything at once
python3 -c "
import sys
print('Python:', sys.version)
print('✅ Ready!' if sys.version_info >= (3, 9) else '❌ Need Python 3.9+')
"
```

## Optional but Helpful

### Network Ports

MCP Mesh will use these ports (configurable):

- **8000**: Registry (starts automatically)
- **8080-8090**: Your agents (you choose)

### Storage

- **500MB**: For MCP Mesh and dependencies
- **100MB**: For logs and data

## Next Steps

Once all prerequisites are met, proceed to [Installation](./02-installation.md) →

---

💡 **Tip**: If you encounter issues, our [Troubleshooting Guide](../10-operations/03-troubleshooting.md) covers common problems and solutions.

📚 **Note**: For containerized deployments (Docker/Kubernetes), different prerequisites apply. See [Docker Deployment](../03-docker-deployment.md) or [Kubernetes Basics](../04-kubernetes-basics.md).

## 🔧 Troubleshooting

### Common Issues

1. **Python version mismatch** - Use `pyenv` or `conda` to manage multiple Python versions
2. **Permission denied on ports** - Either use higher ports (>1024) or run with appropriate permissions
3. **Git not found** - Install via package manager (`apt`, `brew`, `choco`)
4. **Virtual environment issues** - Ensure you're using the Python 3 venv module, not virtualenv

For detailed solutions, see our [Troubleshooting Guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Python 3.8 and below**: Not supported due to typing features used
- **32-bit systems**: Limited support, 64-bit recommended
- **Network proxies**: May require additional configuration
- **Corporate firewalls**: May block agent communication on custom ports

## 📝 TODO

- [ ] Add automated prerequisite installer script
- [ ] Support for Python 3.13 when released
- [ ] Add Podman as Docker alternative
- [ ] Create offline installation package
- [ ] Add ARM64 native support verification
