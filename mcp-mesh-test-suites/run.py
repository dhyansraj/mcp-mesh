#!/usr/bin/env python3
"""
MCP Mesh Integration Test Suite Runner

Usage:
    ./run.py --all                    # Run all tests
    ./run.py --uc uc01_scaffolding    # Run all scaffolding tests
    ./run.py --tc uc01_scaffolding/tc01_python_agent  # Run specific test
    ./run.py --dry-run --all          # List tests without running
"""

import sys
from pathlib import Path

# Add test-suite to path
suite_dir = Path(__file__).parent
framework_dir = suite_dir.parent / "test-suite"
sys.path.insert(0, str(framework_dir))

# Import and run CLI
from tsuite.cli import main

if __name__ == "__main__":
    # Set default suite path to current directory
    sys.argv.extend(["--suite-path", str(suite_dir)])
    main()
