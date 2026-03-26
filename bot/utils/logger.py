"""
bot/utils/logger.py
~~~~~~~~~~~~~~~~~~~
Configures the standard-library ``logging`` module for the entire bot.

A single ``setup_logger`` helper returns a named logger that writes to
*stdout* (container-friendly) with a consistent format.
"""

import logging
import sys


def setup_logger(name: str = "bot", level: str = "INFO") -> logging.Logger:
    """Create and return a logger with a stream handler.

    Parameters
    ----------
    name:
        Logger name (typically the package name).
    level:
        Logging level string (``DEBUG``, ``INFO``, …).

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers when called more than once.
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logger.level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
