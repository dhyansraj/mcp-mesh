# Correct MCP Mesh Decorator Parameters

Based on `/docs/mesh-decorators.md`, here are the **actual** parameters available for MCP Mesh decorators:

## 🔧 **@mesh.tool Parameters**

### **Core Parameters**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `capability` | `str \| None` | `None` | Capability name others can depend on |
| `tags` | `list[str] \| None` | `[]` | Tags for smart service discovery |
| `version` | `str` | `"1.0.0"` | Semantic version for this capability |
| `dependencies` | `list[str \| dict] \| None` | `None` | Required capabilities |
| `description` | `str \| None` | Function docstring | Human-readable description |

### **Enhanced Proxy Configuration (v0.3+)**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeout` | `int` | `30` | Request timeout in seconds |
| `retry_count` | `int` | `1` | Number of retry attempts |
| `custom_headers` | `dict` | `{}` | Custom HTTP headers |
| `streaming` | `bool` | `False` | Enable streaming capabilities |
| `auth_required` | `bool` | `False` | Require authentication |
| `session_required` | `bool` | `False` | Enable session affinity |
| `stateful` | `bool` | `False` | Mark as stateful capability |
| `auto_session_management` | `bool` | `False` | Enable automatic session handling |

## ✅ **Correct Usage Examples**

### **Basic Tool with Dependencies**
```python
@app.tool()
@mesh.tool(
    capability="data_processing",
    dependencies=["weather-service", "llm-service"],
    tags=["data", "processing"],
    version="1.0.0",
    description="Process data with external services"
)
def process_data(): pass
```

### **Enhanced Proxy Configuration**
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
def compute_heavy_data(): pass
```

### **Complex Dependencies with Tags**
```python
@app.tool()
@mesh.tool(
    capability="advanced_analysis",
    dependencies=[
        "simple_service",               # Simple string dependency
        {
            "capability": "info",
            "tags": ["system", "detailed"],  # Tag-based selection
            "version": ">=2.0.0"            # Version constraint
        }
    ],
    tags=["analytics", "advanced"],
    version="2.1.0",
    timeout=180,
    retry_count=2
)
def analyze_with_complex_deps(): pass
```

### **Session-Aware Operations**
```python
@app.tool()
@mesh.tool(
    capability="user_session",
    dependencies=["auth-service"],
    session_required=True,           # Enable session affinity
    stateful=True,                   # Mark as stateful
    auto_session_management=True,    # Automatic session handling
    timeout=60,
    custom_headers={
        "X-Session-Enabled": "true"
    }
)
def manage_user_session(): pass
```

## 🚫 **What I Used Incorrectly**

### **❌ Wrong: nested `enhanced_proxy` object**
```python
# This is NOT supported
@mesh.tool(
    capability="service",
    enhanced_proxy={                 # ❌ Wrong!
        "timeout": 300,
        "retry": {"attempts": 3},
        "stream": True
    }
)
```

### **✅ Correct: kwargs directly**
```python
# This is the correct way
@mesh.tool(
    capability="service",
    timeout=300,                     # ✅ Direct kwargs
    retry_count=3,                   # ✅ Not nested
    streaming=True                   # ✅ Boolean, not "stream"
)
```

## 🔄 **Dependency Types**

### **Simple String Dependencies**
```python
dependencies=["service1", "service2"]
```

### **Complex Object Dependencies**
```python
dependencies=[
    "simple_service",
    {
        "capability": "complex_service",
        "tags": ["tag1", "tag2"],
        "version": ">=1.5.0",
        "namespace": "production"
    }
]
```

## 🎯 **@mesh.agent Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | **Required** | Agent name (mandatory!) |
| `version` | `str` | `"1.0.0"` | Agent version |
| `description` | `str \| None` | `None` | Agent description |
| `http_host` | `str \| None` | `None` | HTTP server host |
| `http_port` | `int` | `0` | HTTP server port |
| `enable_http` | `bool` | `True` | Enable HTTP endpoints |
| `namespace` | `str` | `"default"` | Agent namespace |
| `health_interval` | `int` | `30` | Health check interval |
| `auto_run` | `bool` | `True` | Auto-start and keep alive |
| `auto_run_interval` | `int` | `10` | Keep-alive heartbeat |

## 📋 **Corrected Multi-File Agent Example**

```python
import mesh
from fastmcp import FastMCP

# Import multi-file structure
from .config import get_settings
from .tools import DataParser
from .utils import DataFormatter

# FastMCP instance
app = FastMCP("Data Processor Service")

@app.tool()
@mesh.tool(
    capability="data_parsing",
    dependencies=["llm-service"],
    tags=["parsing", "data", "csv", "json"],
    version="1.0.0",
    description="Parse various data formats",
    # Enhanced proxy configuration
    timeout=120,
    retry_count=2,
    custom_headers={
        "X-Service-Type": "data-parser"
    }
)
def parse_data_file(file_path: str) -> dict:
    # Use sophisticated multi-file parser
    parser = DataParser()
    return parser.parse_file(file_path)

@app.tool()
@mesh.tool(
    capability="data_export",
    tags=["export", "formats"],
    version="1.0.0",
    timeout=60,
    retry_count=1
)
def export_data(data: dict, format_type: str = "csv") -> dict:
    # Use multi-file export tools
    from .tools import DataExporter
    exporter = DataExporter()
    return exporter.export_data(data, format_type)

# Agent with auto-run
@mesh.agent(
    name="data-processor",
    version="1.0.0",
    description="Multi-file data processor",
    http_port=9090,
    auto_run=True
)
class DataProcessorAgent:
    pass
```

## 🎯 **Key Takeaways**

1. **No nested objects**: Enhanced proxy config uses direct kwargs, not nested dicts
2. **Correct parameter names**: `retry_count` not `retry`, `streaming` not `stream`
3. **Tags are powerful**: Use multiple tags for smart service selection
4. **Version everything**: Both tools and dependencies support semantic versioning
5. **Auto-run simplifies deployment**: No manual server management needed

The corrected examples now match the actual MCP Mesh decorator API from the documentation.