#!/bin/bash
# Wrapper to debug Python execution

echo "=== PYTHON DEBUG ===" >&2
echo "Python command: $0 $@" >&2
echo "Which python: $(which python)" >&2
echo "Python version: $(python --version 2>&1)" >&2
echo "PYTHONPATH: $PYTHONPATH" >&2
echo "PATH: $PATH" >&2
echo "===================" >&2

# Now run the actual Python
exec python "$@"
