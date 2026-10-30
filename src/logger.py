"""Process-local logging configured lazily from GlobalConfig."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock

from global_config import GlobalConfig


class Logger:
    """Shared logger; load configuration before the first logging call.

    Configuration is captured once. Call close() after logging has stopped
    to release handlers; the next call initializes from current settings.
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._logger = cls._create_logger()
                    cls._instance = instance
        return cls._instance

    @staticmethod
    def _create_logger():
        config = GlobalConfig().Logging
        backend = logging.Logger("daybreak", level=config.level)
        backend.propagate = False
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        try:
            if config.console.enabled:
                handler = logging.StreamHandler()
                backend.addHandler(handler)
                handler.setLevel(config.console.level)
                handler.setFormatter(formatter)
            if config.file.enabled:
                path = Path(config.file.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(
                    path, maxBytes=config.file.max_bytes,
                    backupCount=config.file.backup_count, encoding="utf-8",
                )
                backend.addHandler(handler)
                handler.setLevel(config.file.level)
                handler.setFormatter(formatter)
            # Avoid logging's lastResort stderr output when all outputs are off.
            backend.addHandler(logging.NullHandler())
        except Exception:
            for handler in backend.handlers[:]:
                backend.removeHandler(handler)
                handler.close()
            raise
        return backend

    @classmethod
    def DEBUG(cls, message, *args, **kwargs):
        """Log a DEBUG message with standard logging keyword arguments."""
        kwargs["stacklevel"] = kwargs.get("stacklevel", 1) + 1
        cls()._logger.debug(message, *args, **kwargs)

    @classmethod
    def INFO(cls, message, *args, **kwargs):
        """Log an INFO message with standard logging keyword arguments."""
        kwargs["stacklevel"] = kwargs.get("stacklevel", 1) + 1
        cls()._logger.info(message, *args, **kwargs)

    @classmethod
    def ERROR(cls, message, *args, **kwargs):
        """Log an ERROR message; exc_info=True includes the active exception."""
        kwargs["stacklevel"] = kwargs.get("stacklevel", 1) + 1
        cls()._logger.error(message, *args, **kwargs)

    @classmethod
    def close(cls):
        """Release handlers after callers have stopped logging."""
        with cls._lock:
            instance = cls._instance
            cls._instance = None
            if instance is not None:
                for handler in instance._logger.handlers[:]:
                    instance._logger.removeHandler(handler)
                    handler.close()
