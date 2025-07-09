"""
Data Processor Agent - Complex Multi-File MCP Mesh Agent Example

This agent demonstrates how to structure a complex MCP Mesh agent with:
- Multiple modules and utilities
- Proper Python packaging
- External dependencies
- Configuration management
- Modular tool organization

The agent provides data processing capabilities including:
- CSV/JSON data parsing and validation
- Data transformation and filtering
- Statistical analysis
- Export to multiple formats
"""

__version__ = "1.0.0"
__author__ = "MCP Mesh Team"

from .main import DataProcessorAgent

__all__ = ["DataProcessorAgent"]