#!/bin/bash
# Development helper script for Data Processor Agent

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

# Check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker first."
        exit 1
    fi
}

# Build the Docker image
build_image() {
    log_info "Building Docker image..."
    bash scripts/build.sh
    log_success "Image built successfully"
}

# Run the agent in development mode
run_dev() {
    check_docker
    
    log_info "Starting Data Processor Agent in development mode..."
    
    # Create necessary directories
    mkdir -p data logs
    
    docker run -it --rm \
        --name data-processor-dev \
        -p 9090:9090 \
        -e LOG_LEVEL=DEBUG \
        -e CACHE_ENABLED=true \
        -e METRICS_ENABLED=true \
        -v "$(pwd)/data:/app/data:ro" \
        -v "$(pwd)/logs:/app/logs" \
        data-processor-agent:latest
}

# Run with shell access for debugging
run_shell() {
    check_docker
    
    log_info "Starting debug shell..."
    
    docker run -it --rm \
        --name data-processor-shell \
        -p 9090:9090 \
        -v "$(pwd)/data:/app/data:ro" \
        -v "$(pwd)/logs:/app/logs" \
        data-processor-agent:latest shell
}

# Run tests inside container
run_tests() {
    check_docker
    
    log_info "Running tests in container..."
    
    docker run --rm \
        --name data-processor-test \
        -v "$(pwd):/app/src:ro" \
        data-processor-agent:latest \
        python -m pytest /app/src/tests/ -v
}

# Show agent status
show_status() {
    log_info "Data Processor Agent Status:"
    
    # Check if container is running
    if docker ps -q -f name=data-processor 2>/dev/null | grep -q .; then
        log_success "Agent is running"
        docker ps -f name=data-processor --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        
        # Try health check
        log_info "Checking health..."
        if curl -s http://localhost:9090/health >/dev/null 2>&1; then
            log_success "Health check passed"
        else
            log_warning "Health check failed or agent not ready"
        fi
    else
        log_warning "Agent is not running"
    fi
}

# Clean up containers and images
cleanup() {
    log_info "Cleaning up..."
    
    # Stop running containers
    docker ps -q -f name=data-processor | xargs -r docker stop
    
    # Remove containers
    docker ps -aq -f name=data-processor | xargs -r docker rm
    
    # Remove dangling images
    docker images -f dangling=true -q | xargs -r docker rmi
    
    log_success "Cleanup completed"
}

# Start with docker-compose
compose_up() {
    check_docker
    
    log_info "Starting with Docker Compose..."
    docker-compose up -d
    
    log_success "Services started. Check status with 'docker-compose ps'"
    log_info "Agent logs: docker-compose logs -f data-processor"
}

# Stop docker-compose services
compose_down() {
    log_info "Stopping Docker Compose services..."
    docker-compose down
    log_success "Services stopped"
}

# Show help
show_help() {
    echo "Data Processor Agent Development Helper"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  build       Build the Docker image"
    echo "  dev         Run agent in development mode"
    echo "  shell       Start debug shell in container"
    echo "  test        Run tests in container"
    echo "  status      Show agent status"
    echo "  cleanup     Clean up containers and images"
    echo "  up          Start with docker-compose"
    echo "  down        Stop docker-compose services"
    echo "  help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 build      # Build the Docker image"
    echo "  $0 dev        # Run in development mode"
    echo "  $0 shell      # Debug the container"
    echo "  $0 status     # Check if agent is running"
}

# Main command dispatcher
case "${1:-help}" in
    build)
        build_image
        ;;
    dev)
        run_dev
        ;;
    shell)
        run_shell
        ;;
    test)
        run_tests
        ;;
    status)
        show_status
        ;;
    cleanup)
        cleanup
        ;;
    up)
        compose_up
        ;;
    down)
        compose_down
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac