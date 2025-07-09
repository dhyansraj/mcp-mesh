# Agent Development with MCP Mesh Source

Quick reference for developing complex agents while simultaneously working on the MCP Mesh framework.

## 🚀 **Quick Setup**

```bash
# From mcp-mesh project root
source .venv/bin/activate
pip install -e .                                    # Framework editable
pip install -e examples/complex/data_processor_agent/ # Agent editable

# Verify setup
python -c "import mcp_mesh; print('✅ Framework ready')"
python -c "from data_processor_agent.config import get_settings; print(f'✅ Agent: {get_settings().agent_name}')"
```

## 🏗️ **Development Workflow**

### **Environment Structure**
```
mcp-mesh/                                    # Project root
├── .venv/                                   # Shared virtual environment
├── mcp_mesh/                                # Framework code (editable install)
├── examples/complex/data_processor_agent/   # Multi-file agent (editable install)
└── pyproject.toml                           # Framework packaging
```

### **Typical Development Session**

```bash
# 1. Activate shared environment
source .venv/bin/activate

# 2. Work on framework
cd mcp-mesh/
# Edit mcp_mesh/ files - changes are immediately available

# 3. Test framework changes with agent
cd examples/complex/data_processor_agent/
python test_structure.py                    # Test package structure
python -m data_processor_agent              # Test full agent

# 4. Work on agent 
# Edit data_processor_agent/ files - changes are immediately available
python -m data_processor_agent              # Test immediately

# 5. Run framework tests
cd ../../..                                 # Back to project root
pytest tests/
```

## 🔧 **Installation Details**

### **What gets installed:**
- `mcp-mesh`: Editable install from project root
- `data_processor_agent`: Editable install from examples directory
- All dependencies in shared `.venv`

### **Benefits:**
- ✅ Single environment to manage
- ✅ Framework changes immediately available to agents
- ✅ Agent changes immediately testable
- ✅ Consistent dependency versions
- ✅ No reinstalls needed for changes

## 📦 **For Different User Types**

### **Framework Developer (You/Me)**
```bash
# Use shared .venv with editable installs
./examples/complex/data_processor_agent/scripts/dev-setup.sh setup
source .venv/bin/activate

# Work on both framework and agents simultaneously
```

### **Agent Developer (Users)**
```bash
# Install released mcp-mesh
pip install mcp-mesh

# Create their own agent
pip install -e my_custom_agent/

# Or use our example as template
pip install -e examples/complex/data_processor_agent/
```

### **Production Deployment**
```bash
# Install from PyPI
pip install mcp-mesh
pip install my-published-agent

# Or from wheel
pip install my_agent-1.0.0-py3-none-any.whl
```

## 🛠️ **Development Commands**

### **Environment Management**
```bash
# Setup/check status
./examples/complex/data_processor_agent/scripts/dev-setup.sh status
./examples/complex/data_processor_agent/scripts/dev-setup.sh setup
./examples/complex/data_processor_agent/scripts/dev-setup.sh cleanup

# Manual activation
source .venv/bin/activate
```

### **Testing**
```bash
# Test framework
pytest tests/

# Test agent structure
cd examples/complex/data_processor_agent/
python test_structure.py

# Test agent functionality
python -m data_processor_agent
```

### **Code Quality**
```bash
# Framework code quality
black mcp_mesh/
mypy mcp_mesh/

# Agent code quality  
cd examples/complex/data_processor_agent/
black data_processor_agent/
mypy data_processor_agent/
```

## 🔄 **Iteration Cycle**

1. **Make framework changes** in `mcp_mesh/`
2. **Test immediately** with agent: `python -m data_processor_agent`
3. **Make agent changes** in `data_processor_agent/`
4. **Test immediately** - no reinstall needed
5. **Commit framework changes** 
6. **Commit agent improvements**

## 🐛 **Troubleshooting**

### **Import Errors**
```bash
# Check if packages are properly installed
pip list | grep mcp-mesh
pip show mcp-mesh                    # Should show editable install
pip show mcp-mesh-data-processor-agent

# Reinstall if needed
pip install -e .                     # From mcp-mesh root
pip install -e examples/complex/data_processor_agent/
```

### **Environment Issues**
```bash
# Check environment status
./examples/complex/data_processor_agent/scripts/dev-setup.sh status

# Clean start
./examples/complex/data_processor_agent/scripts/dev-setup.sh cleanup
./examples/complex/data_processor_agent/scripts/dev-setup.sh setup
```

### **Package Conflicts**
```bash
# Check for conflicting installations
pip list | grep mcp
pip uninstall mcp-mesh mcp-mesh-data-processor-agent

# Clean reinstall
./examples/complex/data_processor_agent/scripts/dev-setup.sh setup
```

## 📋 **Quick Reference Commands**

```bash
# Environment setup
./examples/complex/data_processor_agent/scripts/dev-setup.sh setup

# Activate
source .venv/bin/activate

# Test agent
cd examples/complex/data_processor_agent && python -m data_processor_agent

# Test framework  
cd mcp-mesh && pytest tests/

# Check status
./examples/complex/data_processor_agent/scripts/dev-setup.sh status
```

## 🎯 **For Different Scenarios**

### **Scenario 1: Pure Framework Development**
- Use existing `.venv`
- Install mcp-mesh in editable mode
- Test with simple agents from `examples/simple/`

### **Scenario 2: Pure Agent Development** 
- Create separate venv
- `pip install mcp-mesh` (released version)
- Develop agent independently

### **Scenario 3: Framework + Agent Development (Our Case)**
- Use shared `.venv` 
- Both mcp-mesh and agent in editable mode
- Simultaneous development and testing

This setup optimizes for our specific use case where we need to improve both the framework and create sophisticated agent examples.