# Multi-File Agent Development Setup

## 🎯 **For MCP Mesh Framework + Agent Development**

When you're simultaneously working on the MCP Mesh framework and developing complex agents, use this shared environment setup.

### **Quick Setup Commands**

```bash
# 1. Navigate to mcp-mesh project root
cd /media/psf/Home/workspace/github/mcp-mesh

# 2. Activate the existing .venv (or create if needed)
source .venv/bin/activate

# 3. Install mcp-mesh in editable mode (framework development)
pip install -e .

# 4. Install the complex agent in editable mode (agent development)
pip install -e examples/complex/data_processor_agent/

# 5. Verify both are working
python -c "import mcp_mesh; print(f'✅ Framework: {mcp_mesh.__version__}')"
python -c "from data_processor_agent.config import get_settings; print(f'✅ Agent: {get_settings().agent_name}')"
```

### **Development Workflow**

```bash
# Always start from project root
cd /media/psf/Home/workspace/github/mcp-mesh
source .venv/bin/activate

# Work on framework
# Edit files in mcp_mesh/ - changes are immediately available

# Test framework changes with agent
cd examples/complex/data_processor_agent/
python test_structure.py          # Test package structure
python -m data_processor_agent    # Test full agent (may fail due to MCP deps, that's ok)

# Work on agent
# Edit files in data_processor_agent/ - changes are immediately available
python test_structure.py          # Test immediately

# Go back to framework work
cd ../../..                       # Back to project root
pytest tests/                     # Run framework tests
```

## 📦 **What This Setup Provides**

### **Shared Environment Benefits**
- ✅ Single `.venv` to manage
- ✅ Framework changes immediately available to agents  
- ✅ Agent changes immediately testable
- ✅ Consistent dependency versions
- ✅ No reinstalls needed for code changes

### **Installation Details**
```bash
# After setup, these are installed in editable mode:
pip list | grep mcp-mesh
# mcp-mesh                   0.1.8    /media/psf/Home/workspace/github/mcp-mesh
# mcp-mesh-data-processor-agent 1.0.0 /media/psf/Home/workspace/github/mcp-mesh/examples/complex/data_processor_agent
```

## 🔄 **Typical Development Session**

```bash
# 1. Start the session
cd /media/psf/Home/workspace/github/mcp-mesh
source .venv/bin/activate

# 2. Work on framework improvements
vim mcp_mesh/decorators.py              # Make framework changes
vim mcp_mesh/runtime/agent_lifecycle.py # Framework changes are immediately available

# 3. Test with complex agent
cd examples/complex/data_processor_agent/
python test_structure.py               # Quick validation test
# python -m data_processor_agent       # Full test (may need registry for MCP features)

# 4. Improve agent implementation
vim data_processor_agent/main.py       # Agent changes
vim data_processor_agent/tools/        # Tool improvements

# 5. Test agent changes immediately
python test_structure.py               # Changes are immediately available

# 6. Back to framework for more changes
cd ../../..
pytest tests/unit/test_decorators.py   # Test specific framework features
```

## 🛠️ **For Different Scenarios**

### **Scenario 1: You're Mainly Working on Framework**
```bash
cd /media/psf/Home/workspace/github/mcp-mesh
source .venv/bin/activate
pip install -e .

# Use simple agents for testing
python examples/simple/hello_world.py
```

### **Scenario 2: You're Mainly Working on Complex Agents**
```bash
cd /media/psf/Home/workspace/github/mcp-mesh
source .venv/bin/activate
pip install -e .                                    # Get latest framework
pip install -e examples/complex/data_processor_agent/

# Focus on agent development
cd examples/complex/data_processor_agent/
# Edit agent code, test immediately
```

### **Scenario 3: You're Working on Both (Our Case)**
```bash
cd /media/psf/Home/workspace/github/mcp-mesh
source .venv/bin/activate
pip install -e .                                    # Framework editable
pip install -e examples/complex/data_processor_agent/ # Agent editable

# Iterate on both simultaneously
# Framework changes immediately available to agent
# Agent changes immediately testable
```

## 🐛 **Troubleshooting**

### **"Module not found" errors**
```bash
# Check installations
pip list | grep mcp-mesh
pip show mcp-mesh                           # Should show editable install
pip show mcp-mesh-data-processor-agent     # Should show editable install

# Reinstall if needed
pip install -e .                            # From mcp-mesh root
pip install -e examples/complex/data_processor_agent/
```

### **Import errors in agent**
```bash
# Test the package structure (this should work)
cd examples/complex/data_processor_agent/
python test_structure.py

# The agent main.py might fail due to MCP dependencies
# That's expected in development - focus on the package structure
```

### **Dependency conflicts**
```bash
# Clean slate
pip uninstall mcp-mesh mcp-mesh-data-processor-agent
pip install -e .
pip install -e examples/complex/data_processor_agent/
```

## 📊 **Environment Status Check**

```bash
# Check current environment
echo "Virtual env: $VIRTUAL_ENV"
echo "Python: $(which python)"
echo "Packages:"
pip list | grep -E "(mcp-mesh|data-processor)"

# Test imports
python -c "
try:
    import mcp_mesh
    print(f'✅ Framework: mcp-mesh {mcp_mesh.__version__}')
except Exception as e:
    print(f'❌ Framework: {e}')

try:
    from data_processor_agent.config import get_settings
    print(f'✅ Agent: {get_settings().agent_name}')
except Exception as e:
    print(f'❌ Agent: {e}')
"
```

## 🎯 **Quick Commands Reference**

```bash
# Setup
cd /media/psf/Home/workspace/github/mcp-mesh
source .venv/bin/activate
pip install -e .
pip install -e examples/complex/data_processor_agent/

# Framework work
cd /media/psf/Home/workspace/github/mcp-mesh
# Edit mcp_mesh/
pytest tests/

# Agent work  
cd examples/complex/data_processor_agent/
# Edit data_processor_agent/
python test_structure.py

# Test both together
cd examples/complex/data_processor_agent/
python test_structure.py    # This should always work
# python -m data_processor_agent  # This may need full MCP setup
```

This setup gives you the best of both worlds: fast iteration on framework code with immediate testing using sophisticated multi-file agents.