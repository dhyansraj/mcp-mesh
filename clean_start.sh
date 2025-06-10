#!/bin/bash
# Clean start script for MCP Mesh

echo "🧹 Cleaning up MCP Mesh environment..."

# Kill any running processes
echo "Stopping processes..."
pkill -f mcp-mesh-dev || true
pkill -f mcp-mesh-registry || true
sleep 1

# Remove old database
echo "Removing old database..."
rm -f mcp_mesh_registry.db*
rm -f dev_registry.db*

# Clear any Python cache
echo "Clearing Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

echo "✅ Cleanup complete!"
echo ""
echo "🚀 Starting fresh..."
echo "1. Start registry: mcp-mesh-registry"
echo "2. Start example: MCP_MESH_DEBUG=false mcp-mesh-dev start examples/hello_world.py"
