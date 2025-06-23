#!/bin/bash
# Permanent test runner script that always uses the correct Python environment

set -e  # Exit on error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Always use the project's .venv Python
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
PYTEST_BIN="$SCRIPT_DIR/.venv/bin/pytest"

# Check if .venv exists
if [ ! -f "$PYTHON_BIN" ]; then
    echo "❌ Error: .venv not found at $PYTHON_BIN"
    echo "Please run: python -m venv .venv && .venv/bin/pip install -e src/runtime/python/"
    exit 1
fi

echo "🐍 Using Python: $PYTHON_BIN"
echo "🧪 Using pytest: $PYTEST_BIN"

# Run tests with the correct environment
if [ $# -eq 0 ]; then
    # No arguments - run all unit tests
    echo "🚀 Running all unit tests..."
    "$PYTEST_BIN" src/runtime/python/tests/unit/ -v
else
    # Run specific tests
    echo "🚀 Running specific tests: $@"
    "$PYTEST_BIN" "$@" -v
fi
