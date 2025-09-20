"""
Shared utilities for discovering existing FastAPI and uvicorn server instances.

This module provides utilities to discover running servers that have been started
outside the pipeline, such as by immediate uvicorn start in decorators.
"""

import gc
import logging
import socket
from typing import Any, Dict, List, Optional, Tuple
import threading

logger = logging.getLogger(__name__)


class ServerDiscoveryUtil:
    """Utility class for discovering existing FastAPI apps and uvicorn servers."""

    @staticmethod
    def discover_fastapi_instances() -> Dict[str, Dict[str, Any]]:
        """
        Discover FastAPI application instances in the Python runtime.
        
        Uses intelligent deduplication to handle standard uvicorn patterns where
        the same app might be imported multiple times (e.g., "module:app" pattern).
        
        Returns:
            Dict mapping app_id -> app_info where app_info contains:
            - 'instance': The FastAPI app instance
            - 'title': App title from FastAPI
            - 'routes': List of route information
            - 'module': Module where app was found
        """
        fastapi_apps = {}
        seen_apps = {}  # For deduplication: title -> app_info
        
        try:
            # Import FastAPI here to avoid dependency if not used
            from fastapi import FastAPI
        except ImportError:
            logger.warning("FastAPI not installed - cannot discover FastAPI apps")
            return {}

        # Scan garbage collector for FastAPI instances
        candidate_apps = []
        for obj in gc.get_objects():
            if isinstance(obj, FastAPI):
                candidate_apps.append(obj)

        # Deduplicate apps with identical configurations
        for obj in candidate_apps:
            try:
                title = getattr(obj, "title", "FastAPI App")
                version = getattr(obj, "version", "unknown")
                routes = ServerDiscoveryUtil._extract_route_info(obj)
                route_count = len(routes)
                
                # Create a signature for deduplication
                app_signature = (title, version, route_count)
                
                # Check if we've seen an identical app
                if app_signature in seen_apps:
                    existing_app = seen_apps[app_signature]
                    # Compare route details to ensure they're truly identical
                    existing_routes = existing_app["routes"]
                    
                    if ServerDiscoveryUtil._routes_are_identical(routes, existing_routes):
                        logger.debug(
                            f"Skipping duplicate FastAPI app: '{title}' (same title, version, and routes)"
                        )
                        continue  # Skip this duplicate
                
                # This is a unique app, add it
                app_id = f"app_{id(obj)}"
                app_info = {
                    "instance": obj,
                    "title": title,
                    "version": version,
                    "routes": routes,
                    "module": ServerDiscoveryUtil._get_app_module(obj),
                    "object_id": id(obj),
                    "router_routes_count": len(obj.router.routes) if hasattr(obj, 'router') else 0,
                }
                
                fastapi_apps[app_id] = app_info
                seen_apps[app_signature] = app_info
                
                logger.debug(
                    f"Found FastAPI app: '{title}' (module: {app_info['module']}) with "
                    f"{len(routes)} routes"
                )
                
            except Exception as e:
                logger.warning(f"Error analyzing FastAPI app: {e}")
                continue

        return fastapi_apps

    @staticmethod
    def discover_running_servers() -> List[Dict[str, Any]]:
        """
        Discover running uvicorn servers by scanning threads and checking port bindings.
        
        Returns:
            List of server info dictionaries containing:
            - 'type': 'uvicorn' or 'unknown'
            - 'host': Server host
            - 'port': Server port
            - 'thread': Thread object if found
            - 'app': FastAPI app if discoverable
        """
        running_servers = []
        
        # Look for uvicorn server threads
        for thread in threading.enumerate():
            if hasattr(thread, '_target'):
                # Check if thread target looks like a uvicorn server
                target_name = getattr(thread._target, '__name__', '') if thread._target else ''
                if 'server' in target_name.lower() or 'uvicorn' in target_name.lower():
                    server_info = {
                        'type': 'uvicorn',
                        'thread': thread,
                        'target_name': target_name,
                        'daemon': thread.daemon,
                        'alive': thread.is_alive(),
                    }
                    
                    # Try to extract server details from thread
                    server_details = ServerDiscoveryUtil._extract_server_details_from_thread(thread)
                    server_info.update(server_details)
                    
                    running_servers.append(server_info)
                    logger.debug(f"Found running server thread: {target_name} (daemon={thread.daemon})")
        
        # Also check for bound ports that might indicate running servers
        bound_ports = ServerDiscoveryUtil._discover_bound_ports()
        for port_info in bound_ports:
            # Only add if we haven't already found this port via thread discovery
            existing_ports = [s.get('port') for s in running_servers if s.get('port')]
            if port_info['port'] not in existing_ports:
                port_info['type'] = 'unknown'
                running_servers.append(port_info)
                logger.debug(f"Found bound port: {port_info['host']}:{port_info['port']}")
        
        return running_servers

    @staticmethod
    def _extract_server_details_from_thread(thread) -> Dict[str, Any]:
        """Extract server details from a thread if possible."""
        details = {}
        
        try:
            # Try to access thread local variables or target args
            if hasattr(thread, '_args') and thread._args:
                # Some uvicorn servers might have args with host/port
                args = thread._args
                if len(args) >= 2:
                    # Common pattern: (app, host, port) or similar
                    if isinstance(args[0], str) and ':' in args[0]:
                        # Might be "host:port" format
                        try:
                            host, port = args[0].split(':')
                            details['host'] = host
                            details['port'] = int(port)
                        except (ValueError, IndexError):
                            pass
            
            # Try to find FastAPI app in thread target or args
            if hasattr(thread, '_target') and thread._target:
                # Check if target has app attribute or if it's in closure
                target = thread._target
                if hasattr(target, '__closure__') and target.__closure__:
                    for cell in target.__closure__:
                        try:
                            cell_contents = cell.cell_contents
                            from fastapi import FastAPI
                            if isinstance(cell_contents, FastAPI):
                                details['app'] = cell_contents
                                details['app_title'] = getattr(cell_contents, 'title', 'Unknown')
                                break
                        except (ImportError, AttributeError):
                            continue
                            
        except Exception as e:
            logger.debug(f"Could not extract server details from thread: {e}")
        
        return details

    @staticmethod
    def _discover_bound_ports() -> List[Dict[str, Any]]:
        """Discover ports that are currently bound by this process."""
        bound_ports = []
        
        try:
            # Common port ranges for web servers
            common_ports = [8000, 8080, 8090, 9090, 9091, 3000, 3001, 4000, 5000]
            
            for port in common_ports:
                for host in ['127.0.0.1', '0.0.0.0', 'localhost']:
                    try:
                        # Try to connect to see if port is bound
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(0.1)  # Very short timeout
                        result = sock.connect_ex((host, port))
                        sock.close()
                        
                        if result == 0:  # Connection successful = port is bound
                            bound_ports.append({
                                'host': host,
                                'port': port,
                                'status': 'bound'
                            })
                            break  # Don't check other hosts for same port
                    except Exception:
                        continue
                        
        except Exception as e:
            logger.debug(f"Error discovering bound ports: {e}")
        
        return bound_ports

    @staticmethod
    def find_server_on_port(target_port: int, target_host: str = None) -> Optional[Dict[str, Any]]:
        """
        Find if there's already a server running on the specified port.
        
        Args:
            target_port: Port to check
            target_host: Host to check (optional)
            
        Returns:
            Server info dict if found, None otherwise
        """
        running_servers = ServerDiscoveryUtil.discover_running_servers()
        
        for server in running_servers:
            server_port = server.get('port')
            server_host = server.get('host')
            
            # Check port match
            if server_port == target_port:
                # If target_host is specified, check host match too
                if target_host is None or server_host == target_host or server_host in ['0.0.0.0', '127.0.0.1']:
                    logger.info(f"🔍 DISCOVERY: Found existing server on {server_host}:{server_port}")
                    return server
        
        logger.debug(f"🔍 DISCOVERY: No existing server found on port {target_port}")
        return None

    @staticmethod
    def _routes_are_identical(routes1: List[Dict[str, Any]], routes2: List[Dict[str, Any]]) -> bool:
        """Compare two route lists to see if they're identical."""
        if len(routes1) != len(routes2):
            return False
            
        # Create comparable signatures for each route
        def route_signature(route):
            return (
                tuple(sorted(route.get('methods', []))),  # Sort methods for consistent comparison
                route.get('path', ''),
                route.get('endpoint_name', '')
            )
        
        # Sort routes by signature for consistent comparison
        sig1 = sorted([route_signature(r) for r in routes1])
        sig2 = sorted([route_signature(r) for r in routes2])
        
        return sig1 == sig2

    @staticmethod
    def _extract_route_info(app) -> List[Dict[str, Any]]:
        """Extract route information from FastAPI app without modifying it."""
        routes = []
        
        try:
            for route in app.router.routes:
                if hasattr(route, 'endpoint') and hasattr(route, 'path'):
                    route_info = {
                        "path": route.path,
                        "methods": list(route.methods) if hasattr(route, 'methods') else [],
                        "endpoint": route.endpoint,
                        "endpoint_name": getattr(route.endpoint, '__name__', 'unknown'),
                        "has_mesh_route": hasattr(route.endpoint, '_mesh_route_metadata'),
                    }
                    routes.append(route_info)
                    
        except Exception as e:
            logger.warning(f"Error extracting route info: {e}")
            
        return routes

    @staticmethod
    def _get_app_module(app) -> Optional[str]:
        """Try to determine which module the FastAPI app belongs to."""
        try:
            # Try to get module from the app's stack frame when it was created
            # This is best-effort - may not always work
            import inspect
            
            frame = inspect.currentframe()
            while frame:
                frame_globals = frame.f_globals
                for name, obj in frame_globals.items():
                    if obj is app:
                        return frame_globals.get('__name__', 'unknown')
                frame = frame.f_back
                
        except Exception:
            pass
            
        return None