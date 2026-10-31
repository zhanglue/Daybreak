"""Import-time configuration singleton with explicit TOML and CLI layers."""

import argparse
import math
from ipaddress import ip_address
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tomllib


@dataclass(frozen=True)
class MCPServerConfig:
    """Local MCP data source, storage, and freshness settings."""

    transport: str = "http"
    host: str = "127.0.0.1"
    port: int = 15666
    path: str = "/mcp"
    data_source: str = "garmin_connect"
    data_directory: str = "garmin_data"
    timezone_name: str = "UTC"
    recent_days: int = 7
    recent_ttl_seconds: int = 3600
    profile_ttl_seconds: int = 86400

    def __post_init__(self):
        message = None
        if self.transport not in ('http', 'stdio'):
            message = "MCPServer.transport must be http or stdio."
        elif not 1 <= self.port <= 65535:
            message = "MCPServer.port must be between 1 and 65535."
        elif (not self.path.startswith('/') or self.path == '/' or
              any(part in ('.', '..', '') for part in self.path[1:].split('/')) or
              any(character in self.path for character in ('?', '#', '%', '\\')) or
              any(character.isspace() for character in self.path)):
            message = "MCPServer.path must be an absolute HTTP path without query or traversal."
        elif self.host != 'localhost':
            try:
                if not ip_address(self.host).is_loopback:
                    message = "MCPServer.host must be a loopback address or localhost."
            except ValueError:
                message = "MCPServer.host must be a loopback address or localhost."
        if message is None and (self.recent_days < 0 or min(self.recent_ttl_seconds, self.profile_ttl_seconds) <= 0):
            message = "Invalid MCPServer freshness settings."
        elif message is None and not self.data_directory.strip():
            message = "MCPServer.data_directory must not be empty."
        elif message is None:
            try:
                ZoneInfo(self.timezone_name)
            except (ZoneInfoNotFoundError, ValueError):
                message = "MCPServer.timezone_name must be a valid IANA timezone."
        if message is not None:
            from logger import Logger
            Logger.ERROR(message)
            raise ValueError(message)


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
class HttpConfig:
    """Default HTTP transport settings; no clients are created here."""

    timeout: float = 5.0
    max_connections: int = 100
    max_keepalive_connections: int = 20
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

    MCPServer: MCPServerConfig = field(default_factory=MCPServerConfig)
    GarminConnectClient: GarminConnectClientConfig = field(
        default_factory=GarminConnectClientConfig
    )
    GeneralHttpClient: HttpConfig = field(default_factory=HttpConfig)
    Logging: LoggingConfig = field(default_factory=LoggingConfig)


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
    def MCPServer(self) -> MCPServerConfig:
        return self._data.MCPServer

    @property
    def GarminConnectClient(self) -> GarminConnectClientConfig:
        return self._data.GarminConnectClient

    @property
    def GeneralHttpClient(self) -> HttpConfig:
        return self._data.GeneralHttpClient

    @property
    def Logging(self) -> LoggingConfig:
        return self._data.Logging

    def to_display_dict(self) -> dict:
        """Return all effective settings in schema order, masking hidden fields."""
        def display(data):
            return {
                item.name: (
                    "********" if not item.repr else
                    display(getattr(data, item.name)) if is_dataclass(getattr(data, item.name)) else
                    getattr(data, item.name)
                )
                for item in fields(data)
            }

        return display(self._data)

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
