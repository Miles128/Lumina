"""CLI entrypoint."""

from __future__ import annotations

import argparse

import uvicorn

from secretary.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Lumina local backend")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()

    uvicorn.run(
        "secretary.api.app:app",
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
