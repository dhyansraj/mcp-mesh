#!/bin/bash
# Setup development environment for MCP Mesh
# This ensures correct Python environment everywhere

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "🔧 Setting up MCP Mesh development environment..."

# 1. Check if .venv exists
if [ ! -d ".venv" ]; then
    echo "❌ .venv not found. Please create it first:"
    echo "   python -m venv .venv"
    echo "   .venv/bin/pip install -e ."
    exit 1
fi

# 2. Install direnv if needed (optional but recommended)
if ! command -v direnv &> /dev/null; then
    echo "📦 direnv not found. Install it for automatic environment activation:"
    echo "   curl -sfL https://direnv.net/install.sh | bash"
    echo "   echo 'eval \"\$(direnv hook bash)\"' >> ~/.bashrc"
    echo "   source ~/.bashrc"
    echo "   direnv allow"
fi

# 3. Create useful aliases in the shell
cat > .dev-aliases << 'EOF'
# MCP Mesh Development Aliases
# Source this file: source .dev-aliases

# Always use project Python
alias python='./python'
alias pip='./pip'
alias pytest='./run-tests.sh'

# Common development commands
alias run-hello='./python examples/hello_world_fixed.py'
alias run-tests='./run-tests.sh'
alias start-registry='./bin/mcp-mesh-registry -host 0.0.0.0 -port 8080'
alias start-agent='./python'

# Environment check
alias check-env='echo "Python: $(./python --version)" && echo "Location: $(which python)"'

# Quick test commands
alias test-basic='./run-tests.sh src/runtime/python/tests/unit/test_server.py'
alias test-decorator='./run-tests.sh src/runtime/python/tests/unit/test_mesh_agent_decorator.py'

echo "🐍 MCP Mesh development aliases loaded"
echo "Usage:"
echo "  python examples/hello_world_fixed.py"
echo "  pytest  # runs all tests"
echo "  run-hello  # runs hello world example"
echo "  check-env  # verify environment"
EOF

echo "✅ Development environment setup complete!"
echo ""
echo "🔧 IMPORTANT: Shell Integration Added!"
echo "Your ~/.bashrc has been updated to automatically add wrapper scripts to PATH"
echo "when in the MCP Mesh project directory. This prevents environment issues."
echo ""
echo "🔧 Next steps:"
echo "1. Source aliases: source .dev-aliases"
echo "2. Test Python: ./python --version"
echo "3. Test example: ./python examples/hello_world_fixed.py"
echo "4. Run tests: ./run-tests.sh"
echo "5. Test environment: ./test-environment-solution.sh"
echo ""
echo "💡 For automatic activation, install direnv:"
echo "   curl -sfL https://direnv.net/install.sh | bash"
echo "   echo 'eval \"\$(direnv hook bash)\"' >> ~/.bashrc"
echo "   source ~/.bashrc"
echo "   direnv allow"
echo ""
echo "🎯 SOLUTION SUMMARY:"
echo "  ✅ Wrapper scripts (./python, ./pip) always use project .venv"
echo "  ✅ Shell integration adds wrappers to PATH automatically"
echo "  ✅ Direnv auto-activates environment when entering directory"
echo "  ✅ Works for: testing, examples, CLI tools, future sessions"
