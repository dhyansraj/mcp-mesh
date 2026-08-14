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

- Python 3.11+ compatible
- Type hints required
- Docstrings for public functions
- Follow existing patterns in `src/runtime/python/_mcp_mesh/`

### Python dependencies

`src/runtime/python/constraints.txt` is the Python dependency lock — the
transitive set CI tests against and the runtime images install. Every runtime
has one (`Cargo.lock`, `package-lock.json`, `Chart.lock`); this is Python's.

**Changing a Python dependency is its own PR.** It never rides along inside a
feature change or a release bump:

```bash
# after editing packaging/pypi/pyproject.toml
scripts/lock_python_deps.sh              # move only what the manifest forced

# to deliberately take newer versions of everything
scripts/lock_python_deps.sh --upgrade

python3 scripts/check_release_lockfiles.py
```

The generator runs pip-compile inside `python:3.11-slim` so the result does not
depend on whose laptop produced it, and resolves against
`packaging/pypi/pyproject.toml` — the manifest PyPI publishes, whose bounds are
tighter than the source tree's. Both are why you should not run `pip-compile`
by hand.

It is a *constraints* file, so it installs nothing; it only fixes which version
pip may pick. That is what lets one file cover linux/amd64, linux/arm64, macOS
and Python 3.11–3.14 without markers, and why an entry for `litellm` does not
put litellm back into a default install.

If you install by hand rather than via `make install-dev`, pass it:

```bash
pip install -e 'src/runtime/python/[dev]' -c src/runtime/python/constraints.txt
```

Two production incidents came from not having this: an unpinned FastMCP flipped
a DNS-rebinding default on a rebuild and returned 421 for every Kubernetes
Python provider (#1312), and an `openai` *minor* added a required response
field that broke CI while local environments stayed green (#1453).

### Go (CLI/Registry)

- Go 1.23+
- Run `go fmt` before committing
- Follow Go conventions

### Documentation

- Use MkDocs Material syntax
- Test locally: `mkdocs serve`
- Keep examples runnable

## :star: Project Status

- **Latest Release**: v3.6.0
- **Languages**: Python 3.11+, TypeScript/Node.js 18+, and Java 17+ (runtime), Go 1.23+ (registry)
- **Status**: Production-ready, actively developed

What changed in each version — breaking changes, upgrade notes and fixes — is in the [Release Notes](release-notes.md).

---

## :pray: Acknowledgments

- **[Anthropic](https://anthropic.com)** for creating the MCP protocol
- **[Google](https://a2a-protocol.org/)** for the A2A protocol
- **[FastMCP](https://github.com/jlowin/fastmcp)** for excellent MCP server foundations
- **[Kubernetes](https://kubernetes.io)** community for the infrastructure platform
- All **contributors** who help make MCP Mesh better

---

## Getting Help

- **Questions**: [GitHub Discussions](https://github.com/dhyansraj/mcp-mesh/discussions)
- **Bugs**: [GitHub Issues](https://github.com/dhyansraj/mcp-mesh/issues)
- **Chat**: [Discord Community](https://discord.gg/KDFDREphWn)
- **Examples**: [Working code examples](https://github.com/dhyansraj/mcp-mesh/tree/main/examples)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to MCP Mesh!
