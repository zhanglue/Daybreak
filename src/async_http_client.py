"""Managed asynchronous HTTP clients with application-owned responses and errors."""

import asyncio
import json as json_module
from dataclasses import dataclass, field
from threading import Lock
from types import MappingProxyType
from typing import Any, ClassVar, Dict, Mapping, Optional
from urllib.parse import quote
from uuid import uuid4

import httpx

from logger import Logger


def _credential_values(headers):
    values = []
    for name in ('authorization', 'proxy-authorization', 'cookie', 'x-api-key', 'api-key'):
        value = headers.get(name, '')
        if value:
            values.append(value)
            scheme, separator, credential = value.partition(' ')
            if separator and scheme.lower() in ('bearer', 'basic', 'apikey'):
                values.append(credential)
    return values


def _sensitive_query_key(key):
    normalized = ''.join(character for character in key.lower() if character.isalnum())
    return normalized == 'key' or any(word in normalized for word in (
        'authorization', 'token', 'cookie', 'password', 'secret', 'apikey', 'credential', 'signature',
    ))


class _RequestPreview:
    """Lazily describe the actual wire URL and query, without credentials or bodies."""

    def __init__(self, request):
        self.request = request

    def __str__(self):
        secrets = _credential_values(self.request.headers)
        secrets.extend(value for value in (self.request.url.username, self.request.url.password) if value)
        secrets.extend(value for key, value in self.request.url.params.multi_items()
                       if value and _sensitive_query_key(key))

        def redact(value):
            for secret in secrets:
                value = value.replace(quote(secret, safe=''), '<redacted>').replace(secret, '<redacted>')
            return value

        params = []
        for key, value in self.request.url.params.multi_items():
            params.append((key, '<redacted>' if _sensitive_query_key(key) else redact(value)))
        url = self.request.url.copy_with(username='', password='', fragment='',
                                         query=str(httpx.QueryParams(params)).encode('ascii') if params else None)
        return json_module.dumps(dict(method=self.request.method, url=redact(str(url)),
                                      path=redact(url.path), params=params), ensure_ascii=True)


class _ResponsePreview:
    """Format bounded JSON only when a DEBUG handler formats the record."""

    def __init__(self, response, secrets):
        self.response = response
        self.secrets = secrets

    def __str__(self):
        if len(self.response.content) > 2048:
            return "<body omitted: exceeds 2048 bytes>"

        def redact(value):
            if isinstance(value, dict):
                return {
                    key: "<redacted>" if any(
                        word in key.lower().replace("-", "_")
                        for word in ("authorization", "token", "cookie", "password", "secret", "api_key")
                    ) else redact(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        try:
            preview = json_module.dumps(redact(json_module.loads(self.response.content)), ensure_ascii=True)
        except (ValueError, UnicodeError, RecursionError):
            return "<non-JSON body omitted>"
        for secret in self.secrets:
            if secret:
                preview = preview.replace(json_module.dumps(secret)[1:-1], "<redacted>")
        return preview[:2048]


@dataclass(frozen=True)
class AsyncHttpClientConfig:
    """Creation settings; authentication acquisition belongs to integrations."""

    name: str = "default"
    base_url: str = ""
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    bearer_token: Optional[str] = field(default=None, repr=False)
    timeout: Optional[float] = 5.0
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: Optional[float] = 5.0


@dataclass(frozen=True)
class HttpResponse:
    """A buffered response detached from HTTPX and its request credentials."""

    status_code: int
    headers: Mapping[str, str] = field(repr=False)
    content: bytes = field(repr=False)
    text: str = field(repr=False)

    def json(self) -> Any:
        """Decode JSON on demand; malformed JSON raises JSONDecodeError."""
        try:
            return json_module.loads(self.content)
        except (ValueError, UnicodeError):
            err_msg = "HTTP response JSON decoding failed."
            Logger.ERROR(err_msg)
            raise


class HttpClientError(Exception):
    """Base error for HTTP execution; messages omit URLs and credentials."""

    def __init__(self, message: str, response: Optional[HttpResponse] = None):
        super().__init__(message)
        self.response = response


class HttpTimeoutError(HttpClientError):
    """The request exceeded its configured timeout."""


class HttpConnectionError(HttpClientError):
    """A connection could not be established or maintained."""


class HttpTransportError(HttpClientError):
    """Another HTTP transport or protocol failure occurred."""


class HttpStatusError(HttpClientError):
    """The server returned a status outside the successful 2xx range."""


class AsyncHttpClient:
    """Own a private HTTPX client and expose buffered application responses."""

    def __init__(self, config: AsyncHttpClientConfig):
        try:
            if not isinstance(config, AsyncHttpClientConfig):
                raise TypeError("config must be an AsyncHttpClientConfig.")
            headers = httpx.Headers(config.headers)
            if config.bearer_token is not None:
                headers["Authorization"] = f"Bearer {config.bearer_token}"
            self._debug_settings = (
                config.timeout, config.max_connections,
                config.max_keepalive_connections, config.keepalive_expiry,
            )
            self._client = httpx.AsyncClient(
                base_url=config.base_url,
                headers=headers,
                timeout=config.timeout,
                limits=httpx.Limits(
                    max_connections=config.max_connections,
                    max_keepalive_connections=config.max_keepalive_connections,
                    keepalive_expiry=config.keepalive_expiry,
                ),
                follow_redirects=False,
            )
        except Exception as error:
            if isinstance(error, ImportError):
                Logger.ERROR(
                    "HTTP client creation failed; error_type=%s; "
                    "a transport dependency is missing. Install config/requirements.txt.",
                    type(error).__name__,
                )
            else:
                Logger.ERROR("HTTP client creation failed; error_type=%s.", type(error).__name__)
            raise

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        content: Optional[bytes | str] = None,
        data: Optional[Mapping[str, Any]] = None,
        json: Any = None,
    ) -> HttpResponse:
        """Return a 2xx response or raise an application HTTP exception.

        Invalid arguments and JSON decoding errors remain programming/data
        errors. Cancellation propagates unchanged. No requests are retried.
        """
        try:
            if self.is_closed:
                raise HttpClientError("HTTP client is closed.")
            request = self._client.build_request(method, url, params=params, headers=headers,
                                                 content=content, data=data, json=json)
            request_id = uuid4().hex[:12]
            Logger.DEBUG(
                "HTTP request starting; request_id=%s; request=%s; timeout=%r; max_connections=%r; "
                "max_keepalive_connections=%r; keepalive_expiry_seconds=%r; "
                "query_supplied=%s; json_supplied=%s; form_supplied=%s; content_supplied=%s.",
                request_id, _RequestPreview(request), *self._debug_settings, params is not None, json is not None,
                data is not None, content is not None,
            )
            try:
                response = await self._client.send(request)
            except httpx.TimeoutException:
                raise HttpTimeoutError("HTTP request timed out.") from None
            except httpx.NetworkError:
                raise HttpConnectionError("HTTP connection failed.") from None
            except httpx.RequestError:
                raise HttpTransportError("HTTP transport failed.") from None
            result = HttpResponse(
                status_code=response.status_code,
                headers=MappingProxyType(dict(response.headers)),
                content=response.content,
                text=response.text,
            )
            secrets = _credential_values(request.headers)
            secrets.extend(value for key, value in request.url.params.multi_items()
                           if value and _sensitive_query_key(key))
            for source in (self._client.headers, httpx.Headers(headers or {})):
                secrets.extend(_credential_values(source))
            Logger.DEBUG(
                "HTTP response received; request_id=%s; status=%d; bytes=%d; body=%s.",
                request_id, result.status_code, len(result.content), _ResponsePreview(result, secrets),
            )
            if not 200 <= result.status_code < 300:
                raise HttpStatusError(f"HTTP request returned status {result.status_code}.", result)
            return result
        except HttpClientError as error:
            err_msg = str(error)
            Logger.ERROR(err_msg)
            raise
        except Exception:
            err_msg = "HTTP request execution failed."
            Logger.ERROR(err_msg)
            raise

    async def get(
        self, url: str, *, params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> HttpResponse:
        return await self.request("GET", url, params=params, headers=headers)

    async def post(
        self, url: str, *, params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        content: Optional[bytes | str] = None,
        data: Optional[Mapping[str, Any]] = None, json: Any = None,
    ) -> HttpResponse:
        return await self.request(
            "POST", url, params=params, headers=headers,
            content=content, data=data, json=json,
        )

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            err_msg = "HTTP client shutdown failed."
            Logger.ERROR(err_msg)
            raise


class AsyncHttpClientsManager:
    """Provide class-level access to named pools owned by a lazy singleton.

    Registry operations are synchronous and intended for application setup.
    Each registered HTTPX client owns its own connection pool.
    """

    _instance: ClassVar[Optional["AsyncHttpClientsManager"]] = None
    _instance_lock: ClassVar[Lock] = Lock()
    _pools: Dict[str, AsyncHttpClient]
    _pool_write_lock: Lock

    def __new__(cls) -> "AsyncHttpClientsManager":
        if cls._instance is not None:
            return cls._instance
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._pools = {}
                instance._pool_write_lock = Lock()
                cls._instance = instance
                Logger.DEBUG("HTTP clients manager initialized.")
            return cls._instance

    @classmethod
    def create_client(cls, config: AsyncHttpClientConfig) -> None:
        """Create and register a named HTTPX client without replacing an existing one."""
        if not isinstance(config, AsyncHttpClientConfig):
            raise TypeError("config must be an AsyncHttpClientConfig.")
        if not isinstance(config.name, str) or not config.name.strip():
            raise ValueError("Pool name must be a non-empty string.")
        instance = cls()
        Logger.DEBUG("Creating managed HTTP client.")
        with instance._pool_write_lock:
            if config.name in instance._pools:
                err_msg = "HTTP client registration failed: name already exists."
                Logger.ERROR(err_msg)
                raise ValueError(f"HTTP client pool {config.name!r} already exists.")
            client = AsyncHttpClient(config)
            instance._pools[config.name] = client
            count = len(instance._pools)
        Logger.DEBUG("Managed HTTP client registered; total clients=%d.", count)

    @classmethod
    def get_client(cls, pool_name: str = "default") -> AsyncHttpClient:
        """Return the registered client without acquiring the write lock."""
        if not isinstance(pool_name, str) or not pool_name.strip():
            raise ValueError("Pool name must be a non-empty string.")
        instance = cls()
        try:
            client = instance._pools[pool_name]
        except KeyError:
            err_msg = "HTTP client lookup failed: client has not been created."
            Logger.ERROR(err_msg)
            raise RuntimeError(
                f"HTTP client pool {pool_name!r} has not been built. "
                "Call AsyncHttpClientsManager.create_client(config) first."
            ) from None
        Logger.DEBUG("Returning existing managed HTTP client.")
        return client

    @classmethod
    async def aclose(cls) -> None:
        """Unregister and close all clients after callers have stopped using them.

        Call from the event loop that used the clients, after requests and pool
        registration have stopped. No thread lock is held across an await.
        """
        instance = cls()
        with instance._pool_write_lock:
            clients = instance._pools
            instance._pools = {}
        Logger.DEBUG("Closing managed HTTP clients; count=%d.", len(clients))
        results = await asyncio.gather(
            *(client.aclose() for client in clients.values()), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                Logger.DEBUG("Managed HTTP client shutdown completed with failures.")
                raise result
        Logger.DEBUG("Managed HTTP client shutdown completed; count=%d.", len(clients))
