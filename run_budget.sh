#!/bin/bash
# Budget component - Launch Script

# Default port (can be overridden by environment variable)
export BUDGET_PORT=${BUDGET_PORT:-8013}

# Ensure we're in the right directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR" || exit 1

# Add Tekton root to Python path
TEKTON_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$SCRIPT_DIR:$TEKTON_ROOT:$PYTHONPATH"

# Check if port is already in use
if nc -z localhost $BUDGET_PORT 2>/dev/null; then
    echo "Budget is already running on port $BUDGET_PORT"
    exit 0
fi

echo "Starting Budget on port $BUDGET_PORT..."

# Start the Budget service using custom socket server for proper port reuse
python -c "
from shared.utils.socket_server import run_component_server
run_component_server('budget', 'budget.api.app', 8013)
"