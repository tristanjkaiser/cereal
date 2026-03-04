#!/usr/bin/env python3
"""Cereal web app entry point.

Usage:
    python web/run.py                  # Start on port 5555
    python web/run.py --port 8080      # Custom port
    python web/run.py --open           # Auto-open browser
    python web/run.py --debug          # Debug mode
"""
import argparse
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def main():
    parser = argparse.ArgumentParser(description="Cereal Web Dashboard")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("DASHBOARD_PORT", "5555")),
    )
    parser.add_argument("--open", action="store_true", help="Open browser on start")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    from web import create_app

    app = create_app()

    url = f"http://localhost:{args.port}"
    print(f"Cereal running at {url}")

    if args.open:
        import webbrowser
        webbrowser.open(url)

    app.run(host="127.0.0.1", port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
