#!/bin/bash
# Cereal MCP Server launcher
# Portable version - works from any installation directory

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

export PYTHONPATH="${PYTHONPATH}:${PROJECT_DIR}"
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost:5432/cereal}"

exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/server.py"
