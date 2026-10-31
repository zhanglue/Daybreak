# Daybreak

Daybreak uses Garmin Connect data and the AI capabilities of ChatGPT/Codex to generate a daily report. Daybreak is primarily a local MCP server. Predefined Skills guide a local Codex process to retrieve data through that server and produce the report. Manual or scheduled tasks trigger the workflow.

Status: managed HTTP clients, the standalone Garmin Connect client, and the first
local-first HTTP MCP service are implemented. The Garmin client has 26 GET endpoints
aligned to API specification 1.0.0; all 26 are exposed as MCP tools with complete
client parameters, alongside six convenience tools and a binary ZIP resource.
Live Garmin client access was confirmed by the user. Complete live coverage of
the 26 tools and native Codex/Skill integration remain pending. Live MCP discovery,
local cache reuse, and selected single-day/multi-day health and activity queries
have been verified through an MCP SDK client; private results are not tracked.

## Implementation sequence

1. Define the initial Skills workflow and draft MCP tool contracts.
2. Build a general-purpose asynchronous HTTP client based on `httpx`.
3. Validate Garmin Connect API access inside the server integration.
4. Inventory the required data and finalize MCP response contracts.
5. Implement the local MCP server and connect Codex with the predefined Skills.
6. Generate daily reports and support manual and scheduled execution.

## Runtime architecture

```text
Manual / scheduled task -> Local Codex + predefined Skills
                                      |
                                MCP tool calls
                                      v
                              Daybreak MCP Server
                                      |
                              Garmin integration
                                      |
                              Async httpx client
                                      |
                              Garmin Connect APIs
```

Data returns through the MCP server to Codex for analysis and report generation. Codex does not directly access Garmin APIs or Garmin credentials. The MCP server serves tools and data; it does not launch Codex. A separate task runner starts Codex and captures the report.

The MCP server reads local files first and fetches missing or expired
records through the Garmin integration. The repository-relative store is
`garmin_data/`, organized primarily by date and endpoint, and excluded from Git.
See [MCP server usage](docs/mcp-server.md) for startup, supported datasets, refresh
rules, and current limitations. Start one service with `python src/mcp_server.py`
in the `daybreak` environment; multiple clients connect to
`http://127.0.0.1:15666/mcp`. Listener settings are centralized in `MCPServer`. The [contract draft](docs/local-data-contracts.md)
retains the broader design direction and pending work.

## Documentation

- Garmin API reference: [official Personal API Swagger](https://developer.garmin.com/gc-developer-program/personal/swagger-docs/). The client currently targets API specification version **1.0.0**, recorded in `GarminConnectClient.SWAGGER_VERSION`; `SWAGGER_URL` records the source address. This is the Garmin specification version, not the OpenAPI format version.
- [Roadmap](docs/roadmap.md): project direction and milestone status.
- [Implementation plan](docs/plans/garmin-daily-report.md): scope, tasks, acceptance criteria, and open decisions.
- [Local data and MCP contract draft](docs/local-data-contracts.md): planned file persistence and local-first tool behavior.
- [MCP server usage](docs/mcp-server.md): stdio startup, tools, persistence, and verification.
- [Repository instructions](AGENTS.md): collaboration and development rules.

## Development workflow

Use a short-lived task branch from the latest `main`. Keep implementation and related documentation together. Merge after review and verification, then start the next task from the updated `main`.

Use the shared Conda environment named `daybreak` for development and checks. The required versions are Python 3.14.8, HTTPX 0.28.1 with SOCKS support, and FastMCP 4.1.4. Python is pinned in `config/environment.yaml`; Python package dependencies are pinned in `config/requirements.txt`.

If the environment already exists, activate it:

```bash
conda activate daybreak
```

For a new development machine, create the environment with the same name:

```bash
conda env create -f config/environment.yaml
conda activate daybreak
```

To synchronize an existing environment with the declared dependencies:

```bash
conda env update -n daybreak -f config/environment.yaml
```

Do not create a separate `.venv`. Packaging remains deferred. The exact Codex invocation will be verified during integration.

## Global configuration

`src/global_config.py` creates `global_config` at import time. Calling
`GlobalConfig()` returns that same instance without resetting it. Frozen nested
data classes define the schema and defaults. The `GeneralHttpClient` section contains
`timeout=5.0`, `max_connections=100`, `max_keepalive_connections=20`, and
`keepalive_expiry=5.0`. These settings do not automatically configure HTTP clients;
callers pass the selected values when creating clients.

```python
from global_config import global_config

global_config.update_from_toml("config/default_config.toml")
global_config.update_from_cli()  # Explicitly parse sys.argv[1:].
timeout = global_config.GeneralHttpClient.timeout
```

`config/default_config.toml` mirrors the configuration schema with explicit overrides and has four root
sections: `Logging`, `MCPServer`, `GeneralHttpClient`, and `GarminConnectClient`. The latter defines
`api_key_string=""`, `api_key_file="config/API_KEY.txt"`, and `http_client_pool_size=10`
(overridable with `--GarminConnectClient.http-client-pool-size`). Pool size must
be positive and maps to the owned HTTP client's `max_connections`.
The same Garmin section defines `base_url="https://personal.connectapi.garmin.com"`, `timeout=5.0`,
`max_keepalive_connections=10`, and `keepalive_expiry=5.0`.
`GarminConnectClientConfig.http_client_name` defaults to `"GarminConnect"` in code
and is omitted from the default TOML.
`GarminConnectClient.generate_http_client_config(config)` translates these settings into
`AsyncHttpClientConfig`. Garmin transport uses only its own configuration section;
it does not inherit `GeneralHttpClient` values or clamp connection settings.
Authorization remains per-request runtime state rather than static HTTP defaults.

`await GarminConnectClient.get_client()` creates a lazy process-local singleton
on the application event loop. Direct construction raises `TypeError`. The factory
captures configuration and obtains a token before publishing the instance; failed or
cancelled initialization can be retried. Configure before the first factory call.
Credential resolution: a nonblank `api_key_string`
takes precedence, otherwise the UTF-8 `api_key_file` is read and surrounding
whitespace is removed. The file path is relative to the repository root, regardless
of the working directory; absolute paths, parent traversal, and symlinks escaping
the repository are rejected. Missing, unreadable, or empty credentials raise
`ValueError` without including the key or file contents. Inline keys are excluded
from configuration representations. Keep real keys out of tracked TOML files;
`API_KEY.txt` is already ignored by Git.

The client owns an `AsyncHttpClient` wrapper and closes it if initial token
acquisition fails. Call `await client.aclose()` after requests have stopped to
release transport and clear the singleton. API keys are loaded locally for each
token exchange without an additional key member. The client stores the token and
its UNIX expiration from the JWT `exp` claim. This decoding schedules refresh;
it does not verify JWT signatures. Tokens with invalid expiration or at most 600
seconds remaining are rejected. `_ensure_token()` serializes checks and refresh
under an async lock; `@token_check` applies this guard to future public async
remote instance methods. Waiting calls recheck the new expiration under the lock
and do not proceed on refresh failure. Already-running requests are not paused.
The 26 data endpoints in the supplied inventory have explicit async methods; see
[endpoint contracts](docs/garmin-connect-client.md) for arguments and limitations.
Their outer `@handle_api_errors` logs expected HTTP/transport, validation, and
parsing failures and returns `None`; cancellation propagates. Factory
initialization failures still raise without publishing a singleton.
Token storage is intentionally process-local: a running MCP server reuses the token,
and a process restart obtains a new one. Disk persistence is outside the agreed
client scope. Existing HTTP DEBUG response previews are retained for this personal
application. There is no background refresh timer or authentication-status retry. Token endpoint behavior follows the
[official Garmin authentication example](https://github.com/garmin/connect-personal-api-python/blob/main/src/garmin_personal_api/auth.py).

Run the standalone Garmin smoke test from the repository root:

```bash
conda activate daybreak
python src/garmin_connect_client.py
```

HTTPX honors proxy environment settings. The declared `httpx[socks]` dependency
includes `socksio` so SOCKS-configured shells can create clients. If transport
creation fails, ERROR logs show the exception type and an installation hint for
missing dependencies without exposing proxy URLs or raw exception messages.
Synchronize packages in the active environment with
`python -m pip install -r config/requirements.txt`.

With proxy variables unset, HTTPX connects directly. With a reachable HTTP or
SOCKS proxy configured, it routes requests through that proxy; `NO_PROXY` can
bypass it for matching hosts. Stopping a proxy application does not clear shell
proxy variables: unset stale proxy settings before running in direct mode.
Proxy selection is captured when the HTTP client is created; restart the process
or close and recreate the client after changing proxy settings. There is no
automatic direct fallback when a configured proxy is unavailable.

The entry point loads `config/default_config.toml` relative to the repository,
then applies existing dotted CLI overrides. It prints the Garmin configuration
with `api_key_string` always replaced by `********`, obtains a token through the
factory, and prints heart rate zones and user profile settings as JSON. The token
itself is not printed; only its expiration is shown. The client and logger are
closed before exit. Exit status is 0 when both GETs return non-null results and 1
on initialization, handled remote, or cleanup failure. Imports do not execute the
smoke test. This manual command accesses real account data when supplied a real
key; automated verification uses synthetic responses only.

Loading remains explicit. Example override TOML:

```toml
[GeneralHttpClient]
timeout = 10.0
max_connections = 50
```

Application configuration uses the standard-library `tomllib` parser and has no
PyYAML dependency. `config/environment.yaml` remains the Conda environment file.

Run with `--GeneralHttpClient.timeout 3 --GeneralHttpClient.max-connections 25` to override those fields.
Omitted CLI options retain TOML values; omitted TOML fields retain class defaults.
Importing never reads files or parses arguments. Pass a list to
`update_from_cli([...])` for embedded use. Each update replaces its own source
layer; CLI values always take precedence, including after later TOML updates.
An empty file clears the TOML layer, and an empty argument list clears the CLI
layer. Unknown fields, incorrect types, and invalid numeric limits are rejected
without publishing a partial update. CLI syntax errors use standard argparse
errors. Configure once during single-threaded startup, before consumers read it.
No Garmin credentials or health data belong in configuration examples.

`Logging.level` defaults to `INFO`. Its nested `console` settings default to
`enabled=true` and `level="INFO"`; console output is intended for stderr so MCP
stdout remains available for protocol messages. The `file` settings default to
`enabled=false`, `level="INFO"`, `path="logs/daybreak.log"`,
`max_bytes=10485760` (10 MiB), and `backup_count=3`. Rotation limits must be
positive integers. Levels accept `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`,
and `NOTSET`. Boolean CLI options use `--Logging.file.enabled` to enable and
`--no-Logging.console.enabled` to disable. Other options accept values, such as
`--Logging.file.level DEBUG`. These are configuration contracts only: loading
configuration does not create handlers, directories, or log files.

`GlobalConfig().MCPServer` centralizes MCP transport/listener, data source, data directory, calendar
timezone, and freshness settings. Listener defaults are `transport="http"`,
`host="127.0.0.1"`, `port=15666`, and `path="/mcp"`. Data defaults are `data_source="garmin_connect"`,
`data_directory="garmin_data"`, `timezone_name="UTC"`, `recent_days=7`,
`recent_ttl_seconds=3600`, and `profile_ttl_seconds=86400`. Override through the
`[MCPServer]` TOML table or dotted CLI options such as
`--MCPServer.timezone-name Asia/Shanghai`. Unsupported sources raise
`NotImplementedError` during server initialization, before tools are served.
See [MCP server usage](docs/mcp-server.md) for the complete behavior.

## Global logger

`src/logger.py` provides the process-local `Logger` singleton. Load configuration
before the first `Logger()` or logging call: initialization is lazy and captures
`GlobalConfig().Logging` once. Importing the module has no logging side effects.

```python
from global_config import global_config
from logger import Logger

global_config.update_from_toml("config/default_config.toml")
global_config.update_from_cli()
Logger.INFO("Starting %s", "Daybreak")
Logger.DEBUG("Diagnostic details")
Logger.ERROR("Operation failed")
# Inside an exception handler: Logger.ERROR("Operation failed", exc_info=True)
# At shutdown, after callers have stopped logging:
Logger.close()
```

The shared level and each handler level both filter records. Console output goes
to stderr; optional UTF-8 file output creates parent directories and rotates
according to `max_bytes` and `backup_count`. Console and file records share the format `YYYY.MM.DD HH:MM:SS.mmm LEVEL message`,
with timestamps to milliseconds and standard level names left-aligned to at least
five characters (`DEBUG`, `INFO `, `ERROR`). The logger name is omitted. Standard logging arguments such as `exc_info`, `extra`, and
`stacklevel` are supported. No records propagate to the root logger. Disabling
both outputs is silent, including for errors. `NOTSET` on the shared logger
imposes no level filter. Repeated access does not duplicate handlers.

`Logger.close()` is idempotent and releases file handles. The next call creates
the singleton again using current configuration. Configuration updates alone do
not alter an initialized logger. Stop logging before closing or reinitializing.
Callers are responsible for excluding credentials and personal data from messages.

## HTTP client framework

`AsyncHttpClientsManager` is a process-local, lazily created singleton. It maps names to our `AsyncHttpClient` wrappers. Each wrapper owns a private `httpx.AsyncClient` and its connection pool. Singleton creation is locked; subsequent singleton access and named lookups do not acquire a lock. A write lock covers duplicate checks, synchronous construction, and registration. Only fully constructed clients are published. Manager DEBUG logs record singleton initialization, creation/registration, successful lookup, and shutdown start/completion (including failures). Registration and shutdown include client counts; names, URLs, configuration, credentials, and response content are excluded. Enable DEBUG on both the shared logger and the selected output handler to see these records.

`AsyncHttpClientConfig` is a frozen data class with `name`, `base_url`, `headers`, `bearer_token`, `timeout`, `max_connections`, `max_keepalive_connections`, and `keepalive_expiry`. Headers and the token are excluded from its representation. Headers are copied at client creation; a configured token sets the default Authorization header. Integrations own token acquisition and refresh. Request headers may override client defaults.

```python
from async_http_client import (
    AsyncHttpClientConfig, AsyncHttpClientsManager, HttpClientError,
)

AsyncHttpClientsManager.create_client(
    AsyncHttpClientConfig(name="default", base_url="https://example.test")
)

async def fetch_status():
    try:
        client = AsyncHttpClientsManager.get_client()
        response = await client.get("/status", params={"detail": "summary"})
        return response.json()
    except HttpClientError as error:
        # A status error carries its response; transport errors do not.
        raise
    finally:
        # At application shutdown, after all other requests have finished:
        await AsyncHttpClientsManager.aclose()
```

`get_client()` selects `default`; `get_client("service")` selects another explicitly created client. Missing names raise `RuntimeError`, duplicate or empty names raise `ValueError`, and invalid configuration types raise `TypeError`. Lookup never creates a client implicitly. The Manager owns shutdown; callers borrowing clients must not close them independently.

`AsyncHttpClient` exposes asynchronous `request()`, `get()`, and `post()`. Requests support query parameters and headers; `request()` and `post()` also support JSON, form data, or raw content. Responses are fully buffered. A 2xx response returns `HttpResponse` containing `status_code`, headers with lowercase keys, `content` bytes, `text`, and an on-demand `json()` method. JSON decoding failures remain JSON decoding errors; an empty 204 response is valid without JSON decoding. No HTTPX client, response, or request is exposed through these methods.

Non-2xx statuses, including redirects, raise `HttpStatusError` carrying the `HttpResponse` in `.response`. Timeouts raise `HttpTimeoutError`, network errors raise `HttpConnectionError`, and other HTTPX request errors raise `HttpTransportError`. These derive from `HttpClientError`; transport errors have no response. Error messages omit URLs, bodies, credentials, and underlying error text, and suppress the underlying exception traceback. Response bodies may contain sensitive server data and must be handled explicitly. Invalid request arguments remain programming errors, and cancellation propagates unchanged. Requests are not retried and redirects are not followed automatically.

Request DEBUG logs include the actual HTTP method, fully resolved URL, path, all query parameters (including repeated values), timeout/connection settings, whether body arguments were supplied, response status, body size, and a JSON body preview. A generated request ID correlates request and response entries. Request context is formatted lazily from the built HTTPX request, after base URL and parameter merging. URL user information is removed; credential-like query fields and known credential values are redacted. Ordinary query values are retained without truncation. Body previews are formatted lazily, limited to 2048 bytes/characters, and omitted for oversized or non-JSON bodies. Common credential fields are redacted recursively, and configured/request Authorization, Cookie, and API-key header values are removed from previews. Request headers and request body values are not logged. These rules are not a general personal-data anonymizer; response previews can still contain application data.

HTTP client creation, request execution, JSON decoding, shutdown, duplicate registration, and missing-client lookup failures emit an ERROR through `Logger.ERROR(err_msg)` before raising. Request failures are logged once at the shared request boundary, rather than again in `get()` or `post()`. Logs contain only safe operation/status messages, without URLs, names, headers, bodies, raw exception text, or tracebacks. Original non-HTTP exception types and identities are preserved. Cancellation is neither logged as an error nor wrapped. Load logging configuration before the first HTTP operation that may fail.

Call `await AsyncHttpClientsManager.aclose()` after requests and registration have stopped, on the event loop that used the clients. It detaches the registry under the write lock and closes clients outside the lock. All closes are attempted before propagating the first failure. Empty shutdown is harmless, and clients can be explicitly recreated afterward. Clients must stay within one application event loop; the singleton does not allow sharing live transports across event loops.

Source modules live directly in `src/`, tests in `tests/`, and documentation in `docs/`. Further package organization is deferred. Set `PYTHONPATH=src` when running the usage example or tests from the repository root.

Run the framework checks from the repository root (verified in the shared environment):

```bash
conda activate daybreak
PYTHONPATH=src python -m unittest discover -s tests -v
```

Communicate with the user in Chinese. All tracked file content, code comments, and Git commit messages must be in English.

Do not commit credentials, session tokens, personal health data, or generated personal reports.
