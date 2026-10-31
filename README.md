# Daybreak

Daybreak uses Garmin Connect data and the AI capabilities of ChatGPT/Codex to generate a daily report. Daybreak is primarily a local MCP server. Predefined Skills guide a local Codex process to retrieve data through that server and produce the report. Manual or scheduled tasks trigger the workflow.

Status: managed HTTP clients with application-owned response and error types are implemented. Garmin integration is not implemented yet.

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

## Documentation

- [Roadmap](docs/roadmap.md): project direction and milestone status.
- [Implementation plan](docs/plans/garmin-daily-report.md): scope, tasks, acceptance criteria, and open decisions.
- [Repository instructions](AGENTS.md): collaboration and development rules.

## Development workflow

Use a short-lived task branch from the latest `main`. Keep implementation and related documentation together. Merge after review and verification, then start the next task from the updated `main`.

Use the shared Conda environment named `daybreak` for development and checks. The required versions are Python 3.14.8, HTTPX 0.28.1, and FastMCP 4.1.4. Python is pinned in `config/environment.yaml`; Python package dependencies are pinned in `config/requirements.txt`.

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

`config/default_config.toml` mirrors the class defaults and has three root
sections: `Logging`, `GeneralHttpClient`, and `GarminConnectClient`. The latter defines
`pool_size=10`, overridable with `--GarminConnectClient.pool-size`.
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

Request DEBUG logs include timeout/connection settings, whether query/body arguments were supplied, response status, body size, and a JSON body preview. Body previews are formatted lazily, limited to 2048 bytes/characters, and omitted for oversized or non-JSON bodies. Common credential fields are redacted recursively, and configured/request Authorization, Cookie, and API-key header values are removed from previews. URLs and request body values are not logged. These rules are not a general personal-data anonymizer; response previews can still contain application data.

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
