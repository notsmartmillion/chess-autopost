"""Logging configuration using loguru."""

import sys
from loguru import logger
from typing import Optional


def get_logger(name: str) -> logger:
    """Get a logger instance for the given module name."""
    return logger.bind(module=name)


def setup_logging(level: str = "INFO", log_file: Optional[str] = None):
    """Setup logging configuration."""
    # Remove default handler
    logger.remove()
    
    # Add console handler
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{module}</cyan> | <level>{message}</level>",
        colorize=True
    )
    
    # Add file handler if specified
    if log_file:
        logger.add(
            log_file,
            level=level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module} | {message}",
            rotation="10 MB",
            retention="7 days"
        )
    
    logger.info(f"Logging configured with level: {level}")


# Default setup
setup_logging()
