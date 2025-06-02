"""Main entry point for running Budget API server."""
import uvicorn
import os
from budget.api.app import app

if __name__ == "__main__":
    port = int(os.environ.get("BUDGET_PORT", "8013"))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )