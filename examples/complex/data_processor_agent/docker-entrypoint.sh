#!/bin/bash
set -e

# Docker entrypoint script for Data Processor Agent
# Provides flexible container startup with environment-based configuration

echo "🚀 Starting Data Processor Agent Container"
echo "📊 Agent: ${AGENT_NAME:-data-processor}"
echo "🌐 Port: ${HTTP_PORT:-9090}"
echo "📝 Log Level: ${LOG_LEVEL:-INFO}"
echo "💾 Cache: ${CACHE_ENABLED:-true}"
echo "📈 Metrics: ${METRICS_ENABLED:-true}"

# Create required directories
mkdir -p "${TEMP_DIR:-/app/cache}"
mkdir -p /app/logs

# Wait for dependencies if specified
if [ -n "$WAIT_FOR_REGISTRY" ]; then
    echo "⏳ Waiting for registry at $WAIT_FOR_REGISTRY..."
    timeout 60 bash -c "until curl -s $WAIT_FOR_REGISTRY/health; do sleep 1; done"
    echo "✅ Registry is ready"
fi

if [ -n "$WAIT_FOR_DATABASE" ]; then
    echo "⏳ Waiting for database at $WAIT_FOR_DATABASE..."
    timeout 60 bash -c "until nc -z ${WAIT_FOR_DATABASE%:*} ${WAIT_FOR_DATABASE#*:}; do sleep 1; done"
    echo "✅ Database is ready"
fi

# Export configuration to environment
export AGENT_NAME="${AGENT_NAME:-data-processor}"
export HTTP_PORT="${HTTP_PORT:-9090}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export CACHE_ENABLED="${CACHE_ENABLED:-true}"
export METRICS_ENABLED="${METRICS_ENABLED:-true}"
export TEMP_DIR="${TEMP_DIR:-/app/cache}"

# Handle different execution modes
case "$1" in
    # Standard agent execution
    "data-processor-agent")
        echo "🎯 Starting agent via command line script..."
        exec data-processor-agent
        ;;
    
    # Python module execution
    "python-module")
        echo "🐍 Starting agent via Python module..."
        exec python -m data_processor_agent
        ;;
    
    # Direct Python execution
    "python-direct")
        echo "📄 Starting agent via direct Python execution..."
        exec python /app/main.py
        ;;
    
    # Shell for debugging
    "shell" | "bash")
        echo "🐚 Starting shell for debugging..."
        exec /bin/bash
        ;;
    
    # Health check mode
    "health")
        echo "🏥 Running health check..."
        curl -f "http://localhost:${HTTP_PORT:-9090}/health" || exit 1
        ;;
    
    # Configuration dump
    "config")
        echo "⚙️ Current configuration:"
        echo "  AGENT_NAME: ${AGENT_NAME}"
        echo "  HTTP_PORT: ${HTTP_PORT}"
        echo "  LOG_LEVEL: ${LOG_LEVEL}"
        echo "  CACHE_ENABLED: ${CACHE_ENABLED}"
        echo "  METRICS_ENABLED: ${METRICS_ENABLED}"
        echo "  TEMP_DIR: ${TEMP_DIR}"
        ;;
    
    # Custom command
    *)
        echo "🔧 Executing custom command: $@"
        exec "$@"
        ;;
esac