"""Import-time configuration singleton with explicit TOML and CLI layers."""

import argparse
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import ClassVar

import tomllib


@dataclass(frozen=True)
class HttpConfig:
    """Default HTTP transport settings; no clients are created here."""

    timeout: float = 5.0
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: float = 5.0


@dataclass(frozen=True)
class GarminConnectClientConfig:
    """Garmin credentials and HTTP pool settings."""

    api_key_string: str = field(default="", repr=False)
    api_key_file: str = "config/API_KEY.txt"
    http_client_pool_size: int = 10
    http_client_name: str = "GarminConnect"
    base_url: str = "https://personal.connectapi.garmin.com"
    timeout: float = 5.0
    max_keepalive_connections: int = 10
    keepalive_expiry: float = 5.0


@dataclass(frozen=True)
class ConsoleLoggingConfig:
    """Console handler settings; output is intended for stderr."""

    enabled: bool = True
    level: str = "INFO"


@dataclass(frozen=True)
class FileLoggingConfig:
    """Rotating file handler settings."""

    enabled: bool = False
    level: str = "INFO"
    path: str = "logs/daybreak.log"
    max_bytes: int = 10485760
    backup_count: int = 3


@dataclass(frozen=True)
class LoggingConfig:
    """Shared logger level and independent output settings."""

    level: str = "INFO"
    console: ConsoleLoggingConfig = field(default_factory=ConsoleLoggingConfig)
    file: FileLoggingConfig = field(default_factory=FileLoggingConfig)


@dataclass(frozen=True)
class ConfigData:
    """Hierarchical application configuration schema."""

    Logging: LoggingConfig = field(default_factory=LoggingConfig)
    GeneralHttpClient: HttpConfig = field(default_factory=HttpConfig)
    GarminConnectClient: GarminConnectClientConfig = field(
        default_factory=GarminConnectClientConfig
    )


def _merge(data, updates: Mapping, prefix: str = ""):
    if not isinstance(updates, Mapping):
        raise TypeError(f"{prefix or 'configuration'} must be a mapping.")
    known = {item.name for item in fields(data)}
    result = {}
    for key, value in updates.items():
        if key not in known:
            raise ValueError(f"Unknown configuration field: {prefix}{key}")
        current = getattr(data, key)
        path = f"{prefix}{key}"
        if is_dataclass(current):
            result[key] = _merge(current, value, f"{path}.")
        else:
            expected = type(current)
            valid = type(value) is expected or (
                expected is float and type(value) is int
            )
            if not valid:
                raise TypeError(f"{path} must be {expected.__name__}.")
            if expected in (int, float) and (
                not math.isfinite(value) or value < 0
                or (key in ("max_connections", "max_bytes", "backup_count", "http_client_pool_size") and value == 0)
            ):
                raise ValueError(f"Invalid value for {path}.")
            if key == "level" and value not in {
                "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "NOTSET"
            }:
                raise ValueError(f"Invalid logging level for {path}.")
            if key == "path" and not value.strip():
                raise ValueError(f"{path} must not be empty.")
            if key == "api_key_file" and value:
                key_path = Path(value)
                if key_path.is_absolute() or ".." in key_path.parts:
                    raise ValueError(f"{path} must be a repository-relative path without '..'.")
            result[key] = expected(value)
    return replace(data, **result)


class GlobalConfig:
    """One process-local instance; configure explicitly during startup.

    Layers are retained separately so CLI values always win, even when a
    TOML file is loaded later. Updates validate before publishing a snapshot.
    Startup updates are intended for a single thread.
    """

    _instance: ClassVar["GlobalConfig | None"] = None

    def __new__(cls):
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._toml = {}
            instance._cli = {}
            instance._data = ConfigData()
            cls._instance = instance
        return cls._instance

    @property
    def Logging(self) -> LoggingConfig:
        return self._data.Logging

    @property
    def GeneralHttpClient(self) -> HttpConfig:
        return self._data.GeneralHttpClient

    @property
    def GarminConnectClient(self) -> GarminConnectClientConfig:
        return self._data.GarminConnectClient

    def update_from_toml(self, path: str | Path) -> None:
        """Replace the TOML layer using a UTF-8 mapping parsed by tomllib."""
        with Path(path).open("rb") as stream:
            updates = tomllib.load(stream)
        candidate = _merge(ConfigData(), updates)
        candidate = _merge(candidate, self._cli)
        self._toml = updates
        self._data = candidate

    def update_from_cli(self, args: Sequence[str] | None = None) -> None:
        """Replace the CLI layer; None explicitly parses sys.argv[1:]."""
        parser = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)

        def add_fields(data, prefix=""):
            for item in fields(data):
                value = getattr(data, item.name)
                name = f"{prefix}{item.name}"
                if is_dataclass(value):
                    add_fields(value, f"{name}.")
                elif type(value) is bool:
                    parser.add_argument(
                        f"--{name.replace('_', '-')}", dest=name,
                        action=argparse.BooleanOptionalAction,
                    )
                else:
                    parser.add_argument(f"--{name.replace('_', '-')}",
                                        dest=name, type=type(value))

        add_fields(ConfigData())
        parsed = vars(parser.parse_args(args))
        updates = {}
        for name, value in parsed.items():
            target = updates
            *parents, leaf = name.split(".")
            for parent in parents:
                target = target.setdefault(parent, {})
            target[leaf] = value
        candidate = _merge(_merge(ConfigData(), self._toml), updates)
        self._cli = updates
        self._data = candidate


global_config = GlobalConfig()
