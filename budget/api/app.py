"""
Budget Component API Server

This module initializes and runs the Budget API server, which provides endpoints
for budget management, allocation, and reporting.
"""

import os
import sys
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional, Union
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add the parent directory to sys.path to ensure package imports work correctly
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Add shared utils to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../shared/utils')))
try:
    from health_check import create_health_response
    from hermes_registration import HermesRegistration, heartbeat_loop
except ImportError as e:
    logging.warning(f"Could not import shared utils: {e}")
    create_health_response = None
    HermesRegistration = None

# Try to import debug_utils from shared if available
try:
    from shared.debug.debug_utils import debug_log, log_function
except ImportError:
    # Create a simple fallback if shared module is not available
    class DebugLog:
        def __getattr__(self, name):
            def dummy_log(*args, **kwargs):
                pass
            return dummy_log
    debug_log = DebugLog()
    
    def log_function(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

# Import API endpoints
from budget.api.endpoints import router as budget_router
from budget.api.mcp_endpoints import mcp_router
from budget.api.assistant_endpoints import router as assistant_router
from budget.api.models import ErrorResponse
from budget.data.repository import db_manager

# Import Hermes helper for service registration
from budget.utils.hermes_helper import register_budget_component

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("budget_api")

# Global state for Hermes registration
is_registered_with_hermes = False
hermes_registration = None
heartbeat_task = None

# Create FastAPI app with proper URL paths following Single Port Architecture
app = FastAPI(
    title="Budget API",
    description="API for Tekton Budget component",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development - restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add exception handlers
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"General error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    logger.error(f"HTTP error {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

# Include routers
app.include_router(budget_router)
app.include_router(mcp_router)
app.include_router(assistant_router)

# Health check endpoint
@app.get("/health")
@log_function()
async def health_check():
    """
    Health check endpoint to verify API is running.
    """
    debug_log.info("budget_api", "Health check endpoint called")
    
    # Use standardized health response if available
    if create_health_response:
        return create_health_response(
            component_name="budget",
            port=8013,
            version="0.1.0",
            status="healthy",
            registered=is_registered_with_hermes,
            details={
                "services": ["budget_allocation", "cost_tracking", "assistant_service"]
            }
        )
    else:
        # Fallback to manual format
        return {
            "status": "healthy",
            "version": "0.1.0",
            "timestamp": datetime.now().isoformat(),
            "component": "budget",
            "port": 8013,
            "registered_with_hermes": is_registered_with_hermes,
            "details": {
                "services": ["budget_allocation", "cost_tracking", "assistant_service"]
            }
        }

# Root endpoint
@app.get("/")
async def root():
    """
    Root endpoint with basic information.
    """
    debug_log.info("budget_api", "Root endpoint called")
    return {
        "component": "budget",
        "description": "Tekton Budget Component API",
        "version": "0.1.0",
        "status": "active"
    }

# Import WebSocket manager and handlers
from budget.api.websocket_server import (
    ConnectionManager, add_websocket_routes,
    notify_budget_update, notify_allocation_update, notify_alert, notify_price_update
)

# Create WebSocket connection manager
ws_manager = ConnectionManager()

# Global variable to store Hermes registration client
hermes_client = None

# On startup handlers
@app.on_event("startup")
@log_function()
async def startup_event():
    """
    Initialization tasks on application startup.
    """
    global hermes_client, is_registered_with_hermes, hermes_registration, heartbeat_task
    debug_log.info("budget_api", "Initializing Budget API server")
    
    # Initialize database
    db_manager.initialize()
    
    # Construct the endpoint URL based on the port
    port = os.environ.get("BUDGET_PORT", "8013")
    hostname = os.environ.get("BUDGET_HOST", "localhost")
    endpoint = f"http://{hostname}:{port}"
    
    debug_log.info("budget_api", f"Registering with Hermes using endpoint: {endpoint}")
    
    try:
        hermes_client = await register_budget_component(endpoint)
        if hermes_client:
            debug_log.info("budget_api", "Successfully registered with Hermes")
        else:
            debug_log.warn("budget_api", "Failed to register with Hermes, continuing startup")
    except Exception as e:
        debug_log.error("budget_api", f"Error registering with Hermes: {str(e)}")
    
    # Initialize WebSocket routes
    from budget.core.engine import get_budget_engine
    budget_engine = await get_budget_engine()
    add_websocket_routes(app, ws_manager, budget_engine)
    
    # Initialize FastMCP if available
    try:
        from tekton.mcp.fastmcp import MCPClient
        from tekton.mcp.fastmcp.utils.tooling import ToolRegistry
        from budget.core.mcp import register_budget_tools, register_analytics_tools
        
        # Create tool registry
        tool_registry = ToolRegistry()
        
        # Register budget tools with the registry
        await register_budget_tools(budget_engine, tool_registry)
        await register_analytics_tools(budget_engine, tool_registry)
        
        debug_log.info("budget_api", "Successfully registered FastMCP tools")
    except ImportError:
        debug_log.warn("budget_api", "FastMCP not available, continuing with legacy MCP")
    except Exception as e:
        debug_log.error("budget_api", f"Error registering FastMCP tools: {str(e)}")
    
    # Register with Hermes using standardized registration
    if HermesRegistration:
        hermes_registration = HermesRegistration()
        is_registered_with_hermes = await hermes_registration.register_component(
            component_name="budget",
            port=8013,
            version="0.1.0",
            capabilities=[
                "budget_allocation",
                "cost_tracking",
                "usage_monitoring",
                "assistant_service",
                "websocket_support"
            ],
            metadata={
                "database": "enabled",
                "assistant": "enabled",
                "websocket": "enabled"
            }
        )
        
        # Start heartbeat task if registered
        if is_registered_with_hermes:
            heartbeat_task = asyncio.create_task(
                heartbeat_loop(hermes_registration, "budget", interval=30)
            )
            debug_log.info("budget_api", "Started Hermes heartbeat task")
    
    debug_log.info("budget_api", "Budget API server initialized with WebSocket support")

# On shutdown handlers
@app.on_event("shutdown")
@log_function()
async def shutdown_event():
    """
    Cleanup tasks on application shutdown.
    """
    global hermes_client, heartbeat_task
    debug_log.info("budget_api", "Shutting down Budget API server")
    
    # Cancel heartbeat task
    if heartbeat_task:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
    
    # Deregister from Hermes
    if hermes_registration and is_registered_with_hermes:
        await hermes_registration.deregister("budget")
    
    # Unregister from Hermes service registry (legacy)
    if hermes_client:
        debug_log.info("budget_api", "Unregistering from Hermes")
        try:
            await hermes_client.close()
            debug_log.info("budget_api", "Successfully unregistered from Hermes")
        except Exception as e:
            debug_log.error("budget_api", f"Error unregistering from Hermes: {str(e)}")
    
    # Clean up WebSocket connections
    ws_manager.cleanup()
    debug_log.info("budget_api", "WebSocket connections cleaned up")
    
    # Close database connections
    db_manager.close()
    
    debug_log.info("budget_api", "Budget API server shutdown complete")

# Main function to run the API server
def main():
    """
    Run the Budget API server using uvicorn.
    """
    debug_log.info("budget_api", "Starting Budget API server")
    import uvicorn
    
    # Use the standardized BUDGET_PORT environment variable from Single Port Architecture
    port = int(os.environ.get("BUDGET_PORT", "8013"))
    
    debug_log.info("budget_api", f"Using port {port} from BUDGET_PORT environment variable")
    
    uvicorn.run(
        "budget.api.app:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("BUDGET_API_RELOAD", "false").lower() == "true",
        log_level=os.environ.get("BUDGET_API_LOG_LEVEL", "info").lower()
    )

if __name__ == "__main__":
    main()