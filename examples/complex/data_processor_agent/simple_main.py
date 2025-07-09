#!/usr/bin/env python3
"""
Simplified Data Processor Agent - Pure MCP Mesh Auto-Run Pattern

This demonstrates the same multi-file agent but following the simple auto-run pattern
from examples/simple. This is the recommended approach for MCP Mesh agents.

Key points:
1. FastMCP instance with dual decorators
2. @mesh.agent with auto_run=True
3. NO manual server startup - MCP Mesh handles everything
4. Multi-file structure with utilities and tools
"""

import logging
from typing import Any, Dict, List, Optional

import mesh
from fastmcp import FastMCP

# Import our organized modules (multi-file structure)
try:
    from .config import get_settings
    from .tools import DataParser, DataTransformer, StatisticalAnalyzer, DataExporter
    from .utils import DataFormatter, CacheManager, cache_key
except ImportError:
    from config import get_settings
    from tools import DataParser, DataTransformer, StatisticalAnalyzer, DataExporter
    from utils import DataFormatter, CacheManager, cache_key

# Initialize components
settings = get_settings()
parser = DataParser()
transformer = DataTransformer()
analyzer = StatisticalAnalyzer()
exporter = DataExporter()
formatter = DataFormatter()
cache_manager = CacheManager() if settings.cache_enabled else None

# Configure logging
logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)

# Single FastMCP server instance - MCP Mesh will auto-discover this
app = FastMCP("Data Processor Service")


# ===== MCP TOOLS WITH MULTI-FILE STRUCTURE =====

@app.tool()
@mesh.tool(
    capability="data_parsing",
    dependencies=["llm-service"],  # Optional LLM for data interpretation
    tags=["parsing", "data"],
    version="1.0.0",
    # Enhanced proxy configuration (v0.3+)
    timeout=120,
    retry_count=2
)
def parse_file(file_path: str, format_hint: Optional[str] = None) -> Dict[str, Any]:
    """Parse a data file using the multi-file parser component."""
    try:
        # Use our sophisticated parser from tools module
        result = parser.parse_file(file_path)
        
        # Use our formatter from utils module  
        return {
            "success": True,
            "data_summary": formatter.format_summary(result["dataframe"]),
            "validation_report": formatter.format_validation_report(result["validation"]),
            "metadata": result["metadata"]
        }
    except Exception as e:
        logger.error(f"Parse error: {e}")
        return {"success": False, "error": str(e)}


@app.tool()
@mesh.tool(
    capability="data_analysis",
    dependencies=["weather-service"],  # Example dependency
    tags=["analytics", "statistics"]
)
def analyze_statistics(data_source: str, analysis_type: str = "descriptive") -> Dict[str, Any]:
    """Perform statistical analysis using the multi-file analyzer component."""
    try:
        # This would use our StatisticalAnalyzer from tools module
        # For demo, return structure validation
        return {
            "success": True,
            "analysis_type": analysis_type,
            "message": "Statistical analysis structure validated",
            "supported_types": ["descriptive", "correlation", "outliers"],
            "component": "StatisticalAnalyzer from tools.statistical_analysis"
        }
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        return {"success": False, "error": str(e)}


@app.tool()
@mesh.tool(capability="data_export", tags=["export", "formats"])
def export_data(data_source: str, format_type: str = "csv") -> Dict[str, Any]:
    """Export data using the multi-file export component."""
    try:
        # This would use our DataExporter from tools module
        export_options = exporter.get_export_options(format_type)
        
        return {
            "success": True,
            "export_format": format_type,
            "options": export_options,
            "component": "DataExporter from tools.export_tools"
        }
    except Exception as e:
        logger.error(f"Export error: {e}")
        return {"success": False, "error": str(e)}


@app.tool()
@mesh.tool(capability="agent_status")
def get_status() -> Dict[str, Any]:
    """Get agent status showing multi-file architecture."""
    return {
        "agent_name": settings.agent_name,
        "version": settings.version,
        "architecture": "multi-file",
        "modules": {
            "config": "Environment-based configuration management",
            "tools": "DataParser, DataTransformer, StatisticalAnalyzer, DataExporter", 
            "utils": "DataValidator, DataFormatter, CacheManager"
        },
        "cache_enabled": settings.cache_enabled,
        "supported_formats": parser.supported_formats,
        "status": "healthy"
    }


# ===== AGENT CONFIGURATION - AUTO-RUN PATTERN =====
@mesh.agent(
    name=settings.agent_name,
    version=settings.version,
    description="Multi-file data processor with MCP Mesh auto-run",
    http_port=settings.http_port,
    auto_run=True  # KEY: MCP Mesh automatically handles server startup
)
class DataProcessorAgent:
    """
    Multi-file Data Processor Agent with MCP Mesh auto-run.
    
    Demonstrates:
    - Multi-file Python package structure
    - Sophisticated utilities and tools organization
    - Configuration management
    - MCP Mesh auto-discovery and auto-run
    
    MCP Mesh will automatically:
    1. Discover the 'app' FastMCP instance above
    2. Apply dependency injection to @mesh.tool functions
    3. Start HTTP server on configured port
    4. Register capabilities with mesh registry
    """
    pass


# No main method needed!
# MCP Mesh handles everything automatically when auto_run=True
# Just run: python simple_main.py