# Data Processor Agent

A comprehensive multi-file MCP Mesh agent demonstrating advanced data processing capabilities with proper Python package structure.

## Features

### Core Capabilities
- **Multi-format data parsing**: CSV, JSON, Excel, Parquet, TSV
- **Data validation**: Quality checks, type validation, schema validation
- **Statistical analysis**: Descriptive statistics, correlation analysis, outlier detection
- **Data transformation**: Filtering, sorting, aggregation, cleaning operations
- **Export functionality**: Multiple output formats with metadata
- **Caching system**: Performance optimization for repeated operations

### Advanced Features
- **Dependency injection**: Integrates with weather-service and llm-service
- **Enhanced proxy support**: Timeouts, retries, streaming
- **Session management**: Redis-backed stateful operations
- **Configuration management**: Environment-based settings
- **Comprehensive logging**: Structured logging with multiple levels
- **Error handling**: Graceful error recovery and reporting

## Package Structure

```
data_processor_agent/
├── __init__.py              # Package initialization and exports
├── __main__.py              # Entry point for python -m execution
├── main.py                  # Main agent implementation with MCP tools
├── pyproject.toml           # Python packaging configuration
├── README.md                # This documentation
│
├── config/                  # Configuration management
│   ├── __init__.py
│   └── settings.py          # Settings classes and environment handling
│
├── tools/                   # Core data processing tools
│   ├── __init__.py
│   ├── data_parsing.py      # Multi-format data parsing
│   ├── data_transformation.py # Data manipulation operations
│   ├── statistical_analysis.py # Statistical analysis tools
│   └── export_tools.py      # Data export functionality
│
└── utils/                   # Utility modules
    ├── __init__.py
    ├── validation.py        # Data validation utilities
    ├── formatting.py        # Display and formatting helpers
    └── caching.py           # Caching system implementation
```

## Installation & Usage

### Local Development Installation

```bash
# Install in editable mode with development dependencies
pip install -e ".[dev]"

# Install with all optional dependencies
pip install -e ".[all]"
```

### Running the Agent

#### Method 1: Python Module Execution (Recommended)
```bash
python -m data_processor_agent
```

#### Method 2: Direct Script Execution
```bash
python data_processor_agent/main.py
```

#### Method 3: Using the installed command
```bash
# After pip installation
data-processor-agent
```

### Configuration

The agent can be configured via environment variables:

```bash
export AGENT_NAME="my-data-processor"
export HTTP_PORT="9090"
export LOG_LEVEL="INFO"
export CACHE_ENABLED="true"
export METRICS_ENABLED="true"
```

## MCP Tool Interface

### Data Parsing Tools

#### `parse_data_file`
Parse data files in various formats.

```python
# Example usage
result = await agent.parse_data_file(
    file_path="/path/to/data.csv",
    encoding="utf-8",
    delimiter=","
)
```

#### `parse_data_string` 
Parse data from string input.

```python
# Example usage
result = await agent.parse_data_string(
    data="col1,col2\n1,2\n3,4",
    format_type="csv"
)
```

### Data Processing Tools

#### `filter_data`
Apply filtering conditions to data.

```python
# Example filtering
result = await agent.filter_data(
    data_source="parsed_data_id",
    conditions=[
        {"column": "age", "operator": "gt", "value": 25},
        {"column": "status", "operator": "eq", "value": "active"}
    ]
)
```

#### `transform_data`
Apply data transformation operations.

```python
# Example transformation
result = await agent.transform_data(
    data_source="parsed_data_id",
    operations=["drop_duplicates", "trim_strings", "fill_numeric_nulls"]
)
```

### Analysis Tools

#### `analyze_statistics`
Perform statistical analysis.

```python
# Example analysis
result = await agent.analyze_statistics(
    data_source="parsed_data_id",
    analysis_type="descriptive",
    columns=["age", "income", "score"]
)
```

### Export Tools

#### `export_data`
Export processed data to various formats.

```python
# Example export
result = await agent.export_data(
    data_source="processed_data_id",
    format_type="xlsx",
    include_metadata=True,
    sheet_name="Results"
)
```

### Utility Tools

#### `get_file_info`
Get file information without parsing.

```python
# Example file info
result = await agent.get_file_info(file_path="/path/to/data.csv")
```

#### `get_agent_status`
Get current agent status and configuration.

```python
# Example status check
result = await agent.get_agent_status()
```

## Development Workflow

### 1. Local Development Setup

```bash
# Clone the repository
git clone <repository-url>
cd mcp-mesh/examples/complex/data_processor_agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"
```

### 2. Code Quality Tools

```bash
# Format code
black data_processor_agent/
isort data_processor_agent/

# Lint code
flake8 data_processor_agent/

# Type checking
mypy data_processor_agent/
```

### 3. Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=data_processor_agent --cov-report=html
```

### 4. Building and Distribution

```bash
# Build package
python -m build

# Install built package
pip install dist/mcp_mesh_data_processor_agent-1.0.0-py3-none-any.whl
```

## Docker Deployment

See the Docker example in the parent directory for containerized deployment patterns.

## Dependencies

### Core Dependencies
- **mcp-mesh**: MCP Mesh framework
- **fastmcp**: FastMCP integration
- **pandas**: Data manipulation and analysis
- **numpy**: Numerical computing
- **scipy**: Scientific computing

### Optional Dependencies
- **Performance**: numba, polars, pyarrow
- **Machine Learning**: scikit-learn, matplotlib, seaborn
- **Development**: pytest, black, mypy, sphinx

## Architecture Decisions

### 1. Modular Structure
- **Separation of Concerns**: Each module has a specific responsibility
- **Testability**: Individual components can be tested in isolation
- **Maintainability**: Changes to one component don't affect others
- **Reusability**: Utility modules can be used across different tools

### 2. Configuration Management
- **Environment-based**: Configuration via environment variables
- **Type Safety**: Dataclasses with type hints for configuration
- **Defaults**: Sensible defaults for all configuration options
- **Validation**: Configuration validation on startup

### 3. Error Handling
- **Graceful Degradation**: Partial failures don't crash the entire agent
- **Detailed Errors**: Comprehensive error messages with context
- **Logging**: Structured logging for debugging and monitoring
- **Recovery**: Automatic recovery where possible

### 4. Performance Optimization
- **Caching**: File-based caching for expensive operations
- **Streaming**: Support for large datasets via streaming
- **Memory Management**: Efficient memory usage patterns
- **Lazy Loading**: Load resources only when needed

## Best Practices Demonstrated

1. **Python Packaging**: Proper `pyproject.toml` with all metadata
2. **Module Structure**: Clear separation of concerns and imports
3. **Type Hints**: Comprehensive type annotations
4. **Documentation**: Inline docs and comprehensive README
5. **Configuration**: Environment-based configuration management
6. **Error Handling**: Comprehensive error handling and logging
7. **Testing**: Structure for unit and integration tests
8. **Code Quality**: Linting, formatting, and type checking setup

## Extending the Agent

### Adding New Tools

1. Create tool function in appropriate module under `tools/`
2. Add MCP decorators (`@app.tool()` and `@mesh.tool()`)
3. Update `__init__.py` exports
4. Add documentation and type hints
5. Add tests for the new functionality

### Adding New Utilities

1. Create utility module under `utils/`
2. Add comprehensive type hints
3. Update `utils/__init__.py` exports
4. Add unit tests
5. Update documentation

### Configuration Changes

1. Update `config/settings.py` with new settings
2. Add environment variable support
3. Update default values
4. Document new configuration options

## License

MIT License - see the main MCP Mesh project for full license details.