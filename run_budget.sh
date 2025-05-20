#!/bin/bash

# run_budget.sh - Script to run the Budget component of Tekton
# This script starts the Budget API server and related services

# Set environment variables
export TEKTON_DEBUG=true
export TEKTON_LOG_LEVEL=DEBUG

# Determine the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Navigate to the script directory
cd "$SCRIPT_DIR"

# Check if we're in a virtual environment, if not try to activate one
if [[ -z "$VIRTUAL_ENV" ]]; then
    if [[ -d "venv" ]]; then
        echo "Activating virtual environment..."
        source venv/bin/activate
    elif [[ -d "../venv" ]]; then
        echo "Activating parent virtual environment..."
        source ../venv/bin/activate
    else
        echo "No virtual environment found. Running with system Python."
    fi
fi

# Check if required packages are installed
if ! python -c "import fastapi" &> /dev/null; then
    echo "Installing required packages..."
    pip install -r requirements.txt
fi

# Install package in development mode if not already installed
if ! python -c "import budget" &> /dev/null; then
    echo "Installing budget package in development mode..."
    pip install -e .
fi

# Start the Budget API server
echo "Starting Budget API server..."
python -m budget.api.app