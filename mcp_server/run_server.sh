#!/bin/bash
# Cereal MCP Server launcher
# Uses uv for dependency management

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

export PYTHONPATH="${PYTHONPATH}:${PROJECT_DIR}"
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost:5432/cereal}"

exec uv run --directory "$SCRIPT_DIR" python server.py
