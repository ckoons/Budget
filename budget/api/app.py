"""
Budget Component API Server

This module initializes and runs the Budget API server, which provides endpoints
for budget management, allocation, and reporting.
"""

import os
import sys
import logging
import asyncio
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add the parent directory to sys.path to ensure package imports work correctly
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

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

# Include budget router
app.include_router(budget_router)

# Health check endpoint
@app.get("/health")
@log_function()
async def health_check():
    """
    Health check endpoint to verify API is running.
    """
    debug_log.info("budget_api", "Health check endpoint called")
    return {"status": "healthy", "component": "budget"}

# Root endpoint
@app.get("/")
@log_function()
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

# Standard health endpoint
@app.get("/health")
@log_function()
async def health():
    """
    Standard health check endpoint following Tekton conventions.
    """
    debug_log.info("budget_api", "Health check endpoint called")
    return {
        "status": "healthy",
        "component": "budget",
        "version": "0.1.0",
        "timestamp": str(datetime.now())
    }

# Global variable to store Hermes registration client
hermes_client = None

# On startup handlers
@app.on_event("startup")
@log_function()
async def startup_event():
    """
    Initialization tasks on application startup.
    """
    debug_log.info("budget_api", "Initializing Budget API server")
    
    # Initialize database
    db_manager.initialize()
    
    # Register with Hermes service registry
    global hermes_client
    
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
    
    debug_log.info("budget_api", "Budget API server initialized")

# On shutdown handlers
@app.on_event("shutdown")
@log_function()
async def shutdown_event():
    """
    Cleanup tasks on application shutdown.
    """
    debug_log.info("budget_api", "Shutting down Budget API server")
    
    # Unregister from Hermes service registry
    global hermes_client
    if hermes_client:
        debug_log.info("budget_api", "Unregistering from Hermes")
        try:
            await hermes_client.close()
            debug_log.info("budget_api", "Successfully unregistered from Hermes")
        except Exception as e:
            debug_log.error("budget_api", f"Error unregistering from Hermes: {str(e)}")
    
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