"""
FastAPI Middleware Manager

Handles automatic injection of MCP Mesh tracing middleware into FastAPI applications.
This module provides enhanced middleware injection logic with better timing control,
robust app discovery, and graceful error handling.
"""

import gc
import logging
import time
from typing import List, Optional, Set

logger = logging.getLogger(__name__)


class FastAPIMiddlewareManager:
    """Enhanced FastAPI middleware injection manager.
    
    Provides robust middleware injection capabilities with:
    - Multiple app discovery methods
    - App state detection and validation
    - Retry logic for timing issues
    - Graceful error handling
    - Monkey-patch FastAPI creation for immediate injection
    """
    
    def __init__(self):
        self._processed_apps: Set[int] = set()  # Track processed apps by id()
        self._monkey_patch_applied = False
        self._pending_middleware_needed = False  # Flag that middleware is needed
        
    def enable_middleware_injection(self) -> bool:
        """
        Enable middleware injection via monkey-patching FastAPI creation.
        
        This sets up automatic middleware injection when FastAPI apps are created,
        eliminating timing issues with app startup.
        
        Returns:
            bool: True if monkey-patch was applied successfully
        """
        if self._monkey_patch_applied:
            logger.debug("🔍 TRACING: Monkey-patch already applied")
            return True
            
        try:
            from fastapi import FastAPI
            
            # Store original FastAPI.__init__
            if not hasattr(FastAPI, '_original_init'):
                FastAPI._original_init = FastAPI.__init__
                
            # Create enhanced __init__ that adds middleware immediately
            def enhanced_fastapi_init(self, *args, **kwargs):
                # Call original FastAPI initialization
                result = FastAPI._original_init(self, *args, **kwargs)
                
                # Immediately add middleware to this newly created app
                try:
                    manager = get_fastapi_middleware_manager()
                    if manager._pending_middleware_needed:
                        success = manager.add_middleware_to_specific_app(self)
                        if success:
                            logger.debug(f"🔍 TRACING: Auto-injected middleware to FastAPI app '{getattr(self, 'title', 'Unknown')}' during creation")
                        else:
                            logger.debug(f"🔍 TRACING: Failed to auto-inject middleware during app creation")
                except Exception as e:
                    # Never break FastAPI app creation
                    logger.debug(f"🔍 TRACING: Auto-injection failed during app creation: {e}")
                
                return result
            
            # Apply the monkey-patch
            FastAPI.__init__ = enhanced_fastapi_init
            self._monkey_patch_applied = True
            
            logger.debug("🔍 TRACING: Successfully applied FastAPI creation monkey-patch")
            return True
            
        except Exception as e:
            logger.debug(f"🔍 TRACING: Failed to apply FastAPI monkey-patch: {e}")
            return False

    def request_middleware_injection(self) -> bool:
        """
        Request that middleware be injected into FastAPI apps.
        
        This method should be called from @mesh.route decorators to signal
        that middleware injection is needed.
        
        Returns:
            bool: True if injection was set up successfully
        """
        self._pending_middleware_needed = True
        
        # Try immediate discovery first (for apps that already exist)
        immediate_success = self.add_tracing_middleware_to_discovered_apps()
        
        # Also enable monkey-patch for future app creation
        monkey_patch_success = self.enable_middleware_injection()
        
        logger.debug(f"🔍 TRACING: Middleware injection requested - immediate: {immediate_success}, monkey-patch: {monkey_patch_success}")
        return immediate_success or monkey_patch_success

    def add_tracing_middleware_to_discovered_apps(self) -> bool:
        """
        Add tracing middleware to all discovered FastAPI apps.
        
        Returns:
            bool: True if any middleware was successfully added, False otherwise
        """
        logger.debug("🔍 TRACING: Starting enhanced middleware injection for FastAPI apps...")
        
        apps = self._discover_fastapi_apps()
        if not apps:
            logger.debug("🔍 TRACING: No FastAPI apps discovered")
            return False
            
        success_count = 0
        for app in apps:
            if self._add_middleware_to_app_with_retry(app):
                success_count += 1
                
        logger.debug(f"🔍 TRACING: Enhanced middleware injection completed - {success_count}/{len(apps)} apps processed")
        return success_count > 0
    
    def add_middleware_to_specific_app(self, app) -> bool:
        """
        Add middleware to a specific FastAPI app.
        
        Args:
            app: FastAPI application instance
            
        Returns:
            bool: True if middleware was successfully added
        """
        return self._add_middleware_to_app_with_retry(app)
    
    def _discover_fastapi_apps(self) -> List:
        """
        Discover FastAPI apps using multiple methods.
        
        Returns:
            List of FastAPI app instances
        """
        apps = []
        
        # Try to import FastAPI
        try:
            from fastapi import FastAPI
        except ImportError:
            logger.debug("🔍 TRACING: FastAPI not available")
            return apps
            
        # Method 1: Garbage collector discovery (current approach)
        gc_apps = self._discover_apps_via_gc(FastAPI)
        logger.debug(f"🔍 TRACING: GC discovery found {len(gc_apps)} apps")
        apps.extend(gc_apps)
        
        # Method 2: Module globals discovery
        module_apps = self._discover_apps_via_modules(FastAPI)
        logger.debug(f"🔍 TRACING: Module discovery found {len(module_apps)} apps")
        apps.extend(module_apps)
        
        # Method 3: Stack frame inspection (new)
        stack_apps = self._discover_apps_via_stack(FastAPI)
        logger.debug(f"🔍 TRACING: Stack discovery found {len(stack_apps)} apps")
        apps.extend(stack_apps)
        
        # Remove duplicates while preserving order
        unique_apps = []
        seen_ids = set()
        for app in apps:
            app_id = id(app)
            if app_id not in seen_ids:
                unique_apps.append(app)
                seen_ids.add(app_id)
                
        logger.debug(f"🔍 TRACING: Discovered {len(unique_apps)} unique FastAPI apps")
        return unique_apps
    
    def _discover_apps_via_gc(self, FastAPI) -> List:
        """Discover FastAPI apps via garbage collector."""
        apps = []
        try:
            for obj in gc.get_objects():
                if isinstance(obj, FastAPI):
                    apps.append(obj)
        except Exception as e:
            logger.debug(f"🔍 TRACING: GC discovery failed: {e}")
        return apps
    
    def _discover_apps_via_modules(self, FastAPI) -> List:
        """Discover FastAPI apps via module globals."""
        apps = []
        try:
            import sys
            for module_name, module in sys.modules.items():
                if module and hasattr(module, '__dict__'):
                    for attr_name, attr_value in module.__dict__.items():
                        if isinstance(attr_value, FastAPI):
                            logger.debug(f"🔍 TRACING: Found FastAPI app '{attr_name}' in module '{module_name}'")
                            apps.append(attr_value)
        except Exception as e:
            logger.debug(f"🔍 TRACING: Module discovery failed: {e}")
        return apps
    
    def _discover_apps_via_stack(self, FastAPI) -> List:
        """Discover FastAPI apps via stack frame inspection."""
        apps = []
        try:
            import inspect
            
            # Look through stack frames for 'app' variables
            for frame_info in inspect.stack():
                frame = frame_info.frame
                try:
                    # Check frame locals and globals for FastAPI instances
                    for var_dict in [frame.f_locals, frame.f_globals]:
                        for var_name, var_value in var_dict.items():
                            if isinstance(var_value, FastAPI):
                                logger.debug(f"🔍 TRACING: Found FastAPI app '{var_name}' in stack frame")
                                apps.append(var_value)
                finally:
                    # Avoid reference cycles
                    del frame
        except Exception as e:
            logger.debug(f"🔍 TRACING: Stack discovery failed: {e}")
        return apps
    
    def _add_middleware_to_app_with_retry(self, app) -> bool:
        """
        Add middleware to a single app with retry logic.
        
        Args:
            app: FastAPI application instance
            
        Returns:
            bool: True if middleware was successfully added
        """
        app_id = id(app)
        app_title = getattr(app, 'title', 'Unknown FastAPI App')
        
        # Skip if already processed
        if app_id in self._processed_apps:
            logger.debug(f"🔍 TRACING: App '{app_title}' already processed, skipping")
            return False
            
        logger.debug(f"🔍 TRACING: Processing app '{app_title}' (app_{app_id})")
        
        # Check if middleware already exists
        if self._has_tracing_middleware(app):
            logger.debug(f"🔍 TRACING: App '{app_title}' already has tracing middleware")
            self._processed_apps.add(app_id)
            return False
            
        # Check if app can accept middleware
        if not self._can_add_middleware(app):
            logger.debug(f"🔍 TRACING: App '{app_title}' cannot accept middleware (already started)")
            return False
            
        # Attempt to add middleware with retry logic
        for attempt in range(3):
            try:
                self._add_middleware_to_app(app)
                logger.debug(f"🔍 TRACING: Successfully added middleware to '{app_title}' on attempt {attempt + 1}")
                self._processed_apps.add(app_id)
                return True
                
            except Exception as e:
                error_msg = str(e)
                if "Cannot add middleware after an application has started" in error_msg:
                    if attempt < 2:
                        logger.debug(f"🔍 TRACING: App startup timing issue for '{app_title}', retrying in 50ms...")
                        time.sleep(0.05)  # Brief delay
                        continue
                    else:
                        logger.debug(f"🔍 TRACING: App '{app_title}' already started after {attempt + 1} attempts")
                        return False
                else:
                    logger.debug(f"🔍 TRACING: Failed to add middleware to '{app_title}': {e}")
                    return False
                    
        return False
    
    def _can_add_middleware(self, app) -> bool:
        """
        Check if middleware can be added to the app.
        
        Args:
            app: FastAPI application instance
            
        Returns:
            bool: True if middleware can be added
        """
        try:
            # Check for obvious signs the app has started
            if hasattr(app, '_server') and app._server is not None:
                return False
                
            # Check app state
            if hasattr(app, 'state') and hasattr(app.state, 'started'):
                if app.state.started:
                    return False
                    
            # Try a harmless test - check if we can access middleware list
            if hasattr(app, 'user_middleware'):
                # If we can access this without error, app is likely still configurable
                return True
                
            return True
            
        except Exception as e:
            logger.debug(f"🔍 TRACING: Middleware capability check failed: {e}")
            return False
    
    def _has_tracing_middleware(self, app) -> bool:
        """
        Check if the app already has our tracing middleware.
        
        Args:
            app: FastAPI application instance
            
        Returns:
            bool: True if tracing middleware is already present
        """
        try:
            if hasattr(app, 'user_middleware'):
                for middleware in app.user_middleware:
                    if hasattr(middleware, 'cls'):
                        # Check for both old and new middleware names
                        middleware_name = middleware.cls.__name__
                        if middleware_name in ('MCPMeshTracingMiddleware', 'FastAPITracingMiddleware'):
                            return True
            return False
        except Exception as e:
            logger.debug(f"🔍 TRACING: Middleware detection failed: {e}")
            return False
    
    def _add_middleware_to_app(self, app):
        """Add dedicated FastAPI tracing middleware to a single FastAPI app."""
        from ..tracing.fastapi_tracing_middleware import FastAPITracingMiddleware
        
        # Add the dedicated FastAPI tracing middleware
        app.add_middleware(FastAPITracingMiddleware, logger_instance=logger)
        logger.debug(f"🔍 TRACING: Added dedicated FastAPI tracing middleware to app")
    
    def get_stats(self) -> dict:
        """
        Get statistics about processed apps.
        
        Returns:
            dict: Statistics about middleware injection
        """
        return {
            "processed_apps_count": len(self._processed_apps),
            "processed_app_ids": list(self._processed_apps),
        }


# Global instance for reuse
_middleware_manager: Optional[FastAPIMiddlewareManager] = None


def get_fastapi_middleware_manager() -> FastAPIMiddlewareManager:
    """Get or create global FastAPI middleware manager instance."""
    global _middleware_manager
    if _middleware_manager is None:
        _middleware_manager = FastAPIMiddlewareManager()
    return _middleware_manager