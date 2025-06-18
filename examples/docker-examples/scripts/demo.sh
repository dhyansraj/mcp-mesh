#!/bin/bash

# MCP Mesh Docker Demo Script
#
# This script demonstrates the key features of MCP Mesh in a Docker environment:
# - Service discovery and registration
# - Dependency injection between containers
# - Cross-container communication
# - meshctl dashboard capabilities

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REGISTRY_URL="http://localhost:8000"
HELLO_WORLD_URL="http://localhost:8081"
SYSTEM_AGENT_URL="http://localhost:8082"
DEMO_DELAY=3

print_header() {
    echo
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
}

print_step() {
    echo -e "${GREEN}➤ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

wait_for_service() {
    local url=$1
    local name=$2
    local max_attempts=30
    local attempt=1

    print_step "Waiting for $name to be ready..."

    while [ $attempt -le $max_attempts ]; do
        if curl -s -f "$url/health" > /dev/null 2>&1; then
            print_step "$name is ready!"
            return 0
        fi

        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done

    print_error "$name failed to start after $((max_attempts * 2)) seconds"
    return 1
}

check_prerequisites() {
    print_header "🔍 Checking Prerequisites"

    # Check if we're in the right directory
    if [ ! -f "docker-compose.yml" ]; then
        print_error "Please run this script from the examples/docker-examples directory"
        exit 1
    fi

    # Check required tools
    for tool in docker docker-compose curl jq; do
        if ! command -v $tool &> /dev/null; then
            print_error "$tool is required but not installed"
            exit 1
        fi
        print_step "$tool is available"
    done

    # Check if meshctl exists
    if [ -f "../../bin/meshctl" ]; then
        print_step "meshctl found at ../../bin/meshctl"
        MESHCTL="../../bin/meshctl"
    else
        print_info "meshctl not found - some demo steps will be skipped"
        MESHCTL=""
    fi
}

start_mesh() {
    print_header "🚀 Starting MCP Mesh"

    print_step "Starting Docker Compose services..."
    docker-compose up -d --build

    sleep 5

    print_step "Checking service status..."
    docker-compose ps
}

wait_for_all_services() {
    print_header "⏳ Waiting for All Services"

    wait_for_service "$REGISTRY_URL" "Registry"
    wait_for_service "$HELLO_WORLD_URL" "Hello World Agent"
    wait_for_service "$SYSTEM_AGENT_URL" "System Agent"

    print_step "All services are ready!"
    sleep $DEMO_DELAY
}

demo_service_discovery() {
    print_header "🔍 Service Discovery Demo"

    print_step "1. Registry health check:"
    curl -s "$REGISTRY_URL/health" | jq '.'
    sleep $DEMO_DELAY

    print_step "2. List registered agents:"
    curl -s "$REGISTRY_URL/agents" | jq '.[] | {name: .name, status: .status, endpoint: .endpoint}'
    sleep $DEMO_DELAY

    print_step "3. Hello World Agent details:"
    curl -s "$REGISTRY_URL/agents/hello-world" | jq '.'
    sleep $DEMO_DELAY

    print_step "4. System Agent details:"
    curl -s "$REGISTRY_URL/agents/system-agent" | jq '.'
    sleep $DEMO_DELAY
}

demo_basic_agent_functions() {
    print_header "🛠️ Basic Agent Functions Demo"

    print_step "1. System Agent - Get current date:"
    curl -s "$SYSTEM_AGENT_URL/tools/date_service" | jq '.'
    sleep $DEMO_DELAY

    print_step "2. System Agent - Get system info:"
    curl -s "$SYSTEM_AGENT_URL/tools/info" | jq '.'
    sleep $DEMO_DELAY

    print_step "3. Hello World Agent - Simple greeting (no dependencies yet):"
    curl -s "$HELLO_WORLD_URL/tools/greeting" | jq '.'
    sleep $DEMO_DELAY

    print_step "4. Hello World Agent - Container status:"
    curl -s "$HELLO_WORLD_URL/tools/container_status" | jq '.'
    sleep $DEMO_DELAY
}

demo_dependency_injection() {
    print_header "🔗 Dependency Injection Demo"

    print_info "Waiting for dependency injection to complete (30 seconds)..."
    sleep 30

    print_step "1. Hello World Agent - Greeting with injected date service:"
    curl -s "$HELLO_WORLD_URL/tools/greeting" | jq '.'
    sleep $DEMO_DELAY

    print_step "2. Hello World Agent - Advanced greeting with system info:"
    curl -s "$HELLO_WORLD_URL/tools/advanced_greeting" | jq '.'
    sleep $DEMO_DELAY

    print_step "3. Hello World Agent - Full dependency test:"
    curl -s "$HELLO_WORLD_URL/tools/dependency_test" | jq '.'
    sleep $DEMO_DELAY

    print_step "4. System Agent - Health check with self-dependency:"
    curl -s "$SYSTEM_AGENT_URL/tools/health_check" | jq '.'
    sleep $DEMO_DELAY
}

demo_resilient_architecture() {
    print_header "🛡️ Resilient Architecture Demo"

    print_step "1. Testing agents before registry connection:"
    print_info "Agents work standalone, then enhance when registry is available"
    curl -s "$HELLO_WORLD_URL/tools/greeting" | jq '.'
    sleep $DEMO_DELAY

    print_step "2. Stopping registry to test resilience:"
    docker-compose stop registry
    sleep 3

    print_step "3. Agents should continue working with cached connections:"
    curl -s "$HELLO_WORLD_URL/tools/dependency_test" | jq '.'
    sleep $DEMO_DELAY

    print_step "4. Restarting registry:"
    docker-compose start registry
    print_info "Waiting for registry to be ready..."
    wait_for_service "$REGISTRY_URL" "Registry (restarted)"

    print_step "5. Agents should reconnect automatically:"
    curl -s "$HELLO_WORLD_URL/tools/dependency_test" | jq '.'
    sleep $DEMO_DELAY

    print_info "✓ Resilient architecture demonstrated!"
}

demo_cross_container_communication() {
    print_header "🌐 Cross-Container Communication Demo"

    print_step "1. System Agent - Mesh connectivity test:"
    curl -s "$SYSTEM_AGENT_URL/tools/mesh_test" | jq '.'
    sleep $DEMO_DELAY

    print_step "2. Container information comparison:"
    echo "Hello World Container Info:"
    curl -s "$HELLO_WORLD_URL/tools/container_status" | jq '.container_id, .environment'

    echo "System Agent Container Info:"
    curl -s "$SYSTEM_AGENT_URL/tools/mesh_test" | jq '.container_id, .environment'
    sleep $DEMO_DELAY

    print_step "3. Demonstrate service calls across containers:"
    curl -s "$HELLO_WORLD_URL/tools/dependency_test" | jq '.date_service, .system_info_service'
    sleep $DEMO_DELAY
}

demo_meshctl_dashboard() {
    print_header "📊 meshctl Dashboard Demo"

    if [ -z "$MESHCTL" ]; then
        print_info "meshctl not available - skipping dashboard demo"
        return
    fi

    print_step "1. List all agents via meshctl:"
    $MESHCTL list --registry "$REGISTRY_URL"
    sleep $DEMO_DELAY

    print_step "2. Get detailed status via meshctl:"
    $MESHCTL status --registry "$REGISTRY_URL"
    sleep $DEMO_DELAY

    print_step "3. meshctl configuration check:"
    $MESHCTL config show --registry "$REGISTRY_URL"
    sleep $DEMO_DELAY
}

demo_container_logs() {
    print_header "📋 Container Logs Demo"

    print_step "1. Recent registry logs:"
    docker-compose logs --tail=10 registry
    sleep $DEMO_DELAY

    print_step "2. Recent hello-world-agent logs:"
    docker-compose logs --tail=10 hello-world-agent
    sleep $DEMO_DELAY

    print_step "3. Recent system-agent logs:"
    docker-compose logs --tail=10 system-agent
    sleep $DEMO_DELAY
}

demo_scaling_example() {
    print_header "📈 Scaling Demo"

    print_step "1. Current service status:"
    docker-compose ps
    sleep $DEMO_DELAY

    print_step "2. Scale hello-world-agent to 2 instances:"
    print_info "(This demonstrates how multiple instances would work)"
    print_info "docker-compose up -d --scale hello-world-agent=2"
    print_info "Note: This would require port adjustments for the demo"
    sleep $DEMO_DELAY
}

cleanup_demo() {
    print_header "🧹 Cleanup"

    print_step "Demo completed!"
    print_info "To stop the mesh: docker-compose down"
    print_info "To remove volumes: docker-compose down -v"
    print_info "To view live logs: docker-compose logs -f"
    print_info "To restart: docker-compose up -d"
}

run_full_demo() {
    echo -e "${BLUE}"
    echo "🐳 MCP Mesh Docker Demo"
    echo "======================="
    echo "This demo showcases:"
    echo "• Go registry + Python agents"
    echo "• Resilient architecture (agents work standalone)"
    echo "• Automatic service discovery"
    echo "• Dependency injection across containers"
    echo "• Registry failure recovery"
    echo "• meshctl dashboard capabilities"
    echo "• Cross-container communication"
    echo -e "${NC}"

    read -p "Press Enter to start the demo (or Ctrl+C to cancel)..."

    check_prerequisites
    start_mesh
    wait_for_all_services
    demo_service_discovery
    demo_basic_agent_functions
    demo_dependency_injection
    demo_resilient_architecture
    demo_cross_container_communication
    demo_meshctl_dashboard
    demo_container_logs
    demo_scaling_example
    cleanup_demo
}

# Main script logic
case "${1:-full}" in
    "full")
        run_full_demo
        ;;
    "quick")
        check_prerequisites
        start_mesh
        wait_for_all_services
        demo_dependency_injection
        cleanup_demo
        ;;
    "status")
        demo_service_discovery
        demo_meshctl_dashboard
        ;;
    "test")
        demo_basic_agent_functions
        demo_dependency_injection
        ;;
    "logs")
        demo_container_logs
        ;;
    "resilience")
        demo_resilient_architecture
        ;;
    *)
        echo "Usage: $0 [full|quick|status|test|logs|resilience]"
        echo "  full       - Complete demo (default)"
        echo "  quick      - Quick dependency injection demo"
        echo "  status     - Service discovery and status demo"
        echo "  test       - Agent function testing"
        echo "  logs       - Show container logs"
        echo "  resilience - Test resilient architecture (registry failure/recovery)"
        exit 1
        ;;
esac
