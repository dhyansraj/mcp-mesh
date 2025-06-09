#!/usr/bin/env python3
"""
Demonstration of MCP Mesh process cleanup and management capabilities.

This example shows:
1. Signal handling for graceful shutdown
2. Process tree cleanup
3. Process monitoring and recovery
4. Cross-platform process management

Run this script and try:
- Ctrl+C for graceful shutdown
- Kill the process with SIGTERM
- Monitor child processes
"""

import asyncio
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add the packages to the path for demo
sys.path.insert(
    0, str(Path(__file__).parent.parent / "packages" / "mcp_mesh_runtime" / "src")
)

from mcp_mesh_runtime.cli.process_monitor import (
    MonitoringPolicy,
    get_process_monitor,
    start_process_monitoring,
)
from mcp_mesh_runtime.cli.process_tracker import get_process_tracker
from mcp_mesh_runtime.cli.process_tree import get_process_tree
from mcp_mesh_runtime.cli.signal_handler import (
    install_signal_handlers,
    register_cleanup_handler,
)


def create_demo_agent_script(script_path: Path) -> None:
    """Create a demo agent script that simulates an MCP agent."""
    script_content = '''#!/usr/bin/env python3
"""Demo MCP agent for process management testing."""

import time
import sys
import os
import signal
import random

class DemoAgent:
    def __init__(self, name):
        self.name = name
        self.running = True
        self.counter = 0

        # Handle signals gracefully
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        print(f"[{self.name}] Received signal {signum}, shutting down gracefully...")
        self.running = False

    def run(self):
        print(f"[{self.name}] Started with PID {os.getpid()}")

        while self.running:
            self.counter += 1
            print(f"[{self.name}] Heartbeat {self.counter} (PID: {os.getpid()})")

            # Simulate some work
            time.sleep(2)

            # Simulate random failure (10% chance)
            if random.random() < 0.1:
                print(f"[{self.name}] Simulating failure!")
                sys.exit(1)

        print(f"[{self.name}] Shutdown complete")

if __name__ == "__main__":
    agent_name = sys.argv[1] if len(sys.argv) > 1 else "demo_agent"
    agent = DemoAgent(agent_name)
    agent.run()
'''

    script_path.write_text(script_content)
    script_path.chmod(0o755)


def demo_alert_handler(event_type: str, process_name: str, details: dict) -> None:
    """Handle process monitoring alerts."""
    timestamp = details.get("timestamp", "unknown")

    if event_type == "process_failed":
        print(f"🚨 ALERT: Process {process_name} failed at {timestamp}")
        print(f"   Error: {details.get('error', 'Unknown error')}")
        print(f"   Consecutive failures: {details.get('consecutive_failures', 0)}")

    elif event_type == "process_recovered":
        print(f"✅ RECOVERY: Process {process_name} recovered at {timestamp}")
        print(f"   Previous failures: {details.get('previous_failures', 0)}")

    elif event_type == "process_restarted":
        print(f"🔄 RESTART: Process {process_name} restarted at {timestamp}")
        print(f"   New PID: {details.get('new_pid', 'unknown')}")
        print(f"   Restart count: {details.get('restart_count', 0)}")

    elif event_type == "process_restart_failed":
        print(
            f"❌ RESTART FAILED: Process {process_name} restart failed at {timestamp}"
        )
        print(f"   Restart count: {details.get('restart_count', 0)}")


async def main():
    """Main demonstration function."""
    print("🚀 MCP Mesh Process Management Demo")
    print("=" * 50)

    # Install signal handlers
    print("📡 Installing signal handlers...")
    cleanup_manager = install_signal_handlers()

    # Initialize components
    process_tracker = get_process_tracker()
    process_monitor = get_process_monitor()
    process_tree = get_process_tree()

    # Register cleanup handler
    def demo_cleanup():
        print("🧹 Demo cleanup: stopping all demo processes...")
        # Additional cleanup logic could go here

    register_cleanup_handler(demo_cleanup)

    # Create temporary directory for demo scripts
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        print(f"📁 Created temporary directory: {temp_path}")

        # Create demo agent scripts
        agent_scripts = []
        for i in range(3):
            script_path = temp_path / f"demo_agent_{i}.py"
            create_demo_agent_script(script_path)
            agent_scripts.append(script_path)

        print(f"📝 Created {len(agent_scripts)} demo agent scripts")

        # Start demo agents
        demo_processes = {}
        for i, script_path in enumerate(agent_scripts):
            agent_name = f"demo_agent_{i}"

            print(f"🚀 Starting {agent_name}...")

            # Start process
            process = subprocess.Popen([sys.executable, str(script_path), agent_name])

            # Track process
            process_info = process_tracker.track_process(
                name=agent_name,
                pid=process.pid,
                command=[sys.executable, str(script_path), agent_name],
                service_type="demo_agent",
                metadata={
                    "working_directory": str(temp_path),
                    "script_path": str(script_path),
                    "agent_type": "demo",
                },
            )

            demo_processes[agent_name] = process

            # Set monitoring policy
            policy = MonitoringPolicy(
                enabled=True,
                check_interval=5.0,
                restart_on_failure=True,
                max_restart_attempts=2,
                restart_cooldown=10.0,
                alert_on_failure=True,
                alert_on_recovery=True,
            )
            process_monitor.set_process_policy(agent_name, policy)

            print(f"✅ Started {agent_name} with PID {process.pid}")

        # Add alert handler
        process_monitor.add_alert_callback(demo_alert_handler)

        # Start monitoring
        print("🔍 Starting process monitoring...")
        start_process_monitoring()

        # Display initial status
        print("\n📊 Initial Process Status:")
        print("-" * 30)

        for name, process in demo_processes.items():
            health_info = process_tracker.monitor_process_health(name)
            print(f"Process: {name}")
            print(f"  PID: {process.pid}")
            print(f"  Health: {health_info.get('basic_health', 'unknown')}")
            print(f"  Uptime: {health_info.get('uptime', 0):.1f}s")
            print()

        # Show process tree
        print("🌳 Process Tree Information:")
        print("-" * 30)

        for name, process in demo_processes.items():
            tree_info = process_tree.get_process_info_tree(process.pid)
            print(f"Process {name} (PID {process.pid}):")
            for pid, info in tree_info.items():
                if "error" not in info:
                    print(
                        f"  └─ PID {pid}: {info.get('name', 'unknown')} [{info.get('status', 'unknown')}]"
                    )
            print()

        # Demonstration loop
        print("🎮 Demo Control:")
        print("  - Press Ctrl+C for graceful shutdown")
        print("  - Processes will run and may randomly fail (10% chance every 2s)")
        print("  - Monitor will attempt to restart failed processes")
        print("  - Wait and observe the monitoring in action...")
        print()

        try:
            # Run demonstration for a while
            start_time = time.time()
            while time.time() - start_time < 60:  # Run for 1 minute
                await asyncio.sleep(1)

                # Periodically show monitoring status
                if int(time.time() - start_time) % 15 == 0:
                    print("\n📈 Monitoring Status Update:")
                    print("-" * 30)

                    status = process_monitor.get_monitoring_status()
                    for proc_name, proc_status in status["processes"].items():
                        print(f"{proc_name}:")
                        print(f"  Health: {proc_status['health']}")
                        print(f"  Failures: {proc_status['consecutive_failures']}")
                        print(f"  Restarts: {proc_status['restart_count']}")
                        if proc_status["error_message"]:
                            print(f"  Last Error: {proc_status['error_message']}")
                        print()

        except KeyboardInterrupt:
            print("\n🛑 Graceful shutdown initiated by user...")

        finally:
            print("\n🧹 Cleaning up demo processes...")

            # Stop monitoring
            process_monitor.stop_monitoring()

            # Terminate all tracked processes
            results = process_tracker.terminate_all_processes(timeout=5)

            for name, success in results.items():
                if success:
                    print(f"✅ Successfully terminated {name}")
                else:
                    print(f"⚠️  May not have cleanly terminated {name}")

            # Clean up any orphaned processes
            orphaned_results = process_tracker.cleanup_orphaned_processes()
            if orphaned_results:
                print(f"🧹 Cleaned up {len(orphaned_results)} orphaned processes")

            print("✨ Demo cleanup complete!")


if __name__ == "__main__":
    print("MCP Mesh Process Management Demo")
    print("This demo shows signal handling, process monitoring, and cleanup.")
    print()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDemo interrupted by user")
    except Exception as e:
        print(f"Demo error: {e}")
        import traceback

        traceback.print_exc()

    print("\nDemo finished. Thank you!")
