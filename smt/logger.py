import logging
import logging.handlers
from pathlib import Path

from smt.core.config import get_settings


settings = get_settings()

LOGS_DIR = Path(settings.LOG_DIR)
LOGS_DIR.mkdir(exist_ok=True)


def setup_logger(name: str = "smt", log_file: str = None, level: str = "INFO") -> logging.Logger:
    """
    Setup logger with both console and file handlers

    :param name: Logger name (used for hierarchical logging)
    :param log_file: Optional specific log file name
    :param level: Logging level
    :return: logger
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper()))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler
    if log_file:
        file_path = LOGS_DIR / log_file
    else:
        file_path = LOGS_DIR / f"{name}.log"

    file_handler = logging.handlers.RotatingFileHandler(
        file_path, maxBytes=settings.LOG_FILE_MAX_SIZE, backupCount=settings.LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s [%(filename)s:%(lineno)d] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    logger.propagate = False

    return logger


def get_logger(name: str = None) -> logging.Logger:
    """Get a logger instance with hierarchical naming"""
    if name:
        # Create hierarchical logger (e.g., "smt.services.pool")
        full_name = f"smt.{name}"
    else:
        full_name = "smt"

    return logging.getLogger(full_name)


def setup_all_loggers():
    """Setup all application loggers"""

    # Main application logger
    setup_logger("smt", "app.log", level=settings.LOG_LEVEL)

    # Worker logger
    setup_logger("smt.worker", "worker.log", level=settings.LOG_LEVEL)

    # Services logger
    setup_logger("smt.services", "services.log", level=settings.LOG_LEVEL)

    # Repositories logger
    setup_logger("smt.repositories", "repositories.log", level=settings.LOG_LEVEL)

    # API logger
    setup_logger("smt.api", "api.log", level=settings.LOG_LEVEL)
