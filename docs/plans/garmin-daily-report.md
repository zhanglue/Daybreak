# Garmin Daily Report: Initial Implementation Plan

Status: managed HTTP client wrappers, response/error contracts, and shutdown implemented; 21 tests pass in the shared Conda environment.

## Objective

Use Garmin Connect as the data source, use ChatGPT/Codex as the AI analysis capability through a local Codex command, and produce a daily report.

## Architecture and responsibilities

```text
Manual / scheduled task
  -> Local Codex process with predefined Skills
  -> Daybreak MCP tools
  -> Garmin integration using the async httpx client
  -> Garmin Connect APIs
  -> Structured results returned through MCP
  -> Codex analysis and daily report
```

- **Task runner:** starts Codex, supplies the requested date and workflow, captures output, and handles execution failures.
- **Skills:** define which MCP tools to call, how to interpret results, how to handle missing data, and how to produce the report.
- **Codex:** acts as the MCP client, follows the Skills, analyzes returned data, and generates the report.
- **Daybreak MCP server:** exposes data tools, validates arguments, accesses Garmin, and returns structured data and errors.
- **Garmin integration:** owns Garmin authentication, sessions, endpoint mapping, and data normalization.
- **Generic HTTP client:** owns reusable asynchronous HTTP transport using `httpx`.

Codex must not access Garmin directly. The server does not invoke Codex; the runner is a separate component. Local MCP transport and server lifecycle remain open decisions: do not assume an always-running HTTP service is required.

## Confirmed decisions

- Daybreak is primarily a local MCP server backed by Garmin Connect APIs.
- Define Skills in advance so Codex knows how to retrieve and analyze data through MCP.
- Use a general-purpose asynchronous HTTP client based on `httpx` behind the Garmin integration.
- Refine the selected datasets and MCP contracts after validating Garmin access.
- Support both manual and scheduled tasks that invoke local Codex with the required Skills and MCP connection.
- Generate the report through Codex analysis of MCP results.
- Use Chinese for user communication and English for tracked content and commit messages.
- Establish the initial `main` baseline from these planning documents.
- Use the shared Conda environment named `daybreak`: Python 3.14.8, HTTPX 0.28.1, and FastMCP 4.1.4. `config/environment.yaml` defines the named environment and imports package pins from `config/requirements.txt`. Do not create a separate virtual environment.

## 1. Skills workflow and draft MCP contracts

Suggested branch: `docs/skills-mcp-contracts`.

- [ ] Define the initial daily-report Skill responsibilities, invocation conditions, and workflow before implementing the integration.
- [ ] Draft the needed MCP tools, argument schemas, structured results, and error contracts without claiming unverified Garmin capabilities.
- [ ] Define date, provenance, units, missing-data indicators, and result-size expectations.
- [ ] Define the intended Skill packaging and discovery approach; verify it against current Codex documentation during implementation.
- [ ] Record a synthetic interaction showing tool calls, incomplete results, and expected analysis behavior.

Acceptance: an agreed draft specifies how Codex retrieves data through Daybreak and generates a report; uncertain Garmin capabilities are explicitly provisional.

## 2. General-purpose asynchronous HTTP client

The user explicitly selected the HTTP registry framework as the current task before milestone 1. The Skills workflow and MCP contract work remains pending.

- [x] Confirm Python version, dependency management, and project layout.
- [x] Implement the outer named-pool registry with a data-only configuration class, lazy singleton construction, explicit default-pool registration, and missing-pool errors.
- [x] Define a small reusable interface around `httpx.AsyncClient`.
- [x] Support configurable base URL, headers, query parameters, request bodies, and timeouts.
- [x] Define connection lifecycle, response handling, and useful error behavior.
- [x] Decide whether retries are needed; if added, bound them and define which requests may be retried safely.
- [x] Verify successful requests, timeout and HTTP error behavior, and resource cleanup using mocked transport.
- [x] Document usage without introducing Garmin-specific behavior into the generic layer.

Acceptance: an asynchronous caller can use the client independently of Garmin; behavior and lifecycle are documented and verified without live network dependencies.

## 3. Garmin Connect API access

Dependency: milestone 2. Suggested branch: `spike/garmin-access`.

- [ ] Investigate current API access options and authentication using available first-party documentation and relevant dependency sources.
- [ ] Document the selected access method, limitations, and any undocumented behavior.
- [ ] Implement the minimum Garmin-specific authentication and request flow on top of the generic client.
- [ ] With the user's authorization and local credentials, validate access to representative account data.
- [ ] Establish session reuse, authentication failure handling, and diagnostic behavior without leaking secrets.
- [ ] Record endpoint purposes and observed response structures using synthetic or approved sanitized examples.

Acceptance: the chosen access path retrieves representative Garmin data; authentication steps and access limitations are documented. Credentials and real responses remain outside Git. If access cannot be established, record the blocker and revisit the approach with the user.

## 4. Data inventory and MCP response contracts

Dependency: milestones 1 and 3. Suggested branch: `feat/analysis-input`.

- [ ] Inventory available datasets and fields. Sleep, heart rate, activity, training, stress, and recovery are candidates, not guaranteed requirements.
- [ ] For selected fields, document source endpoint, meaning, unit, time range, availability, and missing-value behavior.
- [ ] Agree on report questions, required versus optional fields, timezone, and report-day boundaries.
- [ ] Decide whether historical comparisons are needed and define the required lookback.
- [ ] Finalize versioned MCP result schemas, request limits, and any local cache or retention requirements.
- [ ] Implement the minimum collection and normalization needed to produce that input.
- [ ] Prepare synthetic fixtures covering complete and incomplete inputs.

Acceptance: a documented data inventory explains what is available and why each selected field is needed; the collection flow can produce the agreed analysis input for a selected date. Missing data is distinguishable from zero values.

## 5. Local MCP server, Skills, and Codex integration

Dependency: milestone 4. Suggested branch: `feat/mcp-codex-integration`.

- [ ] Implement the MCP server tools over the Garmin integration and validate schemas, structured responses, and error behavior.
- [ ] Select local MCP transport and lifecycle; document connection setup and keep protocol output separate from diagnostic logs.
- [ ] Implement the predefined Skills with finalized tool names and response contracts.
- [ ] Verify Skills discovery and MCP tool discovery from a local Codex session.
- [ ] Inspect the installed Codex CLI and verify the supported non-interactive invocation and authentication requirements.
- [ ] Agree on what prepared health data may be supplied to Codex and document that local invocation does not imply offline inference.
- [ ] Define an English analysis prompt and an output contract with evidence references and explicit uncertainty.
- [ ] Invoke Codex with the requested date, explicit Skill workflow, and MCP connection; retrieve source data through MCP rather than direct Garmin access.
- [ ] Verify that Garmin credentials remain server-side and tool errors are handled by the Skill.
- [ ] Handle unavailable commands, authentication errors, timeouts, nonzero exits, and invalid output.
- [ ] Test process handling with a stub command, then validate an authorized end-to-end invocation.
- [ ] Check synthetic examples for unsupported claims and missing-data handling; do not require identical prose across runs.

Acceptance: a documented local command loads the Skill, invokes Daybreak MCP tools, and produces usable AI analysis from their results, preserves evidence references, and exposes failures clearly. The analysis does not invent missing measurements.

## 6. Daily reports and task triggers

Dependency: milestone 5. Suggested branch: `feat/daily-report`.

- [ ] Confirm report language, format, sections, output location, and date naming.
- [ ] Define how AI analysis is turned into the final report, including which metadata the application adds.
- [ ] Include the report date, source-data time ranges, key findings, and data completeness.
- [ ] Define repeat-run and existing-output behavior.
- [ ] Provide a manual workflow for collecting data, invoking analysis, and writing the report for a selected date.
- [ ] Add a separate runner that supports manual execution and scheduling on the agreed host.
- [ ] Verify unattended Codex authentication, Skill loading, MCP connection, working directory, and permissions without assuming interactive approval.
- [ ] Define scheduling timezone, concurrent-run handling, bounded retries, and delayed Garmin synchronization behavior.
- [ ] Verify scheduled execution and manual reruns without duplicate or corrupted reports.
- [ ] Add installation and end-to-end usage instructions to the README.
- [ ] Review a synthetic sample, then validate an authorized real-data report with the user.

Acceptance: following the README produces a daily report for a selected date; findings can be traced to the supplied data; incomplete input and execution failures are visible; personal outputs remain outside Git; a scheduled run also completes in the target environment or exposes a clear actionable failure.

## User-selected increment: global configuration

- [x] Add `src/global_config.py` with an import-time singleton and nested data classes.
- [x] Support explicit standard-library TOML loading and explicit dotted CLI options.
- [x] Preserve defaults for omitted TOML fields and TOML values for omitted CLI options.
- [x] Keep CLI precedence independent of update order and reject invalid updates atomically.
- [x] Document startup usage and verify with synthetic configuration tests.
- [x] Add `config/default_config.toml` matching the `GeneralHttpClient` and
  `GarminConnectClient` root data classes, including Garmin `pool_size=10`.
- [x] Migrate application configuration from YAML to standard-library `tomllib`
  and remove the direct PyYAML dependency; keep the Conda environment YAML file.
- [x] Add `Logging` first in the TOML file with shared and handler levels,
  console enabled, file disabled, and 10 MiB rotation with three backups.
- [x] Support nested logging defaults, typed validation, and boolean CLI switches.

The application logger increment below implements handler initialization.
Configuration loading itself continues to have no logging side effects.

Acceptance: one instance is available immediately after import, layered values
follow defaults < TOML < CLI, and nested configuration is accessible through
data-class attributes. The initial schema covers existing HTTP connection settings;
HTTP client wiring and Garmin settings remain separate work. Each explicit update
replaces its source layer. Startup configuration is single-threaded.

Verification: all 28 tests pass in the existing `daybreak` Conda environment,
including seven configuration tests and default TOML/schema alignment. Tests use synthetic TOML files;
no credentials, personal data, or live network calls are involved.

## User-selected increment: global logger

- [x] Add a lazily initialized, thread-safe `Logger` singleton reading
  `GlobalConfig().Logging` at first use.
- [x] Expose `Logger.INFO`, `Logger.DEBUG`, and `Logger.ERROR`, supporting standard
  logging formatting and exception arguments.
- [x] Implement independent stderr and rotating UTF-8 file handlers with shared
  and per-handler level filters and no root propagation.
- [x] Provide idempotent shutdown and reinitialization using current settings.
- [x] Verify singleton initialization, filtering, silent disabled outputs,
  exception output, file rotation, and resource cleanup using synthetic data.
- [x] Document startup order, output behavior, and lifecycle.

Acceptance: direct class-level calls share one initialized logger, honor the
existing logging configuration, preserve stdout for MCP, and close owned handlers.
Configuration is captured once; shutdown requires callers to stop logging first.

Verification: all 33 tests pass in the existing `daybreak` Conda environment,
including five logger tests. No live network, credentials, or personal data were
accessed. Application startup integration remains pending its implementation.

The task branch starts from the current configuration commit rather than `main`
because the required configuration implementation is not yet on `main`; existing
uncommitted HTTP framework and documentation changes were preserved.

Suggested next step: review the logger interface and lifecycle before selecting
further work; Garmin integration remains outside this increment.

## Open decisions

Resolve each decision before its implementation depends on it:

- Garmin access method and credential/session storage.
- Selected datasets, timezone, report-day boundaries, and history requirements.
- Data preparation format and retention policy.
- MCP SDK, local transport, server lifecycle, tool contracts, and result-size limits.
- Skills packaging and discovery, Codex invocation, output contract, and authorized data scope.
- Scheduling mechanism, execution time, retry policy, and unattended environment.
- Report language, format, sections, and output behavior.

Markdown is a candidate report format. `Asia/Shanghai` is a candidate timezone. Neither is a confirmed product requirement.

## Progress and handoff

Each milestone starts on demand from the latest `main`. Update its checkboxes after verification, and update the roadmap only when its acceptance criteria are met. Record material decisions and unresolved issues here so a new conversation can resume from repository context.

Layout decision: keep source files directly in `src/`, tests in `tests/`, and documentation in `docs/`, and environment configuration in `config/`. The unused repository-local `.venv` has been removed; development uses the existing `daybreak` Conda environment. Do not introduce a project-named package directory yet; further organization is deferred. Activate `daybreak` and run tests from the repository root with `PYTHONPATH=src python -m unittest discover -s tests -v`. For non-interactive execution, use `PYTHONPATH=src conda run -n daybreak python -m unittest discover -s tests -v`.

Current increment: `src/async_http_client.py` defines `AsyncHttpClientsManager`, a lazy singleton mapping names to application-owned `AsyncHttpClient` objects. `create_client(config)` explicitly creates wrappers; `get_client(pool_name="default")` returns them. The write lock covers duplicate checks, synchronous construction, and registration; reads remain unlocked after singleton initialization. Missing and duplicate names remain errors. Each wrapper privately owns one HTTPX client and its connection pool.

`AsyncHttpClientConfig` is a frozen data class containing the name, base URL, headers, bearer token, timeout, and connection limits. Headers and bearer tokens are excluded from its representation. Credentials are supplied only by integrations; generic transport does not acquire or refresh them. Configured headers are copied when creating the client.

Wrappers expose async `request`, `get`, and `post`. Successful 2xx calls return a buffered `HttpResponse` with status, headers, bytes, text, and on-demand JSON decoding. Non-2xx statuses (including redirects) raise `HttpStatusError` carrying the response. `HttpTimeoutError`, `HttpConnectionError`, and `HttpTransportError` translate HTTPX request failures under `HttpClientError`. Error messages omit sensitive request details and suppress underlying tracebacks. Invalid arguments and JSON decode errors retain their native error types; cancellation propagates. No retries or automatic redirects are implemented. Streaming and additional convenience verbs are deferred.

Manager shutdown detaches clients under its write lock and closes them outside the lock, attempting every close before propagating the first failure. Shutdown requires requests and registration to have stopped and must run on the event loop that used the clients. Borrowers must not close shared clients independently. Empty shutdown and explicit recreation are supported.

Verification: all 21 tests pass in the existing `daybreak` Conda environment (Python 3.14.8, HTTPX 0.28.1, FastMCP 4.1.4). Tests cover singleton and registry concurrency, default/named lookup, wrapper identity, configured authentication and request parameters, POST bodies, application responses, non-2xx statuses, timeout/network/protocol errors, cancellation, JSON decode behavior, and cleanup including failed closes. All requests use synthetic MockTransport fixtures; no live network or Garmin data is accessed. Fresh environment dependency resolution remains unverified. A separate user-authorized live HTTPS smoke test is recorded below.

Live smoke test (2026-10-31): using the existing `daybreak` environment and the application wrapper, GET `https://httpbin.org/get` with synthetic `name=daybreak` returned 200 and the expected query echo; POST `https://httpbin.org/post` with synthetic JSON `{"message": "hello"}` returned 200 and the expected JSON echo. Both calls reused the same managed client; shutdown completed with `is_closed=True`. The sandboxed connection was blocked; the authorized network-enabled rerun passed. No credentials or personal data were sent, and echoed network metadata was not printed or saved. This verifies one public HTTPS service, not all network failure modes.

Manager DEBUG logging records singleton initialization, client creation/registration, successful retrieval, and shutdown start/completion or failure. Counts are included for registration and shutdown; client names and request/configuration data are omitted. Normal operation remains quiet at INFO. The existing 35-test suite passes after this addition.

HTTP error logging: creation, requests, JSON decoding, client shutdown, duplicate registration, and missing-client lookup now call `Logger.ERROR(err_msg)` before raising. Request logging is centralized to avoid duplicate GET/POST records. Logs exclude URLs, names, credentials, bodies, raw exception details, and tracebacks. Existing HTTP translations and original non-HTTP exceptions are preserved; cancellation is not logged or wrapped. Logging configuration must be loaded before the first failing HTTP operation.

Verification for this logging increment: 35 tests pass in the shared `daybreak` Conda environment, including safe log messages, original exception preservation, and cancellation behavior. No network or personal data is accessed.

Suggested next step: review the wrapper/configuration and response/error contracts before selecting further work. The user-selected HTTP layer scope is implemented; do not advance automatically to Garmin integration.

## Deferred work

Dashboards, notifications, multi-user accounts, and direct model API integration require separate scope agreement.

## Reference

- [OpenAI: Skills and MCP responsibilities](https://developers.openai.com/plugins/concepts/skills). Skills define reusable workflows around tools; the server provides live data and controlled operations. Exact local Codex configuration will be verified during integration.


Request DEBUG increment: log timeout/connection configuration and argument-presence flags before execution, then status, response size, and a lazy JSON preview before status checking. Previews omit oversized (>2048 bytes) and non-JSON bodies, redact common credential keys recursively, remove known sensitive request header values, and cap formatted output at 2048 characters. Response data is otherwise not anonymized. URLs and request body values remain excluded. All 36 tests pass, including error-response logging and synthetic credential redaction.


Logger format increment: console and file handlers share
`%(asctime)s.%(msecs)03d %(levelname)-5s %(message)s` with date format
`%Y.%m.%d %H:%M:%S`. Standard level names are retained, INFO is padded
to five characters, timestamps include three millisecond digits, and logger names are omitted. Output routing
remains stderr plus the optional file handler. All 36 tests pass after updating
the existing format assertion.
