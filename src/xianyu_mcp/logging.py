"""Logging configuration."""

import logging
import sys
from typing import Optional

from .config import get_settings


def setup_logging(level: Optional[str] = None) -> logging.Logger:
    """Set up logging configuration."""
    settings = get_settings()
    log_level = level or settings.log_level

    # Create logger
    logger = logging.getLogger("xianyu_mcp")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG)

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(console_handler)

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger instance."""
    if name:
        return logging.getLogger(f"xianyu_mcp.{name}")
    return logging.getLogger("xianyu_mcp")


# Initialize logging on import
_logger: Optional[logging.Logger] = None


def init_logging() -> logging.Logger:
    """Initialize logging (singleton)."""
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger
