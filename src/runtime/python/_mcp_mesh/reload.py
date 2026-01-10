"""
File watch and reload functionality for MCP Mesh agents.

Provides automatic restart of agent processes when source files change.
Used by `meshctl start --watch` for development workflows.
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Debounce delay to batch rapid file changes (seconds)
DEBOUNCE_DELAY = float(os.getenv("MCP_MESH_RELOAD_DEBOUNCE", "0.5"))

# Delay after stopping process to allow port release (seconds)
PORT_RELEASE_DELAY = float(os.getenv("MCP_MESH_RELOAD_PORT_DELAY", "0.5"))


def get_watch_paths(script_path: str) -> list[Path]:
    """
    Determine which paths to watch for changes.

    Watches the directory containing the agent script and all subdirectories.
    """
    script_dir = Path(script_path).parent.absolute()
    return [script_dir]


def should_watch_file(path: str) -> bool:
    """
    Filter function to determine which files to watch.

    Only watches:
    - Python files (.py)
    - Jinja2 templates (.jinja2, .j2)
    - YAML config files (.yaml, .yml)

    Excludes common non-source directories like __pycache__, .git, .venv, etc.
    Also excludes hidden files and editor temporary files.
    """
    path_obj = Path(path)
    filename = path_obj.name

    # Skip hidden files and editor temp files (e.g., .!12345!main.py from sed -i)
    if filename.startswith("."):
        return False

    # Skip common editor backup/temp files
    if filename.endswith("~") or filename.endswith(".swp") or filename.endswith(".tmp"):
        return False

    path_parts = {p.lower() for p in path_obj.parts}

    # Skip common non-source directories (case-insensitive, exact component match)
    skip_patterns = [
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        ".pytest_cache",
        ".mypy_cache",
        "node_modules",
        ".eggs",
        ".egg-info",
    ]

    for pattern in skip_patterns:
        if pattern.lower() in path_parts:
            return False

    # Only watch specific file types
    watch_extensions = [".py", ".jinja2", ".j2", ".yaml", ".yml"]
    return path_obj.suffix.lower() in watch_extensions


def terminate_process(process: subprocess.Popen, timeout: int = 3) -> None:
    """
    Gracefully terminate a process and all its children, force kill if needed.

    Args:
        process: The subprocess to terminate
        timeout: Seconds to wait before force killing
    """
    if process is None or process.poll() is not None:
        return

    pid = process.pid

    # Try graceful termination first - send to process group to include children
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        # Process group doesn't exist or we can't signal it, try direct
        process.terminate()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning(f"Process {pid} didn't terminate gracefully, force killing...")
        # Force kill the entire process group
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.wait()


def run_with_reload(script_path: str) -> None:
    """
    Run the agent script with file watching and auto-reload.

    Uses watchfiles to monitor the agent directory for changes.
    When files change, the agent process is terminated and restarted.

    Args:
        script_path: Path to the agent's main.py script
    """
    try:
        import watchfiles
    except ImportError:
        logger.error(
            "watchfiles is required for reload mode. "
            "Install with: pip install watchfiles"
        )
        sys.exit(1)

    script_path = os.path.abspath(script_path)
    watch_paths = get_watch_paths(script_path)
    python_exec = sys.executable

    logger.info("🔄 Starting agent with file watching enabled")
    logger.info(f"📁 Watching: {watch_paths[0]}")
    logger.info("📝 File types: .py, .jinja2, .j2, .yaml, .yml")
    logger.info("🔃 Agent will restart automatically when files change")

    process = None
    stop_event = threading.Event()

    def signal_handler(signum, frame):
        stop_event.set()
        logger.info("🛑 Stopping agent...")
        terminate_process(process)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    def start_agent() -> subprocess.Popen:
        """Start the agent subprocess in a new process group."""
        return subprocess.Popen(
            [python_exec, script_path],
            stdout=sys.stdout,
            stderr=sys.stderr,
            stdin=sys.stdin,
            start_new_session=True,  # Create new process group for clean shutdown
        )

    # Start initial process
    process = start_agent()
    logger.info(f"✅ Agent started (PID: {process.pid})")

    # Watch for file changes
    try:
        for changes in watchfiles.watch(
            *watch_paths,
            watch_filter=lambda ct, p: should_watch_file(p),
            debounce=int(DEBOUNCE_DELAY * 1000),  # Convert to milliseconds
            stop_event=stop_event,
        ):
            if stop_event.is_set():
                break

            # Check if process crashed
            if process.poll() is not None:
                logger.warning(f"⚠️ Agent process exited with code {process.returncode}")

            # Log changes
            for change_type, path in changes:
                rel_path = os.path.relpath(path, watch_paths[0])
                logger.info(f"🔄 Detected {change_type.name}: {rel_path}")

            logger.info("🔃 Restarting agent...")

            # Stop current process
            terminate_process(process)

            # Delay to allow ports to be released
            time.sleep(PORT_RELEASE_DELAY)

            # Start new process
            process = start_agent()
            logger.info(f"✅ Agent restarted (PID: {process.pid})")

    except KeyboardInterrupt:
        pass
    finally:
        terminate_process(process)
        logger.info("👋 File watcher stopped")
