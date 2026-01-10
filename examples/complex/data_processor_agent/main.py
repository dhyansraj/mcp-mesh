#!/usr/bin/env python3
"""
Data Processor Agent - Main Entry Point

A comprehensive multi-file MCP Mesh agent demonstrating:
- Structured Python package organization
- Multiple utility modules and tools
- External dependencies (pandas, numpy, scipy)
- Configuration management
- Proper error handling and logging
- Caching capabilities
"""

import json
import logging
from typing import Any, Dict, List, Optional

import mesh
from fastmcp import FastMCP

# Import our organized modules
try:
    # Relative imports for package execution
    from .config import Settings, get_settings
    from .tools import (DataExporter, DataParser, DataTransformer,
                        StatisticalAnalyzer)
    from .utils import (CacheManager, DataFormatter, DataValidator,
                        ValidationError, cache_key)
except ImportError:
    # Direct imports for standalone execution
    from config import Settings, get_settings
    from utils import (CacheManager, DataFormatter, DataValidator,
                       ValidationError, cache_key)

    from tools import (DataExporter, DataParser, DataTransformer,
                       StatisticalAnalyzer)

# Create FastMCP app instance for hybrid functionality
app = FastMCP("Data Processor Service")

# Initialize global components
settings = get_settings()
parser = DataParser()
transformer = DataTransformer()
analyzer = StatisticalAnalyzer()
exporter = DataExporter()
formatter = DataFormatter()
cache_manager = (
    CacheManager(
        cache_dir=settings.temp_dir + "/cache", ttl_seconds=settings.cache_ttl_seconds
    )
    if settings.cache_enabled
    else None
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@app.tool()
@mesh.tool(
    capability="data_processing",
    dependencies=["weather-service", "llm-service"],
    # Enhanced proxy configuration via kwargs (v0.3+)
    timeout=300,
    retry_count=3,
    streaming=True,
    custom_headers={
        "X-Service-Type": "data-processor",
        "X-Processing-Level": "advanced",
    },
)
def parse_data_file(
    file_path: str,
    file_format: Optional[str] = None,
    weather_service: mesh.McpMeshAgent = None,
    llm_service: mesh.McpMeshAgent = None,
) -> Dict[str, Any]:
    """
    Parse a data file from various formats into a structured format.

    Args:
        file_path: Path to the data file
        file_format: Override file format detection (csv, json, xlsx, parquet, tsv)
        **parse_options: Format-specific parsing options

    Returns:
        Dictionary containing parsed data information, validation results, and metadata
    """
    try:
        logger.info(f"Parsing data file: {file_path}")

        # Check cache if enabled
        if cache_manager:
            cache_key_str = cache_key("parse_file", file_path, file_format)
            cached_result = cache_manager.get(cache_key_str)
            if cached_result:
                logger.info("Returning cached parse result")
                return cached_result

        result = parser.parse_file(file_path)

        # Format results for display
        formatted_result = {
            "success": True,
            "data_summary": formatter.format_summary(result["dataframe"]),
            "validation_report": formatter.format_validation_report(
                result["validation"]
            ),
            "metadata": result["metadata"],
            "preview": formatter.to_display_table(result["dataframe"]),
        }

        # Cache result if enabled
        if cache_manager:
            cache_manager.set(
                cache_key_str,
                formatted_result,
                {"operation": "parse_file", "file_path": file_path},
            )

        return formatted_result

    except Exception as e:
        logger.error(f"Failed to parse file {file_path}: {str(e)}")
        return {"success": False, "error": str(e), "file_path": file_path}


@app.tool()
@mesh.tool(capability="data_processing")
def parse_data_string(data: str, format_type: str) -> Dict[str, Any]:
    """
    Parse data from a string in various formats.

    Args:
        data: Raw data as string
        format_type: Data format (csv, json, tsv)
        **parse_options: Format-specific parsing options

    Returns:
        Dictionary containing parsed data information and validation results
    """
    try:
        logger.info(f"Parsing data string of {len(data)} characters as {format_type}")

        result = parser.parse_string(data, format_type)

        return {
            "success": True,
            "data_summary": formatter.format_summary(result["dataframe"]),
            "validation_report": formatter.format_validation_report(
                result["validation"]
            ),
            "metadata": result["metadata"],
            "preview": formatter.to_display_table(result["dataframe"]),
        }

    except Exception as e:
        logger.error(f"Failed to parse string data: {str(e)}")
        return {"success": False, "error": str(e), "format_type": format_type}


@app.tool()
@mesh.tool(capability="data_processing")
def filter_data(data_source: str, conditions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Filter data based on specified conditions.

    Args:
        data_source: Identifier for previously parsed data (implementation specific)
        conditions: List of filter conditions with column, operator, and value
                   Operators: eq, ne, gt, gte, lt, lte, contains, startswith, endswith, in, notnull, isnull

    Returns:
        Dictionary containing filtered data and processing results
    """
    try:
        # Note: In a real implementation, you'd retrieve the DataFrame from a data store
        # For this example, we'll return the operation structure
        logger.info(f"Filtering data with {len(conditions)} conditions")

        return {
            "success": True,
            "message": "Filter operation structure validated",
            "conditions": conditions,
            "supported_operators": [
                "eq",
                "ne",
                "gt",
                "gte",
                "lt",
                "lte",
                "contains",
                "startswith",
                "endswith",
                "in",
                "notnull",
                "isnull",
            ],
            "note": "In a complete implementation, this would apply filters to actual data",
        }

    except Exception as e:
        logger.error(f"Failed to filter data: {str(e)}")
        return {"success": False, "error": str(e)}


@app.tool()
@mesh.tool(capability="data_processing")
def transform_data(data_source: str, operations: List[str]) -> Dict[str, Any]:
    """
    Apply data transformation operations.

    Args:
        data_source: Identifier for previously parsed data
        operations: List of operations to apply (drop_duplicates, drop_empty_rows,
                   drop_empty_columns, trim_strings, standardize_case, fill_numeric_nulls)
        **transform_options: Additional transformation parameters

    Returns:
        Dictionary containing transformation results
    """
    try:
        logger.info(f"Applying {len(operations)} transformation operations")

        return {
            "success": True,
            "message": "Transformation operations structure validated",
            "operations": operations,
            "supported_operations": [
                "drop_duplicates",
                "drop_empty_rows",
                "drop_empty_columns",
                "trim_strings",
                "standardize_case",
                "fill_numeric_nulls",
            ],
            "options": {},  # Transform options would be implemented in full version
            "note": "In a complete implementation, this would apply transformations to actual data",
        }

    except Exception as e:
        logger.error(f"Failed to transform data: {str(e)}")
        return {"success": False, "error": str(e)}


@app.tool()
@mesh.tool(
    capability="statistical_analysis",
    dependencies=["llm-service"],  # Might use LLM for advanced analysis interpretation
    tags=["analytics", "statistics"],
    version="1.0.0",
    # Enhanced proxy configuration
    timeout=180,
    retry_count=2,
)
def analyze_statistics(
    data_source: str, analysis_type: str, llm_service: mesh.McpMeshAgent = None
) -> Dict[str, Any]:
    """
    Perform statistical analysis on data.

    Args:
        data_source: Identifier for previously parsed data
        analysis_type: Type of analysis (descriptive, correlation, distribution, outliers)
        **analysis_options: Analysis-specific options

    Returns:
        Dictionary containing statistical analysis results
    """
    try:
        logger.info(f"Performing {analysis_type} statistical analysis")

        return {
            "success": True,
            "message": f"Statistical analysis '{analysis_type}' structure validated",
            "analysis_type": analysis_type,
            "supported_types": [
                "descriptive",
                "correlation",
                "distribution",
                "outliers",
            ],
            "options": {},  # Analysis options would be implemented in full version
            "note": "In a complete implementation, this would analyze actual data",
        }

    except Exception as e:
        logger.error(f"Failed to analyze statistics: {str(e)}")
        return {"success": False, "error": str(e)}


@app.tool()
@mesh.tool(capability="data_processing")
def export_data(
    data_source: str, format_type: str, include_metadata: bool = True
) -> Dict[str, Any]:
    """
    Export processed data to various formats.

    Args:
        data_source: Identifier for previously processed data
        format_type: Export format (csv, json, xlsx, parquet)
        include_metadata: Whether to include processing metadata
        **export_options: Format-specific export options

    Returns:
        Dictionary containing export results and file information
    """
    try:
        logger.info(f"Exporting data to {format_type} format")

        # Get format-specific options
        format_options = exporter.get_export_options(format_type)

        return {
            "success": True,
            "message": f"Export to {format_type} format validated",
            "format": format_type,
            "include_metadata": include_metadata,
            "export_options": {},  # Export options would be implemented in full version
            "note": "In a complete implementation, this would export actual data",
        }

    except Exception as e:
        logger.error(f"Failed to export data: {str(e)}")
        return {"success": False, "error": str(e)}


@app.tool()
@mesh.tool(capability="data_processing")
def get_file_info(file_path: str) -> Dict[str, Any]:
    """
    Get information about a data file without parsing it.

    Args:
        file_path: Path to the file to analyze

    Returns:
        Dictionary containing file information and capabilities
    """
    try:
        logger.info(f"Getting file info for: {file_path}")

        info = parser.get_file_info(file_path)

        return {
            "success": True,
            "file_info": info,
            "agent_capabilities": {
                "supported_formats": parser.supported_formats,
                "max_file_size_mb": settings.processing.max_file_size_mb,
                "max_rows": settings.processing.max_rows,
                "cache_enabled": settings.cache_enabled,
            },
        }

    except Exception as e:
        logger.error(f"Failed to get file info: {str(e)}")
        return {"success": False, "error": str(e), "file_path": file_path}


@app.tool()
@mesh.tool(capability="data_processing")
def get_agent_status() -> Dict[str, Any]:
    """
    Get current agent status and configuration.

    Returns:
        Dictionary containing agent status, configuration, and capabilities
    """
    try:
        status = {
            "agent_name": settings.agent_name,
            "version": settings.version,
            "status": "healthy",
            "configuration": {
                "processing_limits": {
                    "max_file_size_mb": settings.processing.max_file_size_mb,
                    "max_rows": settings.processing.max_rows,
                    "max_columns": settings.processing.max_columns,
                    "timeout_seconds": settings.processing.timeout_seconds,
                },
                "export_config": {
                    "supported_formats": settings.export.supported_formats,
                    "default_format": settings.export.default_format,
                    "compression": settings.export.compression,
                },
                "cache_enabled": settings.cache_enabled,
                "metrics_enabled": settings.metrics_enabled,
            },
            "capabilities": [
                "data_parsing",
                "data_transformation",
                "statistical_analysis",
                "data_export",
                "file_validation",
                "multi_format_support",
            ],
            "dependencies": settings.dependencies,
        }

        # Add cache statistics if enabled
        if cache_manager:
            status["cache_stats"] = cache_manager.get_stats()

        return status

    except Exception as e:
        logger.error(f"Failed to get agent status: {str(e)}")
        return {"status": "error", "error": str(e)}


@app.tool()
@mesh.tool(capability="data_processing")
def clear_cache() -> Dict[str, Any]:
    """
    Clear the agent's data processing cache.

    Returns:
        Dictionary containing cache clearing results
    """
    try:
        if not cache_manager:
            return {"success": False, "message": "Cache is not enabled"}

        stats_before = cache_manager.get_stats()
        cache_manager.clear()

        logger.info("Cache cleared successfully")

        return {
            "success": True,
            "message": "Cache cleared successfully",
            "stats_before": stats_before,
            "entries_cleared": stats_before.get("total_entries", 0),
        }

    except Exception as e:
        logger.error(f"Failed to clear cache: {str(e)}")
        return {"success": False, "error": str(e)}


# Agent class definition - MCP Mesh will auto-discover and run the FastMCP app
@mesh.agent(
    name=settings.agent_name,
    http_port=settings.http_port,
    auto_run=True,  # KEY: This makes MCP Mesh automatically start the FastMCP server
)
class DataProcessorAgent:
    """
    Advanced Data Processor Agent

    A comprehensive MCP Mesh agent for data processing operations.

    MCP Mesh will automatically:
    1. Discover the 'app' FastMCP instance above
    2. Apply dependency injection to @mesh.tool decorated functions
    3. Start the FastMCP HTTP server on the configured port
    4. Register all capabilities with the mesh registry

    No manual server startup needed!
    """

    def __init__(self):
        logger.info(f"Initializing Data Processor Agent v{settings.version}")
        logger.info(f"Cache enabled: {settings.cache_enabled}")
        logger.info(f"Supported formats: {parser.supported_formats}")

        # Cleanup expired cache entries on startup
        if cache_manager:
            cache_manager.cleanup_expired()


# No main method needed!
# MCP Mesh processor automatically handles:
# - FastMCP server discovery and startup
# - Dependency injection between functions
# - HTTP server configuration
# - Service registration with mesh registry
