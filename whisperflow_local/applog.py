"""Minimal local logging. Metadata-only by default; transcript text is logged
only when config opts in. Logs rotate by size.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from .paths import AppPaths


def get_logger(metadata_only: bool = True) -> logging.Logger:
    log_dir = AppPaths.discover().ensure().logs
    logger = logging.getLogger("whisperflow_local")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger._metadata_only = metadata_only  # type: ignore[attr-defined]
    return logger
