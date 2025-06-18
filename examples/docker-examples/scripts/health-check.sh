#!/bin/bash

# MCP Mesh Health Check Script
#
# Checks the health of all services in the Docker Compose setup

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

print_status() {
    local service=$1
    local status=$2
    local message=$3

    if [ "$status" = "healthy" ]; then
        echo -e "${GREEN}✓ $service: $message${NC}"
    elif [ "$status" = "warning" ]; then
        echo -e "${YELLOW}⚠ $service: $message${NC}"
    else
        echo -e "${RED}✗ $service: $message${NC}"
    fi
}

check_service_health() {
    local name=$1
    local url=$2

    if curl -s -f "$url/health" > /dev/null 2>&1; then
        local health_data=$(curl -s "$url/health")
        print_status "$name" "healthy" "Service is responding"
        echo "   Response: $health_data"
        return 0
    else
        print_status "$name" "unhealthy" "Service is not responding"
        return 1
    fi
}

check_container_status() {
    echo -e "${BLUE}Container Status:${NC}"
    docker-compose ps
    echo
}

check_service_connectivity() {
    echo -e "${BLUE}Service Health Checks:${NC}"

    local healthy=0
    local total=3

    if check_service_health "Registry" "$REGISTRY_URL"; then
        healthy=$((healthy + 1))
    fi
    echo

    if check_service_health "Hello World Agent" "$HELLO_WORLD_URL"; then
        healthy=$((healthy + 1))
    fi
    echo

    if check_service_health "System Agent" "$SYSTEM_AGENT_URL"; then
        healthy=$((healthy + 1))
    fi
    echo

    echo -e "${BLUE}Overall Health: $healthy/$total services healthy${NC}"

    if [ $healthy -eq $total ]; then
        print_status "Overall" "healthy" "All services are running"
        return 0
    else
        print_status "Overall" "unhealthy" "Some services are down"
        return 1
    fi
}

check_agent_registration() {
    echo -e "${BLUE}Agent Registration Status:${NC}"

    if curl -s -f "$REGISTRY_URL/agents" > /dev/null 2>&1; then
        local agents=$(curl -s "$REGISTRY_URL/agents")
        local count=$(echo "$agents" | jq '. | length' 2>/dev/null || echo "0")

        if [ "$count" -gt 0 ]; then
            print_status "Registration" "healthy" "$count agents registered"
            echo "$agents" | jq '.[] | {name: .name, status: .status, endpoint: .endpoint}' 2>/dev/null || echo "$agents"
        else
            print_status "Registration" "warning" "No agents registered yet"
        fi
    else
        print_status "Registration" "unhealthy" "Cannot reach registry"
    fi
    echo
}

check_dependency_injection() {
    echo -e "${BLUE}Dependency Injection Status:${NC}"

    # Test if hello-world can call system services
    if curl -s -f "$HELLO_WORLD_URL/tools/dependency_test" > /dev/null 2>&1; then
        local result=$(curl -s "$HELLO_WORLD_URL/tools/dependency_test")
        local date_status=$(echo "$result" | jq -r '.date_service' 2>/dev/null || echo "unknown")
        local info_status=$(echo "$result" | jq -r '.system_info_service' 2>/dev/null || echo "unknown")

        if [[ "$date_status" == *"available"* ]]; then
            print_status "Date Service Injection" "healthy" "Working"
        else
            print_status "Date Service Injection" "warning" "Not yet available"
        fi

        if [[ "$info_status" == *"available"* ]]; then
            print_status "Info Service Injection" "healthy" "Working"
        else
            print_status "Info Service Injection" "warning" "Not yet available"
        fi
    else
        print_status "Dependency Injection" "unhealthy" "Cannot test dependency injection"
    fi
    echo
}

check_docker_network() {
    echo -e "${BLUE}Docker Network Status:${NC}"

    if docker network inspect mcp-mesh-network > /dev/null 2>&1; then
        print_status "Network" "healthy" "mcp-mesh-network exists"
        local containers=$(docker network inspect mcp-mesh-network | jq '.[0].Containers | length' 2>/dev/null || echo "0")
        echo "   Connected containers: $containers"
    else
        print_status "Network" "unhealthy" "mcp-mesh-network not found"
    fi
    echo
}

check_volumes() {
    echo -e "${BLUE}Volume Status:${NC}"

    if docker volume inspect mcp-mesh-registry-data > /dev/null 2>&1; then
        print_status "Registry Volume" "healthy" "mcp-mesh-registry-data exists"
    else
        print_status "Registry Volume" "warning" "Registry volume not found"
    fi
    echo
}

run_full_health_check() {
    echo -e "${BLUE}🏥 MCP Mesh Health Check${NC}"
    echo -e "${BLUE}========================${NC}"
    echo

    check_container_status
    check_service_connectivity
    check_agent_registration
    check_dependency_injection
    check_docker_network
    check_volumes

    echo -e "${BLUE}Health check completed.${NC}"
}

# Main script logic
case "${1:-full}" in
    "full")
        run_full_health_check
        ;;
    "services")
        check_service_connectivity
        ;;
    "agents")
        check_agent_registration
        check_dependency_injection
        ;;
    "docker")
        check_container_status
        check_docker_network
        check_volumes
        ;;
    "quick")
        check_container_status
        check_service_connectivity
        ;;
    *)
        echo "Usage: $0 [full|services|agents|docker|quick]"
        echo "  full     - Complete health check (default)"
        echo "  services - Check service connectivity only"
        echo "  agents   - Check agent registration and dependencies"
        echo "  docker   - Check Docker containers, networks, volumes"
        echo "  quick    - Quick container and service check"
        exit 1
        ;;
esac
