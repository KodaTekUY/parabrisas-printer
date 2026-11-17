"""Entrada con logging configurado antes del arranque de Uvicorn."""

import argparse

import uvicorn

from .config import LoggingSettings
from .logging_config import configure_logging, shutdown_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente local de impresión")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    configure_logging(LoggingSettings())
    try:
        uvicorn.run("app.main:app", host=args.host, port=args.port, workers=1, log_config=None)
    finally:
        shutdown_logging()


if __name__ == "__main__":
    main()
