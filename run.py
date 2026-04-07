"""
Run script for eCommerce Smart DSS v2.
Usage:
    python run.py                  # Start backend only
    python run.py --port 8000      # Custom port
    python run.py --reload         # Dev mode with auto-reload
"""

import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="eCommerce Smart DSS Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
