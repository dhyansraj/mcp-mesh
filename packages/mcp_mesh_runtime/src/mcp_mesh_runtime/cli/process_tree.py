"""Process tree management and cleanup utilities."""

import os
import platform
import subprocess
import time

import psutil

from .logging import get_logger


class ProcessTree:
    """Manages process trees and hierarchical cleanup."""

    def __init__(self):
        self.logger = get_logger("cli.process_tree")
        self.system = platform.system().lower()

    def get_process_tree(self, root_pid: int) -> dict[int, list[int]]:
        """Get the complete process tree starting from root_pid.

        Returns:
            Dict mapping parent PID to list of child PIDs
        """
        tree = {}

        try:
            root_process = psutil.Process(root_pid)

            # Use recursive=True to get all descendants
            children = root_process.children(recursive=True)

            # Build tree structure
            all_processes = [root_process] + children

            for proc in all_processes:
                try:
                    parent_pid = proc.ppid()
                    child_pid = proc.pid

                    if parent_pid not in tree:
                        tree[parent_pid] = []

                    if child_pid != root_pid:  # Don't add root as child of its parent
                        tree[parent_pid].append(child_pid)

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return tree

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.warning(f"Cannot access process {root_pid}: {e}")
            return {}

    def get_all_descendants(self, root_pid: int) -> list[int]:
        """Get all descendant PIDs of a root process."""
        descendants = []

        try:
            root_process = psutil.Process(root_pid)
            children = root_process.children(recursive=True)
            descendants = [child.pid for child in children]

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.warning(f"Cannot get descendants of {root_pid}: {e}")

        return descendants

    def terminate_process_tree(
        self, root_pid: int, timeout: float = 10.0, force_kill_timeout: float = 5.0
    ) -> dict[int, bool]:
        """Terminate an entire process tree gracefully.

        Args:
            root_pid: Root process PID
            timeout: Time to wait for graceful termination
            force_kill_timeout: Time to wait before force killing

        Returns:
            Dict mapping PID to success status
        """
        results = {}

        try:
            root_process = psutil.Process(root_pid)

            # Get all processes in the tree
            all_children = root_process.children(recursive=True)
            all_processes = all_children + [root_process]  # Children first, then root

            self.logger.info(
                f"Terminating process tree with {len(all_processes)} processes"
            )

            # Step 1: Send SIGTERM to all processes (children first)
            terminated_processes = []
            for proc in all_processes:
                try:
                    if proc.is_running():
                        self.logger.debug(f"Sending SIGTERM to PID {proc.pid}")
                        proc.terminate()
                        terminated_processes.append(proc)
                        results[proc.pid] = False  # Will update to True if successful
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    results[proc.pid] = True  # Already gone or inaccessible

            # Step 2: Wait for graceful termination
            start_time = time.time()
            remaining_processes = terminated_processes[:]

            while remaining_processes and (time.time() - start_time) < timeout:
                for proc in remaining_processes[:]:
                    try:
                        if not proc.is_running():
                            self.logger.debug(
                                f"Process {proc.pid} terminated gracefully"
                            )
                            results[proc.pid] = True
                            remaining_processes.remove(proc)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        results[proc.pid] = True
                        remaining_processes.remove(proc)

                if remaining_processes:
                    time.sleep(0.1)

            # Step 3: Force kill remaining processes
            if remaining_processes:
                self.logger.warning(
                    f"Force killing {len(remaining_processes)} remaining processes"
                )

                for proc in remaining_processes:
                    try:
                        if proc.is_running():
                            self.logger.debug(f"Force killing PID {proc.pid}")
                            proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                # Wait for force kill to complete
                kill_start = time.time()
                while (
                    remaining_processes
                    and (time.time() - kill_start) < force_kill_timeout
                ):
                    for proc in remaining_processes[:]:
                        try:
                            if not proc.is_running():
                                results[proc.pid] = True
                                remaining_processes.remove(proc)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            results[proc.pid] = True
                            remaining_processes.remove(proc)

                    if remaining_processes:
                        time.sleep(0.1)

                # Mark any still-remaining processes as failed
                for proc in remaining_processes:
                    results[proc.pid] = False
                    self.logger.error(f"Failed to terminate process {proc.pid}")

            return results

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.warning(f"Cannot terminate process tree {root_pid}: {e}")
            return {root_pid: False}

    def find_orphaned_processes(self, known_pids: set[int]) -> list[int]:
        """Find orphaned processes that may need cleanup.

        Args:
            known_pids: Set of PIDs we know about and manage

        Returns:
            List of potentially orphaned PIDs
        """
        orphaned = []

        try:
            # Look for processes that might be our children but aren't tracked
            current_process = psutil.Process()
            all_children = current_process.children(recursive=True)

            for child in all_children:
                if child.pid not in known_pids:
                    try:
                        # Check if this looks like an MCP Mesh process
                        cmdline = child.cmdline()
                        if self._is_mcp_mesh_process(cmdline):
                            orphaned.append(child.pid)
                            self.logger.warning(
                                f"Found potential orphaned MCP process: {child.pid} {' '.join(cmdline)}"
                            )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

        except Exception as e:
            self.logger.warning(f"Error finding orphaned processes: {e}")

        return orphaned

    def _is_mcp_mesh_process(self, cmdline: list[str]) -> bool:
        """Check if a command line indicates an MCP Mesh related process."""
        if not cmdline:
            return False

        command_str = " ".join(cmdline).lower()

        # Check for MCP Mesh indicators
        indicators = [
            "mcp_mesh",
            "mcp-mesh",
            "mcpmesh",
            "mcp_registry",
            "mcp_agent",
            # Add other patterns as needed
        ]

        return any(indicator in command_str for indicator in indicators)

    def cleanup_orphaned_processes(self, orphaned_pids: list[int]) -> dict[int, bool]:
        """Clean up orphaned processes.

        Args:
            orphaned_pids: List of orphaned process PIDs

        Returns:
            Dict mapping PID to cleanup success status
        """
        results = {}

        for pid in orphaned_pids:
            self.logger.info(f"Cleaning up orphaned process {pid}")
            tree_results = self.terminate_process_tree(
                pid, timeout=5.0, force_kill_timeout=3.0
            )
            results.update(tree_results)

        return results

    def get_process_info_tree(self, root_pid: int) -> dict[int, dict]:
        """Get detailed information about a process tree.

        Returns:
            Dict mapping PID to process information
        """
        info_tree = {}

        try:
            root_process = psutil.Process(root_pid)
            all_processes = [root_process] + root_process.children(recursive=True)

            for proc in all_processes:
                try:
                    info_tree[proc.pid] = {
                        "pid": proc.pid,
                        "ppid": proc.ppid(),
                        "name": proc.name(),
                        "cmdline": proc.cmdline(),
                        "status": proc.status(),
                        "create_time": proc.create_time(),
                        "memory_info": (
                            proc.memory_info()._asdict() if proc.memory_info() else None
                        ),
                        "cpu_percent": 0.0,  # Would need time to calculate
                    }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    info_tree[proc.pid] = {
                        "pid": proc.pid,
                        "status": "inaccessible",
                        "error": "Access denied or process no longer exists",
                    }

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.warning(f"Cannot get process tree info for {root_pid}: {e}")

        return info_tree

    def monitor_process_tree(self, root_pid: int, callback=None) -> bool:
        """Monitor a process tree for changes.

        Args:
            root_pid: Root process to monitor
            callback: Optional callback for process events

        Returns:
            True if monitoring started successfully
        """
        try:
            # This is a simplified version - a full implementation would use
            # continuous monitoring with proper event handling
            initial_tree = self.get_process_tree(root_pid)

            if callback:
                callback(
                    "tree_discovered", {"root_pid": root_pid, "tree": initial_tree}
                )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to start monitoring process tree {root_pid}: {e}"
            )
            return False

    def get_system_specific_kill_method(self) -> str:
        """Get the best kill method for the current system."""
        if self.system == "windows":
            return "taskkill"
        elif self.system in ["linux", "darwin"]:
            return "kill"
        else:
            return "psutil"  # Fallback to psutil

    def system_kill_process_tree(self, root_pid: int) -> bool:
        """Use system-specific commands to kill a process tree."""
        kill_method = self.get_system_specific_kill_method()

        try:
            if kill_method == "taskkill" and self.system == "windows":
                # Windows taskkill with /T flag kills tree
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(root_pid)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result.returncode == 0

            elif kill_method == "kill" and self.system in ["linux", "darwin"]:
                # Unix kill - we need to handle tree manually
                descendants = self.get_all_descendants(root_pid)
                all_pids = descendants + [root_pid]

                # Send SIGTERM first
                for pid in all_pids:
                    try:
                        os.kill(pid, 15)  # SIGTERM
                    except (OSError, ProcessLookupError):
                        pass

                time.sleep(2)

                # Send SIGKILL if needed
                for pid in all_pids:
                    try:
                        os.kill(pid, 9)  # SIGKILL
                    except (OSError, ProcessLookupError):
                        pass

                return True

            else:
                # Fallback to psutil method
                results = self.terminate_process_tree(root_pid)
                return all(results.values())

        except Exception as e:
            self.logger.error(f"System kill failed for {root_pid}: {e}")
            return False


# Global process tree manager
_process_tree: ProcessTree | None = None


def get_process_tree() -> ProcessTree:
    """Get the global process tree manager."""
    global _process_tree
    if _process_tree is None:
        _process_tree = ProcessTree()
    return _process_tree


__all__ = [
    "ProcessTree",
    "get_process_tree",
]
