#!/bin/bash
# Development setup script for multi-file agents with mcp-mesh from source

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

# Detect if we're in the mcp-mesh project structure
detect_project_root() {
    local current_dir="$(pwd)"
    local project_root=""
    
    # Check if we're already in project root
    if [[ -f "pyproject.toml" && -d "mcp_mesh" && -d ".venv" ]]; then
        project_root="$(pwd)"
    # Check if we're in examples/complex/data_processor_agent
    elif [[ "$(basename "$current_dir")" == "data_processor_agent" && -f "../../../pyproject.toml" ]]; then
        project_root="$(cd ../../../ && pwd)"
    # Check if we're in examples/complex
    elif [[ "$(basename "$current_dir")" == "complex" && -f "../../pyproject.toml" ]]; then
        project_root="$(cd ../../ && pwd)"
    # Check if we're in examples
    elif [[ "$(basename "$current_dir")" == "examples" && -f "../pyproject.toml" ]]; then
        project_root="$(cd .. && pwd)"
    else
        log_error "Could not detect mcp-mesh project root. Please run from:"
        echo "  - mcp-mesh project root"
        echo "  - examples/complex/data_processor_agent/"
        echo "  - examples/complex/"
        echo "  - examples/"
        exit 1
    fi
    
    echo "$project_root"
}

# Setup development environment
setup_dev_environment() {
    local project_root="$1"
    local agent_dir="$project_root/examples/complex/data_processor_agent"
    
    log_info "Setting up MCP Mesh + Agent development environment"
    log_info "Project root: $project_root"
    log_info "Agent directory: $agent_dir"
    
    # Ensure we have the shared .venv
    if [[ ! -d "$project_root/.venv" ]]; then
        log_warning "No .venv found at project root. Creating one..."
        cd "$project_root"
        python -m venv .venv
        log_success "Created .venv at $project_root/.venv"
    fi
    
    # Activate the virtual environment
    log_info "Activating shared virtual environment..."
    source "$project_root/.venv/bin/activate"
    
    # Upgrade pip
    log_info "Upgrading pip..."
    pip install --upgrade pip
    
    # Install mcp-mesh in editable mode (framework development)
    log_info "Installing mcp-mesh framework in editable mode..."
    cd "$project_root"
    pip install -e ".[dev]"
    log_success "MCP Mesh framework installed for development"
    
    # Install agent in editable mode (agent development)
    log_info "Installing data processor agent in editable mode..."
    cd "$agent_dir"
    pip install -e ".[dev]"
    log_success "Data processor agent installed for development"
    
    # Verify installations
    log_info "Verifying installations..."
    
    # Check mcp-mesh
    if python -c "import mcp_mesh; print(f'✅ mcp-mesh: {mcp_mesh.__version__}')" 2>/dev/null; then
        log_success "MCP Mesh framework is working"
    else
        log_error "MCP Mesh framework installation failed"
        exit 1
    fi
    
    # Check agent package structure
    if python -c "from data_processor_agent.config import get_settings; print(f'✅ Agent config: {get_settings().agent_name}')" 2>/dev/null; then
        log_success "Agent package structure is working"
    else
        log_warning "Agent package has import issues (this may be normal for MCP dependencies)"
    fi
    
    log_success "Development environment setup complete!"
    
    # Show usage instructions
    cat << EOF

🚀 Development Environment Ready!

📁 Project Structure:
   $project_root/
   ├── .venv/                    # Shared virtual environment
   ├── mcp_mesh/                 # Framework code (editable)
   └── examples/complex/data_processor_agent/  # Agent code (editable)

🔧 Usage:
   # Activate environment
   source $project_root/.venv/bin/activate
   
   # Work on framework
   cd $project_root
   # Make changes to mcp_mesh/, they're immediately available
   
   # Work on agent
   cd $project_root/examples/complex/data_processor_agent
   # Make changes to data_processor_agent/, they're immediately available
   
   # Test agent
   python -m data_processor_agent
   python test_structure.py
   
   # Run framework tests
   cd $project_root
   pytest tests/

📦 Both packages are installed in editable mode:
   - Changes to mcp-mesh are immediately available to agents
   - Changes to agent code are immediately testable
   - Single environment to manage

🔄 Workflow:
   1. Make framework changes in mcp_mesh/
   2. Test with agent: cd examples/complex/data_processor_agent && python -m data_processor_agent
   3. Make agent changes in data_processor_agent/
   4. Test agent functionality
   5. Iterate quickly without reinstalls

EOF
}

# Clean up environment
cleanup_environment() {
    local project_root="$1"
    
    log_info "Cleaning up development environment..."
    
    if [[ -d "$project_root/.venv" ]]; then
        log_warning "This will remove the shared .venv directory"
        read -p "Are you sure? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$project_root/.venv"
            log_success "Removed .venv directory"
        else
            log_info "Cleanup cancelled"
        fi
    else
        log_info "No .venv directory found"
    fi
}

# Show current status
show_status() {
    local project_root="$1"
    
    log_info "MCP Mesh Development Environment Status"
    
    # Check if .venv exists
    if [[ -d "$project_root/.venv" ]]; then
        log_success "Shared .venv exists at $project_root/.venv"
        
        # Check if activated
        if [[ "$VIRTUAL_ENV" == "$project_root/.venv" ]]; then
            log_success "Virtual environment is activated"
        else
            log_warning "Virtual environment not activated"
            echo "  Run: source $project_root/.venv/bin/activate"
        fi
        
        # Check installations
        if [[ -n "$VIRTUAL_ENV" ]]; then
            log_info "Checking package installations..."
            
            # Check mcp-mesh
            if pip show mcp-mesh >/dev/null 2>&1; then
                local mcp_location=$(pip show mcp-mesh | grep Location | cut -d' ' -f2)
                if [[ "$mcp_location" == "$project_root" ]]; then
                    log_success "mcp-mesh: Editable install from $project_root"
                else
                    log_warning "mcp-mesh: Installed from $mcp_location (not editable)"
                fi
            else
                log_error "mcp-mesh: Not installed"
            fi
            
            # Check agent
            if pip show mcp-mesh-data-processor-agent >/dev/null 2>&1; then
                local agent_location=$(pip show mcp-mesh-data-processor-agent | grep Location | cut -d' ' -f2-)
                if [[ "$agent_location" == *"examples/complex/data_processor_agent"* ]]; then
                    log_success "data-processor-agent: Editable install"
                else
                    log_warning "data-processor-agent: Regular install"
                fi
            else
                log_error "data-processor-agent: Not installed"
            fi
        fi
    else
        log_error "No shared .venv found at $project_root/.venv"
    fi
}

# Show help
show_help() {
    cat << EOF
MCP Mesh Multi-File Agent Development Setup

This script helps set up a shared development environment for simultaneous
MCP Mesh framework and agent development.

Usage: $0 <command>

Commands:
  setup     Set up development environment with shared .venv
  status    Show current environment status
  cleanup   Remove shared .venv (be careful!)
  help      Show this help message

Environment Setup:
  - Creates/uses shared .venv in mcp-mesh project root
  - Installs mcp-mesh in editable mode (framework development)
  - Installs agent in editable mode (agent development)
  - Both packages share dependencies and environment

Workflow:
  1. Run: $0 setup
  2. Activate: source <project-root>/.venv/bin/activate
  3. Work on framework: cd <project-root> && edit mcp_mesh/
  4. Work on agent: cd examples/complex/data_processor_agent && edit data_processor_agent/
  5. Test changes immediately without reinstalls

Benefits:
  ✅ Single environment to manage
  ✅ Framework changes immediately available to agents
  ✅ Agent changes immediately testable
  ✅ Consistent dependency versions
  ✅ Fast iteration cycle

EOF
}

# Main command dispatcher
main() {
    local project_root
    project_root=$(detect_project_root)
    
    case "${1:-setup}" in
        setup)
            setup_dev_environment "$project_root"
            ;;
        status)
            show_status "$project_root"
            ;;
        cleanup)
            cleanup_environment "$project_root"
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
}

# Run main function
main "$@"