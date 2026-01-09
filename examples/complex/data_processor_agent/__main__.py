#!/usr/bin/env python3
"""
Entry point for running the Data Processor Agent as a Python module.

This allows execution with: python -m data_processor_agent

This is the recommended way to run complex multi-file MCP Mesh agents
as it properly handles module imports and dependencies.
"""

import logging
import sys
from pathlib import Path

# Add the current directory to Python path for proper imports
sys.path.insert(0, str(Path(__file__).parent))

from .main import DataProcessorAgent, logger, settings


def main():
    """Main entry point for the data processor agent."""
    try:
        print(f"🚀 Starting Data Processor Agent v{settings.version}")
        print(f"📊 Agent: {settings.agent_name}")
        print(f"🌐 HTTP Port: {settings.http_port}")
        print(f"💾 Cache: {'Enabled' if settings.cache_enabled else 'Disabled'}")
        print(f"📈 Metrics: {'Enabled' if settings.metrics_enabled else 'Disabled'}")
        print(f"🔗 Dependencies: {', '.join(settings.dependencies)}")
        print()

        # Just import the main module - MCP Mesh will handle the rest!
        from .main import DataProcessorAgent

        print("✅ Data Processor Agent configured successfully")
        print("🎯 Agent capabilities: data parsing, transformation, analysis, export")
        print("📁 Supported formats: csv, json, xlsx, parquet, tsv")
        print()
        print("📡 MCP Mesh will automatically:")
        print("   - Discover the FastMCP app instance")
        print("   - Start the HTTP server on port", settings.http_port)
        print("   - Register capabilities with mesh registry")
        print("   - Handle dependency injection")
        print()
        print("🛑 Press Ctrl+C to stop the agent")

        # MCP Mesh auto_run=True will handle server startup
        # We just need to keep the process alive
        import signal

        def signal_handler(sig, frame):
            print("\n🛑 Received shutdown signal")
            print("✅ Shutdown complete")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Keep process alive - MCP Mesh handles the server
        signal.pause()

    except Exception as e:
        logger.error(f"Failed to start Data Processor Agent: {e}")
        print(f"❌ Error starting agent: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
