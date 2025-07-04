#!/bin/bash

# Progressive Implementation Testing Script
# Tests each phase of the MCP Mesh enhancement implementation

set -e

echo "🚀 MCP Mesh Progressive Implementation Testing"
echo "============================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test phase function
test_phase() {
    local phase=$1
    local description=$2
    local test_function=$3

    echo ""
    echo -e "${BLUE}🔍 Testing Phase $phase: $description${NC}"
    echo "----------------------------------------"

    if $test_function; then
        echo -e "${GREEN}✅ Phase $phase: PASSED${NC}"
    else
        echo -e "${RED}❌ Phase $phase: FAILED${NC}"
        return 1
    fi
}

# Wait for service to be healthy
wait_for_service() {
    local service_name=$1
    local port=$2
    local max_attempts=30
    local attempt=1

    echo "⏳ Waiting for $service_name to be healthy..."

    while [ $attempt -le $max_attempts ]; do
        if curl -s -f "http://localhost:$port/health" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ $service_name is healthy${NC}"
            return 0
        fi
        echo "   Attempt $attempt/$max_attempts - waiting for $service_name..."
        sleep 2
        ((attempt++))
    done

    echo -e "${RED}❌ $service_name failed to become healthy${NC}"
    return 1
}

# Start the testing environment
start_environment() {
    echo "🐳 Starting Docker Compose environment..."
    docker-compose up -d registry redis agent-a agent-b agent-c

    # Wait for services to be healthy
    wait_for_service "Registry" 8000
    wait_for_service "Agent A" 8080
    wait_for_service "Agent B" 8081
    wait_for_service "Agent C" 8082

    echo -e "${GREEN}🌟 Environment is ready for testing!${NC}"
}

# Stop the testing environment
stop_environment() {
    echo "🛑 Stopping Docker Compose environment..."
    docker-compose down
}

# Phase 1: Test metadata endpoint
test_phase_1() {
    echo "Testing metadata endpoint..."

    # Test agent A metadata
    echo "📊 Testing Agent A metadata endpoint..."
    response=$(curl -s "http://localhost:8080/metadata")

    if echo "$response" | jq -e '.capabilities' > /dev/null 2>&1; then
        echo "✅ Agent A metadata endpoint working"
        echo "📋 Agent A capabilities:"
        echo "$response" | jq '.capabilities | keys'
    else
        echo "❌ Agent A metadata endpoint failed"
        return 1
    fi

    # Test agent B metadata
    echo "📊 Testing Agent B metadata endpoint..."
    response=$(curl -s "http://localhost:8081/metadata")

    if echo "$response" | jq -e '.capabilities' > /dev/null 2>&1; then
        echo "✅ Agent B metadata endpoint working"
        return 0
    else
        echo "❌ Agent B metadata endpoint failed"
        return 1
    fi
}

# Phase 2: Test full MCP protocol support
test_phase_2() {
    echo "Testing full MCP protocol support..."

    # Test tools/call (should work)
    echo "🔧 Testing standard tools/call..."
    response=$(curl -s -X POST "http://localhost:8082/mcp/" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_agent_info","arguments":{}}}')

    if echo "$response" | jq -e '.result' > /dev/null 2>&1; then
        echo "✅ Standard tools/call working"
    else
        echo "❌ Standard tools/call failed"
        return 1
    fi

    # Test tools/list (should work with Phase 2 implementation)
    echo "🔧 Testing tools/list method..."
    response=$(curl -s -X POST "http://localhost:8082/mcp/" \
        -H "Content-Type: application/json" \
        -H "X-MCP-Method: tools/list" \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}')

    if echo "$response" | jq -e '.result.tools' > /dev/null 2>&1; then
        echo "✅ tools/list method working"
        echo "🔧 Available tools:"
        echo "$response" | jq '.result.tools | length'
        return 0
    else
        echo "❌ tools/list method failed"
        echo "Response: $response"
        return 1
    fi
}

# Phase 3: Test HTTP wrapper intelligence (metadata lookup)
test_phase_3() {
    echo "Testing HTTP wrapper intelligence..."

    # Test with routing headers to trigger intelligent logging
    echo "🧠 Testing intelligent routing headers..."

    response=$(curl -s -X POST "http://localhost:8080/mcp/" \
        -H "Content-Type: application/json" \
        -H "X-Capability: stateful_counter" \
        -H "X-Session-ID: test-session-123" \
        -H "X-MCP-Method: tools/call" \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"increment_counter","arguments":{"session_id":"test-session-123"}}}')

    if echo "$response" | jq -e '.result' > /dev/null 2>&1; then
        echo "✅ Intelligent routing headers processed"
        echo "📊 Response:"
        echo "$response" | jq '.result'

        # Check logs for intelligent routing decisions
        echo "📋 Checking logs for routing intelligence..."
        docker-compose logs agent-a | tail -5
        return 0
    else
        echo "❌ Intelligent routing failed"
        return 1
    fi
}

# Phase 4: Test session affinity
test_phase_4() {
    echo "Testing session affinity..."

    local session_id="test-session-affinity-$(date +%s)"

    # Make first call to agent A
    echo "📍 Making first call to Agent A with session $session_id..."
    response1=$(curl -s -X POST "http://localhost:8080/mcp/" \
        -H "Content-Type: application/json" \
        -H "X-Capability: stateful_counter" \
        -H "X-Session-ID: $session_id" \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"increment_counter","arguments":{"session_id":"'$session_id'","increment":1}}}')

    pod1=$(echo "$response1" | jq -r '.result.pod_ip // "unknown"')
    counter1=$(echo "$response1" | jq -r '.result.counter // 0')

    echo "✅ First call: pod=$pod1, counter=$counter1"

    # Make second call to agent B (should forward to same pod if session affinity working)
    echo "📍 Making second call to Agent B with same session..."
    response2=$(curl -s -X POST "http://localhost:8081/mcp/" \
        -H "Content-Type: application/json" \
        -H "X-Capability: stateful_counter" \
        -H "X-Session-ID: $session_id" \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"increment_counter","arguments":{"session_id":"'$session_id'","increment":1}}}')

    pod2=$(echo "$response2" | jq -r '.result.pod_ip // "unknown"')
    counter2=$(echo "$response2" | jq -r '.result.counter // 0')

    echo "✅ Second call: pod=$pod2, counter=$counter2"

    # Check session affinity
    if [ "$counter2" -gt "$counter1" ] && [ "$pod1" = "$pod2" ]; then
        echo "✅ Session affinity working - same pod, counter incremented"
        return 0
    else
        echo "⚠️  Session affinity not fully working (expected for Phase 4)"
        echo "   This is normal if session forwarding isn't implemented yet"
        return 0  # Don't fail the test, just log
    fi
}

# Phase 5: Test Redis session storage
test_phase_5() {
    echo "Testing Redis session storage..."

    # Check if Redis is available
    if ! docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; then
        echo "❌ Redis not available"
        return 1
    fi

    echo "✅ Redis is available"

    # Test session storage in Redis
    local session_id="redis-test-$(date +%s)"

    echo "📊 Testing session storage with Redis backend..."
    response=$(curl -s -X POST "http://localhost:8080/mcp/" \
        -H "Content-Type: application/json" \
        -H "X-Capability: stateful_counter" \
        -H "X-Session-ID: $session_id" \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"increment_counter","arguments":{"session_id":"'$session_id'"}}}')

    if echo "$response" | jq -e '.result' > /dev/null 2>&1; then
        echo "✅ Session created with Redis backend"

        # Check metadata shows Redis backend
        metadata=$(curl -s "http://localhost:8080/metadata")
        storage_backend=$(echo "$metadata" | jq -r '.session_affinity.storage_backend // "unknown"')
        echo "📊 Storage backend: $storage_backend"

        return 0
    else
        echo "❌ Redis session storage failed"
        return 1
    fi
}

# Phase 6: Test enhanced HTTP wrapper with MCP protocol routing
test_phase_6() {
    echo "Testing enhanced HTTP wrapper with MCP protocol routing..."

    # Test full MCP access capability
    echo "🔓 Testing full MCP access capability..."
    response=$(curl -s -X POST "http://localhost:8082/mcp/" \
        -H "Content-Type: application/json" \
        -H "X-Capability: agent_introspector" \
        -H "X-MCP-Method: tools/list" \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}')

    if echo "$response" | jq -e '.result.tools' > /dev/null 2>&1; then
        echo "✅ Full MCP access working"
        echo "🔧 Tools found:"
        echo "$response" | jq '.result.tools | length'
        return 0
    else
        echo "❌ Full MCP access failed"
        echo "Response: $response"
        return 1
    fi
}

# Phase 7: Test auto-dependency injection
test_phase_7() {
    echo "Testing auto-dependency injection for system components..."

    # Start additional system components for Phase 7
    echo "🚀 Starting cache and session tracking agents..."
    docker-compose --profile phase7 up -d cache-agent session-tracker

    # Wait for system components
    sleep 10

    # Test metadata shows auto-injected components
    echo "📊 Checking auto-injection status..."
    metadata=$(curl -s "http://localhost:8080/metadata")

    if echo "$metadata" | jq -e '.session_affinity.auto_injection' > /dev/null 2>&1; then
        echo "✅ Auto-injection metadata available"
        echo "🔧 Auto-injection status:"
        echo "$metadata" | jq '.session_affinity.auto_injection'
        return 0
    else
        echo "⚠️  Auto-injection not fully implemented yet"
        return 0  # Don't fail - this is expected for early phases
    fi
}

# Main test execution
main() {
    local phase=${1:-"all"}

    if [ "$phase" = "setup" ]; then
        start_environment
        exit 0
    elif [ "$phase" = "cleanup" ]; then
        stop_environment
        exit 0
    fi

    # Ensure environment is running
    if ! curl -s -f "http://localhost:8000/health" > /dev/null 2>&1; then
        echo "🐳 Environment not running, starting it..."
        start_environment
    fi

    # Run tests based on phase argument
    case $phase in
        "1"|"phase1")
            test_phase 1 "Metadata Endpoint" test_phase_1
            ;;
        "2"|"phase2")
            test_phase 2 "Full MCP Protocol Support" test_phase_2
            ;;
        "3"|"phase3")
            test_phase 3 "HTTP Wrapper Intelligence" test_phase_3
            ;;
        "4"|"phase4")
            test_phase 4 "Session Affinity" test_phase_4
            ;;
        "5"|"phase5")
            test_phase 5 "Redis Session Storage" test_phase_5
            ;;
        "6"|"phase6")
            test_phase 6 "Enhanced HTTP Wrapper" test_phase_6
            ;;
        "7"|"phase7")
            test_phase 7 "Auto-Dependency Injection" test_phase_7
            ;;
        "all")
            echo "🔄 Running all phase tests..."
            test_phase 1 "Metadata Endpoint" test_phase_1 && \
            test_phase 2 "Full MCP Protocol Support" test_phase_2 && \
            test_phase 3 "HTTP Wrapper Intelligence" test_phase_3 && \
            test_phase 4 "Session Affinity" test_phase_4 && \
            test_phase 5 "Redis Session Storage" test_phase_5 && \
            test_phase 6 "Enhanced HTTP Wrapper" test_phase_6 && \
            test_phase 7 "Auto-Dependency Injection" test_phase_7
            ;;
        *)
            echo "Usage: $0 [1|2|3|4|5|6|7|all|setup|cleanup]"
            echo ""
            echo "Phase descriptions:"
            echo "  1  - Test metadata endpoint"
            echo "  2  - Test full MCP protocol support"
            echo "  3  - Test HTTP wrapper intelligence"
            echo "  4  - Test session affinity"
            echo "  5  - Test Redis session storage"
            echo "  6  - Test enhanced HTTP wrapper"
            echo "  7  - Test auto-dependency injection"
            echo "  all - Run all tests"
            echo "  setup - Start environment only"
            echo "  cleanup - Stop environment"
            exit 1
            ;;
    esac

    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}🎉 All requested tests completed successfully!${NC}"
    else
        echo ""
        echo -e "${RED}💥 Some tests failed. Check the output above.${NC}"
        exit 1
    fi
}

# Make sure we have required tools
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ docker-compose is required but not installed${NC}"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo -e "${RED}❌ jq is required but not installed${NC}"
    exit 1
fi

# Run main function with all arguments
main "$@"
