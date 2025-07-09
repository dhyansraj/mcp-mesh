# Complex MCP Mesh Agent Examples

This directory contains advanced examples demonstrating how to build production-ready, multi-file MCP Mesh agents that go beyond simple single-script implementations.

## Overview

While the `examples/simple/` directory shows basic MCP Mesh functionality, this `examples/complex/` directory demonstrates:

- **Production-scale agent architecture** with proper Python packaging
- **Modular code organization** with utilities, tools, and configuration management
- **Multi-agent dependency injection** with real service dependencies
- **Comprehensive development workflows** with testing, CI/CD, and deployment
- **Real-world patterns** for error handling, logging, caching, and external integrations

## Examples

### 1. Data Processor Agent (`data_processor_agent/`)

A comprehensive multi-file agent demonstrating advanced data processing capabilities with **real dependency injection** from weather and LLM services.

**Features:**
- **Multi-format data parsing**: CSV, JSON, Excel, Parquet, TSV
- **Statistical analysis**: Descriptive statistics, correlation analysis, outlier detection
- **Data transformation**: Filtering, sorting, aggregation, cleaning operations
- **Export functionality**: Multiple output formats with metadata
- **Service dependencies**: Integrates with weather-service and llm-service
- **Caching system**: Performance optimization for repeated operations
- **Configuration management**: Environment-based settings with validation
- **Enhanced proxy configuration**: Timeouts, retries, streaming, custom headers
- **Proper Python packaging**: `pyproject.toml` with dependencies and scripts

**Structure:**
```
data_processor_agent/
├── __init__.py              # Package initialization
├── __main__.py              # Entry point for python -m execution
├── main.py                  # Main agent with MCP tools and dual decorators
├── simple_main.py           # Simplified version following simple examples pattern
├── pyproject.toml           # Python packaging configuration
├── README.md                # Detailed documentation
├── Dockerfile               # Multi-stage Docker build
├── docker-compose.yml       # Development environment
├── config/                  # Configuration management
│   ├── __init__.py
│   └── settings.py          # Environment-based configuration
├── tools/                   # Core processing tools
│   ├── __init__.py
│   ├── data_parsing.py      # DataParser class
│   ├── data_transformation.py # DataTransformer class
│   ├── statistical_analysis.py # StatisticalAnalyzer class
│   └── export_tools.py      # DataExporter class
├── utils/                   # Shared utilities
│   ├── __init__.py
│   ├── data_validation.py   # ValidationError, DataValidator
│   ├── data_formatting.py   # DataFormatter class
│   └── cache_manager.py     # CacheManager with TTL support
└── scripts/                 # Development helper scripts
```

## Multi-Agent Architecture

This example demonstrates a **complete multi-agent ecosystem** with real service dependencies:

### Required Services

The data processor agent depends on two service agents from `examples/advanced/`:

1. **Weather Service Agent** (`examples/advanced/weather_agent.py`)
   - **Capability**: `weather-service`
   - **Port**: 9094
   - **Features**: Auto-detects location via IP, provides real weather data using Open-Meteo API

2. **LLM Service Agent** (`examples/advanced/llm_chat_agent.py`)
   - **Capability**: `llm-service`
   - **Port**: 9093
   - **Features**: Text processing, data interpretation, system prompts, conversation management

3. **Data Processor Agent** (`examples/complex/data_processor_agent/`)
   - **Dependencies**: `["weather-service", "llm-service"]`
   - **Port**: 9092
   - **Features**: Complex multi-file agent with dependency injection

## Quick Start - Full Multi-Agent Setup

### 1. Start Required Services

**Terminal 1 - Weather Service:**
```bash
cd examples/advanced
python weather_agent.py
```

**Terminal 2 - LLM Service:**
```bash
cd examples/advanced
python llm_chat_agent.py
```

**Terminal 3 - Data Processor (with dependencies):**
```bash
cd examples/complex/data_processor_agent
python main.py
```

### 2. Verify All Agents Registered

```bash
# Check all agents are registered with dependencies resolved
curl -s http://localhost:8000/agents | jq '.agents[] | {name: .name, endpoint: .endpoint, dependencies_resolved: .dependencies_resolved}'
```

Expected output:
```json
{
  "name": "weather-agent-472dbc15",
  "endpoint": "http://10.211.55.3:9094",
  "dependencies_resolved": 0
}
{
  "name": "llm-chat-agent-ce2b56ad", 
  "endpoint": "http://10.211.55.3:9093",
  "dependencies_resolved": 0
}
{
  "name": "data-processor-c271bd5b",
  "endpoint": "http://10.211.55.3:9090",
  "dependencies_resolved": 3
}
```

### 3. Test Service Integration

**Test Weather Service:**
```bash
curl -s -X POST http://localhost:9094/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_local_weather",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text.formatted'
```

**Test LLM Service:**
```bash
curl -s -X POST http://localhost:9093/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "process_text_with_llm",
      "arguments": {
        "text": "Weather data shows 70°F temperature with overcast conditions",
        "task": "analyze"
      }
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text.result'
```

**Test Data Processor (with dependency injection):**
```bash
curl -s -X POST http://localhost:9090/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_agent_status",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text.dependencies'
```

### 4. Alternative Execution Methods

**Local Development:**
```bash
cd data_processor_agent
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
python -m data_processor_agent
```

**Docker Deployment:**
```bash
docker build -t data-processor-agent .
docker run -p 9092:9092 data-processor-agent
```

**Docker Compose (full stack with registry):**
```bash
docker-compose up -d
```

## Architecture Patterns Demonstrated

### 1. **Dual Decorator Pattern**
All tools use FastMCP + MCP Mesh dual decorators:
```python
@app.tool()                    # FastMCP decorator FIRST
@mesh.tool(                    # MCP Mesh decorator SECOND
    capability="data_processing", 
    dependencies=["weather-service", "llm-service"],
    # Enhanced proxy configuration
    timeout=300,
    retry_count=3,
    streaming=True,
    custom_headers={
        "X-Service-Type": "data-processor",
        "X-Processing-Level": "advanced"
    }
)
def parse_data_file(
    file_path: str, 
    file_format: Optional[str] = None,
    weather_service: mesh.McpMeshAgent = None,  # Dependency injection
    llm_service: mesh.McpMeshAgent = None       # Dependency injection
) -> Dict[str, Any]:
    # Implementation with injected dependencies
    pass
```

### 2. **Enhanced Proxy Configuration (v0.3+)**
Direct kwargs for advanced proxy features:
```python
@mesh.tool(
    capability="data_processing",
    # Enhanced proxy configuration as direct kwargs
    timeout=300,              # 5-minute timeout
    retry_count=3,           # 3 retry attempts  
    streaming=True,          # Enable streaming
    custom_headers={         # Custom HTTP headers
        "X-Service-Type": "data-processor",
        "X-Processing-Level": "advanced"
    }
)
```

### 3. **Auto-Run Pattern**
All agents use `auto_run=True` for zero-boilerplate startup:
```python
@mesh.agent(
    name="data-processor",
    version="1.0.0", 
    http_port=9092,
    auto_run=True    # MCP Mesh handles everything automatically
)
class DataProcessorAgent:
    pass
```

### 4. **Modular Package Structure**
- Clear separation of concerns with `config/`, `tools/`, `utils/` modules
- Proper Python package initialization and exports
- Flexible import strategies for both package and standalone execution

### 5. **Service Discovery & Dependency Injection**
- Automatic service discovery through MCP Mesh registry
- Type-safe dependency injection with `mesh.McpMeshAgent` parameters
- Graceful degradation when dependencies are unavailable

## Development Workflow

### Shared Virtual Environment Development

For simultaneous MCP Mesh framework and agent development:

```bash
# Use the project root .venv for both framework and agents
cd /path/to/mcp-mesh           # Project root
source .venv/bin/activate       # Shared virtual environment

# Framework is already installed in editable mode
# Agents can import directly from the shared environment

# Run agents from their directories
cd examples/complex/data_processor_agent
python main.py

cd examples/advanced  
python weather_agent.py
python llm_chat_agent.py
```

### Local Development

```bash
# Set up development environment
cd data_processor_agent
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run quality checks
black data_processor_agent/
mypy data_processor_agent/
pytest tests/

# Test the package structure
python test_structure.py

# Run the agent
python -m data_processor_agent
```

### Docker Development

```bash
# Build and run with Docker
./scripts/build.sh
./scripts/dev.sh dev

# Development with shell access
./scripts/dev.sh shell

# Full stack with docker-compose
./scripts/dev.sh up
```

## Integration with MCP Mesh

These examples demonstrate advanced MCP Mesh features:

### 1. **Real Dependency Injection**
```python
@app.tool()
@mesh.tool(
    capability="data_processing", 
    dependencies=["weather-service", "llm-service"]
)
def analyze_data_with_context(
    data: str,
    weather_service: mesh.McpMeshAgent = None,   # Auto-injected weather service
    llm_service: mesh.McpMeshAgent = None        # Auto-injected LLM service
) -> Dict[str, Any]:
    # Get weather context
    weather_data = weather_service() if weather_service else None
    
    # Use LLM for analysis
    analysis = llm_service({
        "text": data, 
        "task": "analyze",
        "context": f"Weather: {weather_data}"
    }) if llm_service else None
    
    return {"data": data, "weather": weather_data, "analysis": analysis}
```

### 2. **Enhanced Proxy Configuration (v0.3+)**
```python
@app.tool()
@mesh.tool(
    capability="heavy_computation",
    dependencies=["database-service"],
    # Enhanced proxy kwargs (NOT nested object!)
    timeout=300,                    # 5 minutes
    retry_count=3,                  # 3 retries
    streaming=True,                 # Enable streaming
    custom_headers={
        "X-Service-Type": "data-processor",
        "X-Processing-Level": "advanced"
    }
)
def process_large_dataset(data: str) -> Dict[str, Any]:
    # Automatic timeout, retry, and streaming configuration
    pass
```

### 3. **FastMCP Compatibility**
```python
# ✅ CORRECT: No **kwargs in function signatures
def parse_data_file(file_path: str, file_format: Optional[str] = None) -> Dict[str, Any]:
    pass

# ❌ WRONG: FastMCP doesn't support **kwargs
def parse_data_file(file_path: str, **options) -> Dict[str, Any]:
    pass
```

## Service Ecosystem

This example demonstrates a complete service ecosystem:

### Service Providers
- **Weather Service**: Real weather data with auto-location detection
- **LLM Service**: Text processing and data interpretation
- **Data Processor**: Complex multi-file agent consuming both services

### Capability Names
- `weather-service` → Provided by weather agent
- `llm-service` → Provided by LLM agent  
- `data_processing` → Provided by data processor agent (multiple tools)
- `statistical_analysis` → Provided by data processor agent
- `data_interpretation` → Provided by LLM agent

### Service Discovery
All agents automatically register with the MCP Mesh registry and dependencies are resolved via capability names and tags.

## Best Practices Demonstrated

### 1. **Code Organization**
- Single responsibility principle for each module
- Clear interfaces between components
- Separation of business logic from infrastructure

### 2. **Configuration Management**
- All configuration via environment variables
- Type-safe configuration with validation
- Hierarchical configuration with defaults

### 3. **Error Handling**
- Structured error responses for MCP tools
- Graceful degradation for partial failures
- Comprehensive logging for debugging

### 4. **Testing Strategy**
- Unit tests for individual components
- Integration tests for MCP tools
- Multi-agent testing with real dependencies

### 5. **Deployment Flexibility**
- Multiple execution methods
- Docker containerization with multi-stage builds
- Kubernetes-ready configuration
- Development and production configurations

## Deployment Options

### 1. **Local Development**
- Direct Python execution for rapid iteration
- Virtual environment with editable installation
- Environment variable configuration

### 2. **Docker Containerization**
- Multi-stage builds for optimization
- Non-root user for security
- Health checks and monitoring

### 3. **Kubernetes Deployment**
- Production-ready manifests
- ConfigMap and Secret integration
- Service discovery and load balancing

### 4. **Package Distribution**
- PyPI-compatible packages
- Command-line scripts installation
- Dependency management

## Next Steps

1. **Start the Multi-Agent Setup**: Follow the Quick Start guide above
2. **Test Service Integration**: Use the MCP tool invocation examples
3. **Review the Data Processor Agent**: Dive into the complete implementation
4. **Adapt for Your Use Case**: Use these patterns as a starting point for your own agents
5. **Contribute Examples**: Share your own complex agent patterns with the community

## Related Documentation

- [Simple Examples](../simple/README.md) - Basic MCP Mesh functionality  
- [Advanced Examples](../advanced/README.md) - Weather and LLM service agents
- [Mesh Decorators Guide](../../docs/mesh-decorators.md) - Complete decorator reference
- [Development Guide](../../docs/02-local-development.md) - Comprehensive best practices

## Support

For questions about complex agent development:
1. Review the development guide and example code
2. Check the main MCP Mesh documentation
3. Test the multi-agent setup to understand service dependencies
4. Open an issue with specific questions or problems
5. Contribute improvements and additional examples