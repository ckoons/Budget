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

# Add Tekton root to path for shared imports
tekton_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if tekton_root not in sys.path:
    sys.path.append(tekton_root)

# Import shared utils
from shared.utils.health_check import create_health_response
from shared.utils.hermes_registration import HermesRegistration, heartbeat_loop
from shared.utils.logging_setup import setup_component_logging
from shared.utils.shutdown import component_lifespan
from shared.utils.env_config import get_component_config
from shared.utils.startup import component_startup, StartupMetrics
from shared.utils.errors import StartupError
from shared.api import (
    create_standard_routers,
    mount_standard_routers,
    create_ready_endpoint,
    create_discovery_endpoint,
    get_openapi_configuration,
    EndpointInfo
)

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

# Configure logging using shared utility
logger = setup_component_logging("budget")

# Component configuration
COMPONENT_NAME = "budget"
COMPONENT_VERSION = "0.1.0"
COMPONENT_DESCRIPTION = "Budget management and cost tracking component"
start_time = None
is_registered_with_hermes = False
hermes_registration = None
heartbeat_task = None
mcp_bridge = None

# Import WebSocket manager and handlers
from budget.api.websocket_server import (
    ConnectionManager, add_websocket_routes,
    notify_budget_update, notify_allocation_update, notify_alert, notify_price_update
)

# Create WebSocket connection manager
ws_manager = ConnectionManager()

# Define startup and cleanup functions for lifespan
async def startup_tasks():
    """Initialize Budget services."""
    global is_registered_with_hermes, hermes_registration, heartbeat_task, start_time
    import time
    start_time = time.time()
    logger.info("Initializing Budget API server")
    
    # Initialize database
    db_manager.initialize()
    
    # Get configuration
    config = get_component_config()
    port = config.budget.port if hasattr(config, 'budget') else int(os.environ.get("BUDGET_PORT", 8013))
    
    # Initialize WebSocket routes
    from budget.core.engine import get_budget_engine
    budget_engine = get_budget_engine()
    add_websocket_routes(app, ws_manager, budget_engine)
    
    # Initialize FastMCP if available
    try:
        from tekton.mcp.fastmcp import MCPClient
        from tekton.mcp.fastmcp.utils.tooling import ToolRegistry
        from budget.core.mcp import register_budget_tools, register_analytics_tools
        
        # Create tool registry
        tool_registry = ToolRegistry(component_name=COMPONENT_NAME)
        
        # Register budget tools with the registry
        await register_budget_tools(budget_engine, tool_registry)
        await register_analytics_tools(budget_engine, tool_registry)
        
        logger.info("Successfully registered FastMCP tools")
        
        # Initialize Hermes MCP Bridge
        from budget.core.mcp.hermes_bridge import BudgetMCPBridge
        global mcp_bridge
        mcp_bridge = BudgetMCPBridge(budget_engine)
        await mcp_bridge.initialize()
        logger.info("Initialized Hermes MCP Bridge for FastMCP tools")
    except ImportError:
        logger.warning("FastMCP not available, continuing with legacy MCP")
    except Exception as e:
        logger.error(f"Error registering FastMCP tools: {str(e)}")
    
    # Register with Hermes using standardized registration
    hermes_registration = HermesRegistration()
    logger.info(f"Attempting to register Budget with Hermes on port {port}")
    is_registered_with_hermes = await hermes_registration.register_component(
        component_name=COMPONENT_NAME,
        port=port,
        version=COMPONENT_VERSION,
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
            heartbeat_loop(hermes_registration, COMPONENT_NAME, interval=30)
        )
        logger.info("Started Hermes heartbeat task")
    
    logger.info("Budget API server initialized with WebSocket support")

async def cleanup_tasks():
    """Cleanup Budget resources."""
    global heartbeat_task
    logger.info("Shutting down Budget API server")
    
    # Cancel heartbeat task
    if heartbeat_task:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
    
    # Deregister from Hermes
    if hermes_registration and is_registered_with_hermes:
        await hermes_registration.deregister(COMPONENT_NAME)
        logger.info("Deregistered from Hermes")
    
    # Clean up WebSocket connections
    ws_manager.cleanup()
    logger.info("WebSocket connections cleaned up")
    
    # Clean up MCP bridge
    global mcp_bridge
    if mcp_bridge:
        try:
            await mcp_bridge.shutdown()
            logger.info("MCP bridge cleaned up")
        except Exception as e:
            logger.warning(f"Error cleaning up MCP bridge: {e}")
    
    # Close database connections
    db_manager.close()
    
    logger.info("Budget API server shutdown complete")

# Create FastAPI app with proper URL paths following Single Port Architecture
app = FastAPI(
    **get_openapi_configuration(
        component_name=COMPONENT_NAME,
        component_version=COMPONENT_VERSION,
        component_description=COMPONENT_DESCRIPTION
    ),
    lifespan=component_lifespan(
        COMPONENT_NAME,
        startup_tasks,
        [cleanup_tasks],
        port=8013
    )
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development - restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create standard routers
routers = create_standard_routers(COMPONENT_NAME)

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

# Health check endpoint
@routers.root.get("/health")
async def health_check():
    """
    Health check endpoint to verify API is running.
    """
    debug_log.info("budget_api", "Health check endpoint called")
    
    # Use standardized health response
    return create_health_response(
        component_name=COMPONENT_NAME,
        port=8013,
        version=COMPONENT_VERSION,
        status="healthy",
        registered=is_registered_with_hermes,
        details={
            "services": ["budget_allocation", "cost_tracking", "assistant_service"]
        }
    )

# Root endpoint
@routers.root.get("/")
async def root():
    """
    Root endpoint with basic information.
    """
    debug_log.info("budget_api", "Root endpoint called")
    return {
        "component": COMPONENT_NAME,
        "description": COMPONENT_DESCRIPTION,
        "version": COMPONENT_VERSION,
        "status": "active"
    }

# Add ready endpoint
routers.root.add_api_route(
    "/ready",
    create_ready_endpoint(
        component_name=COMPONENT_NAME,
        component_version=COMPONENT_VERSION,
        start_time=start_time or 0,
        readiness_check=lambda: is_registered_with_hermes
    ),
    methods=["GET"]
)

# Add discovery endpoint
routers.v1.add_api_route(
    "/discovery",
    create_discovery_endpoint(
        component_name=COMPONENT_NAME,
        component_version=COMPONENT_VERSION,
        component_description=COMPONENT_DESCRIPTION,
        endpoints=[
            EndpointInfo(path="/api/v1/budgets", method="*", description="Budget management"),
            EndpointInfo(path="/api/v1/policies", method="*", description="Budget policies"),
            EndpointInfo(path="/api/v1/allocations", method="*", description="Budget allocations"),
            EndpointInfo(path="/api/v1/usage", method="POST", description="Usage tracking"),
            EndpointInfo(path="/api/v1/alerts", method="GET", description="Budget alerts"),
            EndpointInfo(path="/api/v1/prices", method="GET", description="Pricing information"),
            EndpointInfo(path="/api/v1/assistant", method="POST", description="LLM assistant")
        ],
        capabilities=[
            "budget_allocation",
            "cost_tracking",
            "usage_monitoring",
            "assistant_service",
            "websocket_support"
        ],
        dependencies={
            "hermes": "http://localhost:8001"
        },
        metadata={
            "documentation": "/api/v1/docs",
            "database": "enabled",
            "assistant": "enabled",
            "websocket": "enabled"
        }
    ),
    methods=["GET"]
)

# Mount standard routers
mount_standard_routers(app, routers)

# Include business routers with v1 prefix
routers.v1.include_router(budget_router)
routers.v1.include_router(assistant_router)

# Include MCP router at root (not under v1)
app.include_router(mcp_router)

if __name__ == "__main__":
    from shared.utils.socket_server import run_component_server
    
    run_component_server(
        component_name="budget",
        app_module="budget.api.app",
        default_port=int(os.environ.get("BUDGET_PORT")),
        reload=False
    )