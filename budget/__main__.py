"""Entry point for python -m budget"""
from budget.api.app import app
import uvicorn
import os

if __name__ == "__main__":
    port = int(os.environ.get("BUDGET_PORT", 8013))
    uvicorn.run(app, host="0.0.0.0", port=port)