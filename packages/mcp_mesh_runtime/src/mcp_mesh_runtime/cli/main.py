"""Main CLI entry point for MCP Mesh Developer CLI."""

import argparse
import asyncio
import sys
import time

from .agent_manager import AgentManager
from .config import cli_config_manager
from .registry_manager import RegistryManager
from .signal_handler import (
    get_cleanup_manager,
    install_signal_handlers,
    register_cleanup_handler,
)
from .status import get_status_display


def _convert_config_value(key: str, value: str):
    """Convert string value to appropriate type for configuration key."""
    # Define type mappings for configuration keys
    int_keys = {
        "registry_port",
        "health_check_interval",
        "startup_timeout",
        "shutdown_timeout",
    }
    bool_keys = {"auto_restart", "watch_files", "debug_mode", "enable_background"}
    str_keys = {"registry_host", "db_path", "log_level", "pid_file"}

    try:
        if key in int_keys:
            return int(value)
        elif key in bool_keys:
            return value.lower() in ("true", "1", "yes", "on")
        elif key in str_keys:
            return value
        else:
            # Unknown key, let validation handle it
            return value
    except ValueError:
        return None


def cmd_start(args: argparse.Namespace) -> int:
    """Start MCP Mesh services."""
    try:
        # Load configuration with CLI overrides
        config = cli_config_manager.load_config(override_args=vars(args))
        status_display = get_status_display()

        # Determine startup mode
        registry_only = args.registry_only or (not args.agents)
        background_mode = getattr(args, "background", False)

        startup_info = {
            "Registry": f"{config.registry_host}:{config.registry_port}",
            "Database": config.db_path,
            "Log Level": config.log_level,
            "Mode": (
                "Registry-only"
                if registry_only
                else f"Registry + {len(args.agents)} agent(s)"
            ),
        }

        if background_mode:
            startup_info["Background"] = "Yes"

        print(
            status_display.show_info(
                "Starting MCP Mesh services with configuration:", startup_info
            )
        )

        if args.agents:
            print(status_display.show_info(f"Agent files: {', '.join(args.agents)}"))

        # Create managers
        registry_manager = RegistryManager(config)
        agent_manager = AgentManager(config, registry_manager)

        async def start_services():
            """Async function to start registry and agents."""
            try:
                # Ensure registry is running
                print(status_display.show_info("Starting registry service..."))
                registry_ready = await agent_manager.ensure_registry_running()
                if not registry_ready:
                    raise RuntimeError("Failed to start or connect to registry")

                # Get registry process info for display
                registry_process = registry_manager.process_tracker.get_process(
                    "registry"
                )
                if registry_process:
                    print(
                        status_display.show_success(
                            "Registry service ready",
                            {
                                "PID": registry_process.pid,
                                "Host": registry_process.metadata.get("host"),
                                "Port": registry_process.metadata.get("port"),
                                "URL": registry_process.metadata.get("url"),
                            },
                        )
                    )

                # Registry-only mode
                if registry_only:
                    print(
                        status_display.show_success(
                            "Registry-only mode: Ready for agent connections"
                        )
                    )
                    return True

                # Start agent processes if specified
                if args.agents:
                    print(
                        status_display.show_info(
                            f"Starting {len(args.agents)} agent(s)..."
                        )
                    )

                    agent_results = agent_manager.start_multiple_agents(args.agents)

                    if not agent_results:
                        print(
                            status_display.show_warning(
                                "No agents were started successfully"
                            )
                        )
                        return False

                    # Display agent startup results
                    for agent_name, process_info in agent_results.items():
                        print(
                            status_display.show_success(
                                f"Agent {agent_name} started",
                                {
                                    "PID": process_info.pid,
                                    "File": process_info.metadata.get("agent_file"),
                                    "Registry": process_info.metadata.get(
                                        "registry_url"
                                    ),
                                },
                            )
                        )

                    print(
                        status_display.show_success(
                            f"All {len(agent_results)} agent(s) started successfully"
                        )
                    )

                return True

            except Exception as e:
                print(status_display.show_error(f"Failed to start services: {e}"))
                # Only close on error - keep services running on success
                await registry_manager.close()
                await agent_manager.close()
                return False

        # Run the async startup process
        success = asyncio.run(start_services())

        if not success:
            return 1

        if not background_mode:
            print()
            print(
                status_display.show_info(
                    "Services started successfully. Use these commands:"
                )
            )
            print("  mcp_mesh_dev status    # Check service health")
            print("  mcp_mesh_dev list      # Show running agents")
            print("  mcp_mesh_dev logs      # View logs")
            print("  mcp_mesh_dev stop      # Stop all services")
            print()
            print(status_display.show_info("Press Ctrl+C to stop all services"))

            # Keep the CLI running until interrupted
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n" + status_display.show_info("Stopping services..."))
                # Graceful shutdown will be handled by signal handlers
                return 0

        return 0

    except Exception as e:
        print(f"Failed to start services: {e}", file=sys.stderr)
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop MCP Mesh services."""
    try:
        config = cli_config_manager.get_config()
        status_display = get_status_display()
        registry_manager = RegistryManager(config)
        agent_manager = AgentManager(config, registry_manager)

        # Determine stop mode
        force_mode = getattr(args, "force", False)
        specific_agent = getattr(args, "agent", None)
        timeout = getattr(args, "timeout", 30)

        if specific_agent:
            # Stop specific agent only
            print(status_display.show_info(f"Stopping agent: {specific_agent}"))

            # Check if agent exists
            process_info = agent_manager.process_tracker.get_process(specific_agent)
            if not process_info:
                print(
                    status_display.show_error(
                        f"Agent '{specific_agent}' not found or not running"
                    )
                )
                return 1

            # Stop the specific agent
            success = agent_manager.stop_agent(specific_agent, timeout=timeout)

            if success:
                print(
                    status_display.show_success(
                        f"Agent {specific_agent} stopped successfully"
                    )
                )
                return 0
            else:
                print(
                    status_display.show_error(f"Failed to stop agent {specific_agent}")
                )
                return 1

        else:
            # Stop all services
            stop_mode = "force" if force_mode else "graceful"
            print(
                status_display.show_info(
                    f"Stopping all MCP Mesh services ({stop_mode} mode)..."
                )
            )

            total_stopped = 0
            total_errors = 0

            # Stop all agent processes first
            agent_results = agent_manager.stop_all_agents(timeout=timeout)

            if agent_results:
                print(
                    status_display.show_info(
                        f"Stopping {len(agent_results)} agent(s)..."
                    )
                )
                for agent_name, success in agent_results.items():
                    if success:
                        print(
                            status_display.show_success(
                                f"Agent {agent_name} stopped successfully"
                            )
                        )
                        total_stopped += 1
                    else:
                        print(
                            status_display.show_warning(
                                f"Agent {agent_name} may not have stopped cleanly"
                            )
                        )
                        total_errors += 1

            # Stop registry service
            print(status_display.show_info("Stopping registry service..."))
            registry_success = registry_manager.stop_registry_service(timeout=timeout)

            if registry_success:
                print(
                    status_display.show_success("Registry service stopped successfully")
                )
                total_stopped += 1
            else:
                print(
                    status_display.show_warning(
                        "Registry service may not have stopped cleanly"
                    )
                )
                total_errors += 1

            # Summary
            print()
            if total_errors == 0:
                print(
                    status_display.show_success(
                        f"All services stopped successfully ({total_stopped} total)"
                    )
                )
                return 0
            elif total_stopped > 0:
                print(
                    status_display.show_warning(
                        f"Partial success: {total_stopped} stopped, {total_errors} had issues"
                    )
                )
                return 1
            else:
                print(status_display.show_error("Failed to stop services cleanly"))
                return 1

    except Exception as e:
        print(f"Failed to stop services: {e}", file=sys.stderr)
        return 1


def cmd_restart_agent(args: argparse.Namespace) -> int:
    """Restart a specific MCP Mesh agent."""
    try:
        config = cli_config_manager.get_config()
        status_display = get_status_display()
        registry_manager = RegistryManager(config)
        agent_manager = AgentManager(config, registry_manager)

        print(status_display.show_info(f"Restarting agent: {args.agent_name}"))

        async def restart_agent():
            """Async function to restart the agent."""
            try:
                # Check if agent exists
                process_info = agent_manager.process_tracker.get_process(
                    args.agent_name
                )
                if not process_info:
                    print(
                        status_display.show_error(
                            f"Agent '{args.agent_name}' not found"
                        )
                    )
                    return False

                # Show current status
                print(
                    status_display.show_info(
                        "Current agent status:",
                        {
                            "PID": process_info.pid,
                            "Status": (
                                "running"
                                if agent_manager.process_tracker._is_process_running(
                                    process_info.pid
                                )
                                else "stopped"
                            ),
                            "File": process_info.metadata.get("agent_file"),
                            "Uptime": f"{process_info.get_uptime().total_seconds():.1f}s",
                        },
                    )
                )

                # Restart agent with registration wait
                success = await agent_manager.restart_agent_with_registration_wait(
                    args.agent_name, timeout=args.timeout
                )

                if success:
                    # Get new process info
                    new_process = agent_manager.process_tracker.get_process(
                        args.agent_name
                    )
                    print(
                        status_display.show_success(
                            f"Agent {args.agent_name} restarted successfully",
                            {
                                "New PID": new_process.pid,
                                "Status": "running and registered",
                                "File": new_process.metadata.get("agent_file"),
                            },
                        )
                    )
                    return True
                else:
                    print(
                        status_display.show_warning(
                            f"Agent {args.agent_name} restarted but may not be fully ready"
                        )
                    )
                    return False

            except Exception as e:
                print(
                    status_display.show_error(
                        f"Failed to restart agent {args.agent_name}: {e}"
                    )
                )
                return False
            finally:
                await registry_manager.close()
                await agent_manager.close()

        # Run the async restart process
        success = asyncio.run(restart_agent())
        return 0 if success else 1

    except Exception as e:
        print(f"Failed to restart agent: {e}", file=sys.stderr)
        return 1


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart MCP Mesh registry service."""
    try:
        config = cli_config_manager.get_config()
        status_display = get_status_display()
        registry_manager = RegistryManager(config)

        print(status_display.show_info("Restarting MCP Mesh registry service..."))

        # Restart registry service
        try:
            process_info = registry_manager.restart_registry_service(
                timeout=args.timeout, preserve_config=not args.reset_config
            )

            print(
                status_display.show_success(
                    "Registry service restarted successfully",
                    {
                        "PID": process_info.pid,
                        "Host": process_info.metadata.get("host"),
                        "Port": process_info.metadata.get("port"),
                        "URL": process_info.metadata.get("url"),
                    },
                )
            )

            # Wait for registry to be ready
            async def wait_for_ready():
                return await registry_manager.wait_for_registry_ready(
                    timeout=config.startup_timeout
                )

            is_ready = asyncio.run(wait_for_ready())
            if not is_ready:
                print(
                    status_display.show_warning(
                        "Registry service restarted but may not be fully ready"
                    )
                )

            return 0

        except Exception as e:
            print(status_display.show_error(f"Failed to restart registry service: {e}"))
            return 1
        finally:
            asyncio.run(registry_manager.close())

    except Exception as e:
        print(f"Failed to restart services: {e}", file=sys.stderr)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Show status of MCP Mesh services."""
    try:
        config = cli_config_manager.get_config()
        status_display = get_status_display()
        registry_manager = RegistryManager(config)
        agent_manager = AgentManager(config, registry_manager)

        print(status_display.show_info("Checking MCP Mesh services status..."))

        async def get_detailed_status():
            """Get comprehensive status of all services."""
            registry_status = await registry_manager.get_registry_status_async()
            agents_status = await agent_manager.get_all_agents_status()
            return registry_status, agents_status

        registry_status, agents_status = asyncio.run(get_detailed_status())

        # Format and display status
        if args.json:
            import json

            status_data = {
                "registry": registry_status,
                "agents": agents_status,
                "system": {
                    "total_agents": len(agents_status),
                    "running_agents": sum(
                        1
                        for status in agents_status.values()
                        if status.get("status") == "running"
                    ),
                    "registered_agents": sum(
                        1
                        for status in agents_status.values()
                        if status.get("registered", False)
                    ),
                    "healthy_agents": sum(
                        1
                        for status in agents_status.values()
                        if status.get("health") == "healthy"
                    ),
                },
            }
            print(json.dumps(status_data, indent=2))
        else:
            # Display overall system health
            total_agents = len(agents_status)
            running_agents = sum(
                1
                for status in agents_status.values()
                if status.get("status") == "running"
            )
            registered_agents = sum(
                1
                for status in agents_status.values()
                if status.get("registered", False)
            )
            healthy_agents = sum(
                1
                for status in agents_status.values()
                if status.get("health") == "healthy"
            )

            # Determine overall system health
            registry_healthy = registry_status.get("status") == "running"
            all_agents_healthy = total_agents == 0 or (
                running_agents == total_agents and registered_agents == total_agents
            )

            overall_status = (
                "healthy" if registry_healthy and all_agents_healthy else "degraded"
            )
            overall_status_type = (
                "success" if overall_status == "healthy" else "warning"
            )

            print()
            print(
                getattr(status_display, f"show_{overall_status_type}")(
                    f"MCP Mesh System Status: {overall_status.upper()}",
                    {
                        "Registry": "Running" if registry_healthy else "Issues",
                        "Total Agents": total_agents,
                        "Running": running_agents,
                        "Registered": registered_agents,
                        "Healthy": healthy_agents,
                    },
                )
            )

            print()

            # Registry service status with enhanced details
            registry_process = registry_manager.process_tracker.get_process("registry")
            registry_details = dict(registry_status)

            if registry_process:
                registry_details.update(
                    {
                        "PID": registry_process.pid,
                        "Uptime": f"{registry_process.get_uptime().total_seconds():.1f}s",
                        "Started": registry_process.start_time.strftime("%H:%M:%S"),
                    }
                )

            registry_status_type = "success" if registry_healthy else "error"
            print(
                getattr(status_display, f"show_{registry_status_type}")(
                    "Registry Service", registry_details
                )
            )

            # Agent status with enhanced formatting
            if agents_status:
                print()
                print(
                    status_display.show_info(f"Agent Processes ({total_agents} total):")
                )

                for agent_name, agent_status in agents_status.items():
                    # Determine status color and type
                    is_running = agent_status.get("status") == "running"
                    is_registered = agent_status.get("registered", False)
                    is_healthy = agent_status.get("health") == "healthy"

                    if is_running and is_registered and is_healthy:
                        status_type = "success"
                        status_text = "Healthy & Running"
                    elif is_running and is_registered:
                        status_type = "warning"
                        status_text = "Running (Health Unknown)"
                    elif is_running:
                        status_type = "warning"
                        status_text = "Running (Unregistered)"
                    else:
                        status_type = "error"
                        status_text = "Stopped"

                    agent_details = {
                        "Status": status_text,
                        "PID": agent_status.get("pid", "N/A"),
                        "Health": agent_status.get("health", "unknown"),
                        "Registered": "Yes" if is_registered else "No",
                    }

                    uptime = agent_status.get("uptime", 0)
                    if uptime > 0:
                        agent_details["Uptime"] = f"{uptime:.1f}s"

                    # Add file path if available
                    if "file" in agent_status:
                        agent_details["File"] = agent_status["file"]

                    print(
                        getattr(status_display, f"show_{status_type}")(
                            f"Agent: {agent_name}", agent_details
                        )
                    )
            else:
                print()
                print(status_display.show_info("No agent processes running"))

            # Performance metrics if verbose
            if args.verbose:
                print()
                print(status_display.show_info("Performance Metrics:"))

                # Process table
                from .process_tracker import get_process_tracker

                process_tracker = get_process_tracker()
                all_processes = process_tracker.get_all_processes()

                if all_processes:
                    print(status_display.show_all_processes())

                    # Memory and CPU usage summary (if available)
                    try:
                        import psutil

                        total_memory = 0
                        total_cpu = 0
                        active_processes = 0

                        for process_info in all_processes.values():
                            if process_tracker._is_process_running(process_info.pid):
                                try:
                                    proc = psutil.Process(process_info.pid)
                                    memory_info = proc.memory_info()
                                    cpu_percent = proc.cpu_percent()

                                    total_memory += memory_info.rss
                                    total_cpu += cpu_percent
                                    active_processes += 1
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    pass

                        if active_processes > 0:
                            print()
                            print(
                                status_display.show_info(
                                    "Resource Usage:",
                                    {
                                        "Active Processes": active_processes,
                                        "Total Memory": f"{total_memory / (1024**2):.1f} MB",
                                        "Average CPU": f"{total_cpu / active_processes:.1f}%",
                                    },
                                )
                            )

                    except ImportError:
                        print(
                            status_display.show_info(
                                "Install 'psutil' for detailed resource metrics"
                            )
                        )
                else:
                    print(status_display.show_info("No processes being tracked"))

        asyncio.run(registry_manager.close())
        asyncio.run(agent_manager.close())
        return 0

    except Exception as e:
        print(f"Failed to get status: {e}", file=sys.stderr)
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """List available MCP Mesh agents and services."""
    try:
        config = cli_config_manager.get_config()
        status_display = get_status_display()
        registry_manager = RegistryManager(config)
        agent_manager = AgentManager(config, registry_manager)

        async def get_agents_info():
            """Get comprehensive agent information from registry and process tracker."""
            try:
                # Get all agents from registry
                registry_client = agent_manager._get_registry_client()
                registry_agents = await registry_client.get_all_agents()

                # Get all tracked processes
                agent_processes = {
                    name: process
                    for name, process in agent_manager.process_tracker.get_all_processes().items()
                    if process.service_type == "agent"
                }

                # Combine registry and process information
                agent_info = {}

                # Add registry agents
                for agent in registry_agents:
                    agent_id = agent.get("agent_id") or agent.get("name")
                    if agent_id:
                        agent_info[agent_id] = {
                            "name": agent.get("name", agent_id),
                            "status": "registered",
                            "registered": True,
                            "health": agent.get("health_status", "unknown"),
                            "capabilities": agent.get("capabilities", []),
                            "dependencies": agent.get("dependencies", []),
                            "endpoint": agent.get("endpoint"),
                            "last_seen": agent.get("last_seen"),
                            "uptime": "unknown",
                            "pid": None,
                            "process_status": "unknown",
                        }

                # Add process information
                for agent_name, process_info in agent_processes.items():
                    if agent_name in agent_info:
                        # Update existing entry with process info
                        agent_info[agent_name].update(
                            {
                                "pid": process_info.pid,
                                "process_status": (
                                    "running"
                                    if agent_manager.process_tracker._is_process_running(
                                        process_info.pid
                                    )
                                    else "stopped"
                                ),
                                "uptime": f"{process_info.get_uptime().total_seconds():.1f}s",
                                "agent_file": process_info.metadata.get("agent_file"),
                                "working_directory": process_info.metadata.get(
                                    "working_directory"
                                ),
                            }
                        )
                    else:
                        # Process exists but not registered
                        agent_info[agent_name] = {
                            "name": agent_name,
                            "status": "running_unregistered",
                            "registered": False,
                            "health": "unknown",
                            "capabilities": [],
                            "dependencies": [],
                            "endpoint": None,
                            "last_seen": None,
                            "uptime": f"{process_info.get_uptime().total_seconds():.1f}s",
                            "pid": process_info.pid,
                            "process_status": (
                                "running"
                                if agent_manager.process_tracker._is_process_running(
                                    process_info.pid
                                )
                                else "stopped"
                            ),
                            "agent_file": process_info.metadata.get("agent_file"),
                            "working_directory": process_info.metadata.get(
                                "working_directory"
                            ),
                        }

                return agent_info

            except Exception:
                # Fallback to process tracker only
                agent_processes = {
                    name: process
                    for name, process in agent_manager.process_tracker.get_all_processes().items()
                    if process.service_type == "agent"
                }

                agent_info = {}
                for agent_name, process_info in agent_processes.items():
                    agent_info[agent_name] = {
                        "name": agent_name,
                        "status": "process_only",
                        "registered": False,
                        "health": "unknown",
                        "capabilities": [],
                        "dependencies": [],
                        "endpoint": None,
                        "last_seen": None,
                        "uptime": f"{process_info.get_uptime().total_seconds():.1f}s",
                        "pid": process_info.pid,
                        "process_status": (
                            "running"
                            if agent_manager.process_tracker._is_process_running(
                                process_info.pid
                            )
                            else "stopped"
                        ),
                        "agent_file": process_info.metadata.get("agent_file"),
                        "working_directory": process_info.metadata.get(
                            "working_directory"
                        ),
                    }

                return agent_info

        # Get agent information
        agents_info = asyncio.run(get_agents_info())

        # Apply filters
        if args.filter:
            import re

            pattern = re.compile(args.filter, re.IGNORECASE)
            agents_info = {
                name: info
                for name, info in agents_info.items()
                if pattern.search(name) or pattern.search(info.get("status", ""))
            }

        # Filter by type if specified
        if args.agents and not args.services:
            # Show only agents (default behavior - all entries are agents)
            pass
        elif args.services and not args.agents:
            # Show only services (for future service discovery)
            agents_info = {}

        # Format and display output
        if args.json:
            import json

            print(json.dumps(agents_info, indent=2))
        else:
            if not agents_info:
                print(status_display.show_info("No agents found"))
                print()
                print(status_display.show_info("To start an agent:"))
                print("  mcp_mesh_dev start my_agent.py")
                print("  mcp_mesh_dev start --registry-only  # Registry only")
            else:
                # Summary statistics
                total_agents = len(agents_info)
                running_agents = sum(
                    1
                    for info in agents_info.values()
                    if info["process_status"] == "running"
                )
                registered_agents = sum(
                    1 for info in agents_info.values() if info["registered"]
                )
                healthy_agents = sum(
                    1 for info in agents_info.values() if info["health"] == "healthy"
                )

                print(
                    status_display.show_info(
                        f"MCP Mesh Agents Summary ({total_agents} total):",
                        {
                            "Running": f"{running_agents}/{total_agents}",
                            "Registered": f"{registered_agents}/{total_agents}",
                            "Healthy": f"{healthy_agents}/{total_agents}",
                        },
                    )
                )
                print()

                # Sort agents by status for better display (running first)
                sorted_agents = sorted(
                    agents_info.items(),
                    key=lambda x: (
                        0
                        if x[1]["process_status"] == "running" and x[1]["registered"]
                        else (
                            1
                            if x[1]["process_status"] == "running"
                            else 2 if x[1]["registered"] else 3
                        )
                    ),
                )

                for agent_name, info in sorted_agents:
                    # Determine status color and text
                    if info["process_status"] == "running" and info["registered"]:
                        status_type = "success"
                        status_text = "🟢 Running & Registered"
                    elif info["process_status"] == "running":
                        status_type = "warning"
                        status_text = "🟡 Running (Unregistered)"
                    elif info["registered"]:
                        status_type = "warning"
                        status_text = "🟡 Registered (Process Unknown)"
                    else:
                        status_type = "error"
                        status_text = "🔴 Stopped"

                    # Build agent details
                    agent_details = {
                        "Status": status_text,
                        "Health": (
                            info["health"].title()
                            if info["health"] != "unknown"
                            else "Unknown"
                        ),
                    }

                    # Add process information
                    if info["pid"]:
                        agent_details["PID"] = info["pid"]
                    if info["uptime"] != "unknown":
                        # Format uptime more nicely
                        try:
                            uptime_seconds = float(info["uptime"].replace("s", ""))
                            if uptime_seconds < 60:
                                agent_details["Uptime"] = f"{uptime_seconds:.1f}s"
                            elif uptime_seconds < 3600:
                                agent_details["Uptime"] = f"{uptime_seconds/60:.1f}m"
                            else:
                                agent_details["Uptime"] = f"{uptime_seconds/3600:.1f}h"
                        except (ValueError, AttributeError):
                            agent_details["Uptime"] = info["uptime"]

                    # Add file and capability information
                    if info["agent_file"]:
                        agent_details["File"] = info["agent_file"]
                    if info["endpoint"]:
                        agent_details["Endpoint"] = info["endpoint"]
                    if info["capabilities"]:
                        cap_count = len(info["capabilities"])
                        agent_details["Capabilities"] = f"{cap_count} available"
                    if info["dependencies"]:
                        dep_count = len(info["dependencies"])
                        agent_details["Dependencies"] = f"{dep_count} required"

                    print(
                        getattr(status_display, f"show_{status_type}")(
                            f"Agent: {agent_name}", agent_details
                        )
                    )

                print()

                # Helpful commands
                if any(
                    info["process_status"] != "running" for info in agents_info.values()
                ):
                    print(status_display.show_info("Quick actions:"))
                    print("  mcp_mesh_dev start <agent.py>      # Start stopped agent")
                    print(
                        "  mcp_mesh_dev restart-agent <name>  # Restart specific agent"
                    )

                print(
                    "  mcp_mesh_dev status                 # Detailed health information"
                )
                print("  mcp_mesh_dev logs --agent <name>    # View agent logs")

                # Export option
                if args.json is False:  # Only if not already in JSON mode
                    print("  mcp_mesh_dev list --json           # Export as JSON")

        asyncio.run(registry_manager.close())
        asyncio.run(agent_manager.close())
        return 0

    except Exception as e:
        print(f"Failed to list agents: {e}", file=sys.stderr)
        return 1


def cmd_logs(args: argparse.Namespace) -> int:
    """Show logs for MCP Mesh services."""
    try:
        config = cli_config_manager.get_config()
        status_display = get_status_display()
        registry_manager = RegistryManager(config)
        agent_manager = AgentManager(config, registry_manager)

        import tempfile
        from pathlib import Path

        # Check if specific agent requested
        if args.agent:
            # Get agent process info
            process_info = agent_manager.process_tracker.get_process(args.agent)
            if not process_info:
                print(
                    status_display.show_error(
                        f"Agent '{args.agent}' not found or not running"
                    )
                )
                return 1

            print(status_display.show_info(f"Showing logs for agent: {args.agent}"))

            # For MCP agents, we can check their stdout/stderr if captured
            # In a real implementation, agents might log to files or system logger

            # Try to get log data from process (this is a simplified approach)
            log_lines = []

            # Check if agent has a log file (common pattern)
            possible_log_paths = [
                Path(process_info.metadata.get("working_directory", "."))
                / f"{args.agent}.log",
                Path(tempfile.gettempdir()) / f"mcp_mesh_{args.agent}.log",
                Path(config.db_path).parent / "logs" / f"{args.agent}.log",
            ]

            log_file_found = False
            for log_path in possible_log_paths:
                if log_path.exists():
                    try:
                        with open(log_path) as f:
                            lines = f.readlines()
                            if args.lines:
                                lines = lines[-args.lines :]
                            log_lines.extend([line.strip() for line in lines])
                        log_file_found = True
                        print(
                            status_display.show_success(
                                f"Reading from log file: {log_path}"
                            )
                        )
                        break
                    except Exception as e:
                        print(
                            status_display.show_warning(
                                f"Failed to read log file {log_path}: {e}"
                            )
                        )

            if not log_file_found:
                # Fallback: show process information and suggest logging setup
                print(status_display.show_warning("No log file found for agent"))
                print(
                    status_display.show_info(
                        "Agent Process Information:",
                        {
                            "PID": process_info.pid,
                            "Command": " ".join(process_info.command),
                            "Working Dir": process_info.metadata.get(
                                "working_directory"
                            ),
                            "Started": process_info.start_time.strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "Uptime": f"{process_info.get_uptime().total_seconds():.1f}s",
                        },
                    )
                )

                # Show recent system logs for the process (if available)
                try:
                    import subprocess

                    # Try to get recent logs from journalctl (Linux) or system logs
                    result = subprocess.run(
                        [
                            "journalctl",
                            "--user",
                            "--since",
                            "1 hour ago",
                            "--grep",
                            str(process_info.pid),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

                    if result.returncode == 0 and result.stdout.strip():
                        print(status_display.show_info("Recent system logs:"))
                        for line in result.stdout.strip().split("\n")[-args.lines :]:
                            print(f"  {line}")
                    else:
                        print(status_display.show_info("No recent system logs found"))
                        print(
                            status_display.show_info(
                                "Consider configuring logging in your agent"
                            )
                        )

                except Exception:
                    print(status_display.show_info("System log access not available"))
                    print(
                        status_display.show_info(
                            "Consider configuring file-based logging in your agent"
                        )
                    )

            # Display collected logs
            if log_lines:
                print()

                # Apply log level filtering and colorize
                filtered_lines = []
                level_colors = {
                    "DEBUG": "info",
                    "INFO": "info",
                    "WARNING": "warning",
                    "ERROR": "error",
                    "CRITICAL": "critical",
                }

                for line in log_lines:
                    line_upper = line.upper()

                    # Determine if line should be included based on level filter
                    should_include = True
                    if args.level == "INFO" and "DEBUG" in line_upper:
                        should_include = False
                    elif args.level == "WARNING" and any(
                        level in line_upper for level in ["DEBUG", "INFO"]
                    ):
                        should_include = False
                    elif args.level == "ERROR" and any(
                        level in line_upper for level in ["DEBUG", "INFO", "WARNING"]
                    ):
                        should_include = False

                    if should_include:
                        # Try to colorize based on log level
                        colorized_line = line
                        for level, _color in level_colors.items():
                            if level in line_upper:
                                # Add some basic formatting for log levels
                                colorized_line = line.replace(level, f"[{level}]")
                                break

                        filtered_lines.append(colorized_line)

                if filtered_lines:
                    print(
                        status_display.show_info(
                            f"Showing {len(filtered_lines)} log entries (level: {args.level}):"
                        )
                    )
                    print()

                    for line in filtered_lines:
                        # Add timestamp coloring if present
                        if any(
                            char.isdigit() for char in line[:20]
                        ):  # Likely has timestamp
                            print(f"  {line}")
                        else:
                            print(f"  {line}")
                else:
                    print(
                        status_display.show_info(
                            f"No log entries found matching level: {args.level}"
                        )
                    )

                if args.follow:
                    print()
                    print(
                        status_display.show_info("Following logs (Ctrl+C to stop)...")
                    )

                    # Enhanced follow implementation with basic file watching
                    if log_file_found:
                        try:
                            import time

                            # Find the actual log file that was read
                            actual_log_file = None
                            for log_path in possible_log_paths:
                                if log_path.exists():
                                    actual_log_file = log_path
                                    break

                            if actual_log_file:
                                print(
                                    status_display.show_success(
                                        f"Monitoring: {actual_log_file}"
                                    )
                                )
                                print()

                                # Simple file following (seek to end and read new lines)
                                with open(actual_log_file) as f:
                                    f.seek(0, 2)  # Seek to end

                                    while True:
                                        line = f.readline()
                                        if line:
                                            # Apply same filtering
                                            line_upper = line.upper()
                                            should_include = True
                                            if (
                                                args.level == "INFO"
                                                and "DEBUG" in line_upper
                                            ):
                                                should_include = False
                                            elif args.level == "WARNING" and any(
                                                level in line_upper
                                                for level in ["DEBUG", "INFO"]
                                            ):
                                                should_include = False
                                            elif args.level == "ERROR" and any(
                                                level in line_upper
                                                for level in [
                                                    "DEBUG",
                                                    "INFO",
                                                    "WARNING",
                                                ]
                                            ):
                                                should_include = False

                                            if should_include:
                                                print(f"  {line.strip()}")
                                        else:
                                            time.sleep(0.1)  # Brief pause
                            else:
                                print(
                                    status_display.show_warning(
                                        "Log file not available for following"
                                    )
                                )

                        except KeyboardInterrupt:
                            print(
                                "\n" + status_display.show_info("Log following stopped")
                            )
                        except Exception as e:
                            print(
                                status_display.show_warning(
                                    f"Log following failed: {e}"
                                )
                            )
                    else:
                        print(
                            status_display.show_warning(
                                "Log following requires a log file"
                            )
                        )
                        print(
                            status_display.show_info(
                                "Configure file-based logging in your agent to enable this feature"
                            )
                        )

        else:
            # Show logs for all services
            print(status_display.show_info("Showing logs for all MCP Mesh services"))

            # Registry logs
            registry_process = agent_manager.process_tracker.get_process("registry")
            if registry_process:
                print()
                print(
                    status_display.show_info(
                        "Registry Service:",
                        {
                            "PID": registry_process.pid,
                            "Status": (
                                "running"
                                if agent_manager.process_tracker._is_process_running(
                                    registry_process.pid
                                )
                                else "stopped"
                            ),
                            "Uptime": f"{registry_process.get_uptime().total_seconds():.1f}s",
                        },
                    )
                )

            # Agent logs summary
            agent_processes = {
                name: process
                for name, process in agent_manager.process_tracker.get_all_processes().items()
                if process.service_type == "agent"
            }

            if agent_processes:
                print()
                print(
                    status_display.show_info(
                        f"Found {len(agent_processes)} agent process(es):"
                    )
                )
                for agent_name, process_info in agent_processes.items():
                    status = (
                        "running"
                        if agent_manager.process_tracker._is_process_running(
                            process_info.pid
                        )
                        else "stopped"
                    )
                    status_type = "success" if status == "running" else "warning"

                    print(
                        getattr(status_display, f"show_{status_type}")(
                            f"Agent: {agent_name}",
                            {
                                "PID": process_info.pid,
                                "Status": status,
                                "Uptime": f"{process_info.get_uptime().total_seconds():.1f}s",
                                "File": process_info.metadata.get(
                                    "agent_file", "unknown"
                                ),
                            },
                        )
                    )

                print()
                print(
                    status_display.show_info(
                        "Use 'mcp_mesh_dev logs --agent <name>' to view specific agent logs"
                    )
                )
            else:
                print()
                print(status_display.show_info("No agent processes currently running"))

        asyncio.run(registry_manager.close())
        asyncio.run(agent_manager.close())
        return 0

    except KeyboardInterrupt:
        print("\nLog monitoring stopped by user")
        return 0
    except Exception as e:
        print(f"Failed to show logs: {e}", file=sys.stderr)
        return 1


def cmd_config(args: argparse.Namespace) -> int:
    """Manage CLI configuration."""
    try:
        if args.config_action == "show":
            config = cli_config_manager.get_config()
            output_format = getattr(args, "format", "yaml")
            print(cli_config_manager.show_config(format=output_format))

        elif args.config_action == "reset":
            cli_config_manager.reset_to_defaults()
            config = cli_config_manager.get_config()
            cli_config_manager.save_config(config)
            print("Configuration reset to defaults")

        elif args.config_action == "set":
            if not hasattr(args, "key") or not hasattr(args, "value"):
                print(
                    "Error: key and value are required for 'set' action",
                    file=sys.stderr,
                )
                return 1

            # Convert value to appropriate type based on key
            converted_value = _convert_config_value(args.key, args.value)
            if converted_value is None:
                print(
                    f"Error: Invalid value '{args.value}' for key '{args.key}'",
                    file=sys.stderr,
                )
                return 1

            # Update configuration
            cli_config_manager.update_config(**{args.key: converted_value})
            config = cli_config_manager.get_config()
            cli_config_manager.save_config(config)
            print(f"Set {args.key} = {converted_value}")

        elif args.config_action == "path":
            print(f"Configuration file: {cli_config_manager.config_path}")

        elif args.config_action == "save":
            # Save current runtime configuration as defaults
            config = cli_config_manager.get_config()
            cli_config_manager.save_config(config)
            print(f"Current configuration saved to {cli_config_manager.config_path}")

        return 0

    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""

    # Global help text with examples and common workflows
    description = """MCP Mesh Developer CLI - Development and debugging tools for MCP Mesh

The MCP Mesh Developer CLI provides tools for managing MCP (Model Context Protocol)
agents and services in a mesh architecture. Use it to start agents, monitor services,
and debug your MCP integrations.

Examples:
  mcp_mesh_dev start                        Start registry only
  mcp_mesh_dev start intent_agent.py       Start registry + intent agent
  mcp_mesh_dev start --registry-port 8081  Start with custom registry port
  mcp_mesh_dev list                         Show running agents and services
  mcp_mesh_dev status                       Check service health
  mcp_mesh_dev logs                         View recent logs
  mcp_mesh_dev restart-agent my_agent      Restart specific agent
  mcp_mesh_dev stop                         Stop all services

Common Workflows:
  Development:
    mcp_mesh_dev start my_agent.py         # Start agent for development
    mcp_mesh_dev logs --follow             # Monitor logs in real-time
    mcp_mesh_dev status                    # Check agent health

  Debugging:
    mcp_mesh_dev list                      # List all running agents
    mcp_mesh_dev logs --agent my_agent     # View specific agent logs
    mcp_mesh_dev status --verbose          # Detailed status information

For more information, visit: https://github.com/your-org/mcp-mesh"""

    epilog = """Troubleshooting:
  • If registry fails to start, check if port 8080 is already in use
  • Use 'mcp_mesh_dev status' to verify all services are healthy
  • Check logs with 'mcp_mesh_dev logs' for detailed error information
  • Ensure your agent files follow MCP protocol specifications

Report issues at: https://github.com/your-org/mcp-mesh/issues"""

    parser = argparse.ArgumentParser(
        prog="mcp_mesh_dev",
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        version="mcp_mesh_dev 1.0.0-alpha",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        metavar="COMMAND",
    )

    # Start command
    start_help = """Start MCP Mesh services and components

This command starts the MCP Mesh registry and optionally one or more MCP agents.
The registry acts as a service discovery hub for agent communication.

Usage patterns:
  mcp_mesh_dev start                     # Start registry only
  mcp_mesh_dev start agent.py           # Start registry + single agent
  mcp_mesh_dev start agent1.py agent2.py # Start registry + multiple agents

The registry will start on port 8080 by default. Agents will automatically
register themselves with the registry upon startup."""

    start_parser = subparsers.add_parser(
        "start",
        help="Start MCP Mesh services",
        description=start_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Add arguments for start command
    start_parser.add_argument(
        "agents",
        nargs="*",
        help="Path to agent files to start (optional)",
        metavar="AGENT_FILE",
    )

    start_parser.add_argument(
        "--registry-port",
        type=int,
        help="Port for the registry service (default: 8080)",
        metavar="PORT",
    )

    start_parser.add_argument(
        "--registry-host",
        help="Host for the registry service (default: localhost)",
        metavar="HOST",
    )

    start_parser.add_argument(
        "--db-path",
        help="Path to SQLite database file (default: ./dev_registry.db)",
        metavar="PATH",
    )

    start_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )

    start_parser.add_argument(
        "--health-check-interval",
        type=int,
        help="Health check interval in seconds (default: 30)",
        metavar="SECONDS",
    )

    start_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )

    start_parser.add_argument(
        "--startup-timeout",
        type=int,
        help="Startup timeout in seconds (default: 30)",
        metavar="SECONDS",
    )

    start_parser.add_argument(
        "--registry-only",
        action="store_true",
        help="Start only the registry, no agents",
    )

    start_parser.add_argument(
        "--background",
        action="store_true",
        help="Run services in background",
    )

    start_parser.set_defaults(func=cmd_start)

    # Stop command
    stop_help = """Stop running MCP Mesh services and components

This command gracefully stops all running MCP Mesh services including
the registry and any connected agents. Agents will be given time to
complete current operations before shutdown."""

    stop_parser = subparsers.add_parser(
        "stop",
        help="Stop MCP Mesh services",
        description=stop_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    stop_parser.add_argument(
        "--force",
        action="store_true",
        help="Force stop services without graceful shutdown",
    )

    stop_parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for graceful shutdown (default: 30)",
        metavar="SECONDS",
    )

    stop_parser.add_argument(
        "--agent",
        help="Stop only the specified agent",
        metavar="AGENT_NAME",
    )

    stop_parser.set_defaults(func=cmd_stop)

    # Restart command
    restart_help = """Restart the MCP Mesh registry service

    This command gracefully restarts the registry service while preserving
    configuration and state. Useful for applying configuration changes or
    recovering from issues without affecting agent registrations."""

    restart_parser = subparsers.add_parser(
        "restart",
        help="Restart MCP Mesh registry service",
        description=restart_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    restart_parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for graceful shutdown (default: 30)",
        metavar="SECONDS",
    )

    restart_parser.add_argument(
        "--reset-config",
        action="store_true",
        help="Reset to default configuration instead of preserving current settings",
    )

    restart_parser.set_defaults(func=cmd_restart)

    # Restart agent command
    restart_agent_help = """Restart a specific MCP Mesh agent

    This command gracefully restarts an individual agent process while preserving
    its configuration and automatically re-registering it with the registry."""

    restart_agent_parser = subparsers.add_parser(
        "restart-agent",
        help="Restart a specific agent",
        description=restart_agent_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    restart_agent_parser.add_argument(
        "agent_name",
        help="Name of the agent to restart",
        metavar="AGENT_NAME",
    )

    restart_agent_parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for graceful shutdown (default: 30)",
        metavar="SECONDS",
    )

    restart_agent_parser.set_defaults(func=cmd_restart_agent)

    # Status command
    status_help = """Display the current status of MCP Mesh services and components

Shows health status, uptime, and basic metrics for:
- Registry service
- Connected agents
- Service connectivity
- Resource usage (with --verbose)

Use this command to verify that your MCP Mesh deployment is healthy."""

    status_parser = subparsers.add_parser(
        "status",
        help="Show status of MCP Mesh services",
        description=status_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    status_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed status information",
    )

    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output status in JSON format",
    )

    status_parser.set_defaults(func=cmd_status)

    # List command
    list_help = """List all available MCP Mesh agents and services

Displays information about:
- Running agents and their capabilities
- Available services and endpoints
- Agent registration status
- Connection health

Use filters to narrow down the list to specific agent types or services."""

    list_parser = subparsers.add_parser(
        "list",
        help="List available agents and services",
        description=list_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    list_parser.add_argument(
        "--agents",
        action="store_true",
        help="Show only agents",
    )

    list_parser.add_argument(
        "--services",
        action="store_true",
        help="Show only services",
    )

    list_parser.add_argument(
        "--filter",
        help="Filter by name pattern",
        metavar="PATTERN",
    )

    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )

    list_parser.set_defaults(func=cmd_list)

    # Logs command
    logs_help = """Display logs from MCP Mesh services and components

View logs from:
- Registry service
- Individual agents
- System events and errors
- Communication between services

Use --follow to monitor logs in real-time during development."""

    logs_parser = subparsers.add_parser(
        "logs",
        help="Show logs for MCP Mesh services",
        description=logs_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    logs_parser.add_argument(
        "--follow",
        action="store_true",
        help="Follow log output in real-time",
    )

    logs_parser.add_argument(
        "--agent",
        help="Show logs for specific agent",
        metavar="AGENT_NAME",
    )

    logs_parser.add_argument(
        "--level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Minimum log level to display",
        default="INFO",
    )

    logs_parser.add_argument(
        "--lines",
        type=int,
        default=50,
        help="Number of recent log lines to show (default: 50)",
        metavar="N",
    )

    logs_parser.set_defaults(func=cmd_logs)

    # Config command
    config_help = """Manage MCP Mesh Developer CLI configuration

    Configuration can be set via:
    1. Command-line arguments (highest priority)
    2. Configuration file (~/.mcp_mesh/cli_config.json)
    3. Environment variables (MCP_MESH_*)
    4. Default values (lowest priority)

    Examples:
      mcp_mesh_dev config show                    # Show current configuration
      mcp_mesh_dev config show --format json     # Show config in JSON format
      mcp_mesh_dev config set registry_port 8081 # Set registry port
      mcp_mesh_dev config save                   # Save current config as defaults
      mcp_mesh_dev config reset                  # Reset to defaults
      mcp_mesh_dev config path                   # Show config file location"""

    config_parser = subparsers.add_parser(
        "config",
        help="Manage CLI configuration",
        description=config_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    config_subparsers = config_parser.add_subparsers(
        dest="config_action",
        help="Configuration actions",
        metavar="ACTION",
    )

    # Config show subcommand
    show_parser = config_subparsers.add_parser(
        "show",
        help="Show current configuration",
    )
    show_parser.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format (default: yaml)",
    )

    # Config set subcommand
    set_parser = config_subparsers.add_parser(
        "set",
        help="Set configuration value",
    )
    set_parser.add_argument(
        "key",
        help="Configuration key to set",
    )
    set_parser.add_argument(
        "value",
        help="Configuration value to set",
    )

    # Config reset subcommand
    config_subparsers.add_parser(
        "reset",
        help="Reset configuration to defaults",
    )

    # Config path subcommand
    config_subparsers.add_parser(
        "path",
        help="Show configuration file path",
    )

    # Config save subcommand
    config_subparsers.add_parser(
        "save",
        help="Save current configuration as defaults",
    )

    config_parser.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the MCP Mesh Developer CLI."""
    # Install signal handlers for graceful shutdown
    install_signal_handlers()

    # Register CLI-specific cleanup handlers
    def cleanup_cli_resources():
        """Cleanup CLI resources on shutdown."""
        try:
            from .process_tracker import get_process_tracker

            process_tracker = get_process_tracker()

            # Only perform aggressive cleanup if we're actually shutting down
            # Check if this is an intentional shutdown vs a startup issue
            cleanup_manager = get_cleanup_manager()
            if cleanup_manager.is_shutdown_in_progress():
                # Cleanup orphaned processes
                orphaned_results = process_tracker.cleanup_orphaned_processes()
                if orphaned_results:
                    print(f"Cleaned up {len(orphaned_results)} orphaned processes")

                # Clean up dead processes
                dead_processes = process_tracker.cleanup_dead_processes()
                if dead_processes:
                    print(f"Removed {len(dead_processes)} dead process entries")

        except Exception as e:
            print(f"Warning: Error during CLI cleanup: {e}", file=sys.stderr)

    register_cleanup_handler(cleanup_cli_resources)

    parser = create_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        # Let signal handler manage cleanup
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
