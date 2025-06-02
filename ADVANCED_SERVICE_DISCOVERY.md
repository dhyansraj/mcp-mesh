# Advanced Service Discovery with Decorator Pattern Integration

## Overview

This implementation provides advanced service discovery capabilities with decorator pattern integration for MCP Mesh. Agents can self-register with enhanced capability metadata using the `@mesh_agent` decorator, and other agents can discover them using sophisticated matching algorithms and MCP tools.

## Key Features

### 1. **Agent Self-Registration with @mesh_agent Decorator**

- Agents automatically register with the registry using decorator metadata
- Rich capability metadata including performance profiles and resource requirements
- Hierarchical capability inheritance support
- Automatic health monitoring with configurable intervals

### 2. **Semantic Capability Matching**

- Advanced matching algorithms with similarity scoring
- Support for exact, partial, semantic, and fuzzy matching strategies
- Capability hierarchy with inheritance relationships
- Performance-based compatibility assessment

### 3. **Complex Query Language**

- Boolean operators: AND, OR, NOT
- Comparison operators: EQUALS, CONTAINS, MATCHES, GREATER_THAN, LESS_THAN
- Field-specific queries on capabilities, tags, performance metrics
- Weighted query components for relevance scoring

### 4. **Compatibility Scoring Engine**

- Multi-dimensional scoring: capability, performance, security, availability
- Detailed breakdown with recommendations
- Configurable compatibility thresholds
- Missing capability identification

### 5. **Advanced Discovery MCP Tools**

- `query_agents`: Complex capability-based agent search
- `get_best_agent`: Intelligent optimal agent selection
- `check_compatibility`: Detailed compatibility assessment
- `list_agent_capabilities`: Capability inventory management
- `get_capability_hierarchy`: Inheritance relationship mapping

## Architecture

### Dual Package Structure

Following the dual-package architecture:

**mcp-mesh-types** (Interface Package):

- Service discovery interfaces and types
- Enhanced @mesh_agent decorator (no-op)
- Protocol definitions for type safety
- Examples import only from this package

**mcp-mesh** (Implementation Package):

- Capability matching and scoring engine
- Service discovery implementation
- Enhanced decorator with registration logic
- Registry client with metadata support

## Implementation Components

### 1. Service Discovery Interfaces (`mcp-mesh-types/service_discovery.py`)

```python
# Core types for service discovery
class CapabilityMetadata(BaseModel):
    name: str
    version: str = "1.0.0"
    description: Optional[str] = None
    parent_capabilities: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    performance_metrics: Dict[str, float] = Field(default_factory=dict)
    security_level: str = "standard"
    resource_requirements: Dict[str, Any] = Field(default_factory=dict)

class CapabilityQuery(BaseModel):
    operator: QueryOperator
    field: Optional[str] = None
    value: Any = None
    subqueries: List["CapabilityQuery"] = Field(default_factory=list)
    matching_strategy: MatchingStrategy = MatchingStrategy.SEMANTIC
    weight: float = Field(1.0, ge=0.0, le=1.0)

class Requirements(BaseModel):
    required_capabilities: List[str]
    preferred_capabilities: List[str] = Field(default_factory=list)
    performance_requirements: Dict[str, float] = Field(default_factory=dict)
    security_requirements: Dict[str, str] = Field(default_factory=dict)
    max_latency_ms: Optional[float] = None
    min_availability: Optional[float] = None
    compatibility_threshold: float = 0.7
```

### 2. Capability Matching Engine (`mcp-mesh/shared/capability_matching.py`)

```python
class CapabilityMatchingEngine:
    def score_capability_match(self, required: CapabilityMetadata, provided: CapabilityMetadata) -> float:
        """Score match between required and provided capabilities."""

    def build_capability_hierarchy(self, capabilities: List[CapabilityMetadata]) -> CapabilityHierarchy:
        """Build hierarchical structure from capabilities."""

    def evaluate_query(self, query: CapabilityQuery, agent_metadata: MeshAgentMetadata) -> bool:
        """Evaluate complex query against agent metadata."""

    def compute_compatibility_score(self, agent_info: AgentInfo, requirements: Requirements) -> CompatibilityScore:
        """Compute comprehensive compatibility score."""
```

### 3. Enhanced @mesh_agent Decorator

**Interface Version** (`mcp-mesh-types/decorators.py`):

```python
@mesh_agent(
    capabilities=["file_processing", "text_analysis"],
    version="2.1.0",
    description="Advanced file processing agent",
    tags=["files", "text", "analysis"],
    performance_profile={"throughput_files_per_sec": 50.0},
    resource_requirements={"memory_mb": 512},
    security_context="file_operations",
    health_interval=30,
)
```

**Implementation Version** (`mcp-mesh/decorators/mesh_agent.py`):

- Automatic capability registration with service discovery
- Enhanced metadata collection and processing
- Background health monitoring with capability updates
- Graceful fallback mode for registry unavailability

### 4. MCP Discovery Tools (`mcp-mesh/tools/discovery_tools.py`)

```python
@app.tool()
async def query_agents(query: str, operator: str = "contains", field: str = "capabilities") -> List[Dict]:
    """Query agents based on capability requirements."""

@app.tool()
async def get_best_agent(required_capabilities: List[str], **kwargs) -> Optional[Dict]:
    """Get the best matching agent for given requirements."""

@app.tool()
async def check_compatibility(agent_id: str, required_capabilities: List[str]) -> Dict:
    """Check compatibility between agent and requirements."""

@app.tool()
async def list_agent_capabilities(agent_id: Optional[str] = None) -> Dict:
    """List capabilities for agents."""

@app.tool()
async def get_capability_hierarchy() -> Dict:
    """Get capability hierarchy with inheritance relationships."""
```

## Usage Examples

### 1. Agent Registration with Enhanced Metadata

```python
from mcp_mesh_types import mesh_agent

class FileProcessingAgent:
    @mesh_agent(
        capabilities=["file_processing", "text_analysis", "data_extraction"],
        version="2.1.0",
        description="Advanced file processing agent with text analysis",
        tags=["files", "text", "analysis", "extraction"],
        performance_profile={
            "throughput_files_per_sec": 50.0,
            "max_file_size_mb": 100.0,
            "avg_processing_time_ms": 250.0,
        },
        resource_requirements={
            "memory_mb": 512,
            "cpu_cores": 2,
            "disk_space_mb": 1024,
        },
        security_context="file_operations",
        endpoint="http://localhost:8001/file-agent",
        health_interval=30,
    )
    async def process_file(self, file_path: str, operation: str = "analyze") -> Dict:
        """Process a file with specified operation."""
        # Agent automatically registers capabilities when decorated
        return {"status": "success", "file_path": file_path}
```

### 2. Simple Capability Search

```python
# Find agents with specific capability
results = await query_agents(
    query="file_processing",
    operator="contains",
    field="capabilities"
)

for agent in results:
    print(f"Found: {agent['agent_name']} (score: {agent['compatibility_score']['overall']:.2f})")
```

### 3. Best Agent Selection

```python
# Find best agent for requirements
best_agent = await get_best_agent(
    required_capabilities=["text_analysis", "sentiment_analysis"],
    performance_requirements={"throughput_files_per_sec": 30.0},
    max_latency_ms=500.0,
    compatibility_threshold=0.8
)

if best_agent:
    print(f"Selected: {best_agent['agent_name']} at {best_agent['endpoint']}")
```

### 4. Complex Query Example

```python
from mcp_mesh_types import CapabilityQuery, QueryOperator, MatchingStrategy

# Complex query: High-performance agents with file OR database capabilities
file_query = CapabilityQuery(
    operator=QueryOperator.CONTAINS,
    field="capabilities",
    value="file_processing",
    weight=1.0
)

db_query = CapabilityQuery(
    operator=QueryOperator.CONTAINS,
    field="capabilities",
    value="database_operations",
    weight=1.0
)

performance_query = CapabilityQuery(
    operator=QueryOperator.GREATER_THAN,
    field="throughput_files_per_sec",
    value=30.0,
    weight=0.5
)

complex_query = CapabilityQuery(
    operator=QueryOperator.AND,
    subqueries=[
        CapabilityQuery(operator=QueryOperator.OR, subqueries=[file_query, db_query]),
        performance_query
    ],
    matching_strategy=MatchingStrategy.HIERARCHICAL
)

results = await query_agents_complex(complex_query)
```

### 5. Compatibility Assessment

```python
# Detailed compatibility check
compatibility = await check_compatibility(
    agent_id="file-processor-001",
    required_capabilities=["file_processing", "text_analysis"],
    performance_requirements={"avg_processing_time_ms": 300.0},
    min_availability=0.95
)

print(f"Overall Score: {compatibility['overall_score']:.2f}")
print(f"Compatible: {compatibility['is_compatible']}")
print(f"Missing: {compatibility['missing_capabilities']}")
print(f"Recommendations: {compatibility['recommendations']}")
```

## Key Benefits

### 1. **Zero-Boilerplate Integration**

- Agents self-register with single decorator
- No manual registry API calls required
- Automatic capability metadata extraction

### 2. **Intelligent Discovery**

- Semantic matching beyond exact string comparison
- Performance-based agent selection
- Multi-criteria compatibility scoring

### 3. **Flexible Query Language**

- Support for complex boolean queries
- Field-specific search capabilities
- Weighted relevance scoring

### 4. **MCP SDK Compatibility**

- All discovery tools available as MCP tools
- Maintains full MCP protocol compliance
- Seamless integration with existing MCP infrastructure

### 5. **Hierarchical Capabilities**

- Capability inheritance and relationships
- Support for capability evolution and versioning
- Semantic understanding of capability relationships

## Developer Rules Compliance

✅ **Rule 1**: Use MCP SDK as-is - All tools use `@app.tool()` for MCP protocol compliance

✅ **Rule 2**: Complement MCP SDK - Interfaces in mcp-mesh-types, implementations in mcp-mesh

✅ **Rule 3**: Examples import only from mcp-mesh-types - All examples demonstrate clean interface usage

✅ **Rule 4**: Maintain MCP SDK compatibility - Full protocol compliance maintained throughout

## Examples Provided

1. **`advanced_service_discovery_example.py`** - Comprehensive demonstration of all features
2. **`dual_package_discovery_demo.py`** - Shows dual-package architecture compliance
3. **`mcp_discovery_tools_example.py`** - Interactive demonstration of MCP tools

## Next Steps

This implementation provides the foundation for advanced service discovery. Future enhancements could include:

1. **Machine Learning-Based Matching** - Use ML models for semantic capability understanding
2. **Performance Prediction** - Predictive models for agent performance under different loads
3. **Auto-Scaling Integration** - Dynamic agent provisioning based on capability demands
4. **Geographic Distribution** - Location-aware agent discovery and routing
5. **Capability Composition** - Automatic workflow generation from capability combinations

## Testing

Run the examples to see the advanced service discovery in action:

```bash
# Run the comprehensive demo
python examples/advanced_service_discovery_example.py

# Run the dual-package demo
python examples/dual_package_discovery_demo.py

# Run the MCP tools demo
python examples/mcp_discovery_tools_example.py
```

Each example demonstrates different aspects of the advanced service discovery system while maintaining strict compliance with the dual-package architecture and MCP SDK integration requirements.
