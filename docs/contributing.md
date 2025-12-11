# Contributing to MCP Mesh

> Guidelines for contributing to the MCP Mesh project

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/mcp-mesh.git
   cd mcp-mesh
   ```
3. **Set up development environment**:
   ```bash
   make install-dev
   source .venv/bin/activate
   ```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Changes

- Follow existing code style and patterns
- Add tests for new functionality
- Update documentation as needed

### 3. Test Your Changes

```bash
# Run tests
make test

# Run linting
make lint

# Build to verify
make build
```

### 4. Commit and Push

```bash
git add .
git commit -m "feat: add new feature description"
git push origin feature/your-feature-name
```

**Commit message format:**

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation only
- `refactor:` - Code refactoring
- `test:` - Adding tests
- `chore:` - Maintenance tasks

### 5. Create Pull Request

1. Go to [MCP Mesh GitHub](https://github.com/dhyansraj/mcp-mesh)
2. Click "New Pull Request"
3. Select your branch
4. Fill in the PR template
5. Request review

## Project Structure

```
mcp-mesh/
├── cmd/                    # Go CLI tools (meshctl, registry)
├── src/runtime/python/     # Python SDK
├── examples/               # Example agents
├── docs/                   # Documentation (MkDocs)
├── helm/                   # Helm charts
└── Makefile               # Build automation
```

## Code Guidelines

### Python (SDK)

- Python 3.9+ compatible
- Type hints required
- Docstrings for public functions
- Follow existing patterns in `src/runtime/python/_mcp_mesh/`

### Go (CLI/Registry)

- Go 1.23+
- Run `go fmt` before committing
- Follow Go conventions

### Documentation

- Use MkDocs Material syntax
- Test locally: `mkdocs serve`
- Keep examples runnable

## Getting Help

- **Questions**: [GitHub Discussions](https://github.com/dhyansraj/mcp-mesh/discussions)
- **Bugs**: [GitHub Issues](https://github.com/dhyansraj/mcp-mesh/issues)
- **Chat**: [Discord Community](https://discord.gg/KDFDREphWn)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to MCP Mesh!
