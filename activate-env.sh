#!/bin/bash
# Manual environment activation script
# Usage: source activate-env.sh
# This script forces the correct environment even when other tools interfere

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🔧 Manually activating MCP Mesh environment..."

# Activate the virtual environment
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
    echo "✅ Activated .venv"
else
    echo "❌ .venv not found at $SCRIPT_DIR/.venv"
    return 1
fi

# Add wrapper scripts to PATH (highest priority)
export PATH="$SCRIPT_DIR:$PATH"
echo "✅ Added wrapper scripts to PATH"

# Set PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR/src/runtime/python/src:$PYTHONPATH"
echo "✅ Set PYTHONPATH"

# Set MCP Mesh environment variables
export MCP_MESH_REGISTRY_URL="http://localhost:8080"
export MCP_MESH_LOG_LEVEL="INFO"

# Verify the setup
echo ""
echo "🔍 Environment verification:"
echo "  Python: $(which python)"
echo "  Python executable: $(python -c 'import sys; print(sys.executable)')"
echo "  Pip: $(which pip)"
echo ""
echo "✅ Environment activated successfully!"
echo "💡 Now you can run: python examples/hello_world_fixed.py"
