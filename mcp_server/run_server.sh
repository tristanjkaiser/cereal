#!/bin/bash
# Cereal MCP Server launcher
# Uses uv for dependency management

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

export PYTHONPATH="${PYTHONPATH}:${PROJECT_DIR}"
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost:5432/cereal}"

# Find uv: check PATH, then common install locations
if command -v uv &> /dev/null; then
    UV_BIN="uv"
elif [ -x "$HOME/.local/bin/uv" ]; then
    UV_BIN="$HOME/.local/bin/uv"
elif [ -x "$HOME/.cargo/bin/uv" ]; then
    UV_BIN="$HOME/.cargo/bin/uv"
else
    echo "Error: uv not found. Install it: https://docs.astral.sh/uv/" >&2
    exit 1
fi

exec "$UV_BIN" run --directory "$SCRIPT_DIR" python server.py
