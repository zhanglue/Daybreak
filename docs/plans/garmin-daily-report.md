# Garmin Daily Report: Initial Implementation Plan

Status: managed HTTP clients, the standalone Garmin client, and the first local-first
HTTP MCP service are implemented; 92 tests pass in the shared Conda environment.
Live Garmin client validation is confirmed by the user; live MCP access and
Codex/Skill integration remain pending.

## Objective

Use Garmin Connect as the data source, use ChatGPT/Codex as the AI analysis capability through a local Codex command, and produce a daily report.

## Architecture and responsibilities

```text
Manual / scheduled task
  -> Local Codex process with predefined Skills
  -> Daybreak MCP tools
  -> Local data layer: read valid files under garmin_data/
     -> On miss or expiry: Garmin integration using the async httpx client
     -> Garmin Connect APIs -> atomic local persistence
  -> Structured results returned through MCP
  -> Codex analysis and daily report
```

- **Task runner:** starts Codex, supplies the requested date and workflow, captures output, and handles execution failures.
- **Skills:** define which MCP tools to call, how to interpret results, how to handle missing data, and how to produce the report.
- **Codex:** acts as the MCP client, follows the Skills, analyzes returned data, and generates the report.
- **Daybreak MCP server:** exposes data tools, validates arguments, accesses Garmin, and returns structured data and errors.
- **Local data layer:** owns file identity, freshness, incremental gap retrieval,
  atomic persistence, and provenance; a valid local hit requires no Garmin auth.
- **Garmin integration:** owns Garmin authentication, sessions, endpoint mapping, and data normalization.
- **Generic HTTP client:** owns reusable asynchronous HTTP transport using `httpx`.

Codex must not access Garmin directly. The server does not invoke Codex; the runner
is a separate component. The selected default is a persistent local Streamable
HTTP service shared by client processes. Stdio remains an explicit alternative.

## Confirmed decisions

- Daybreak is primarily a local MCP server backed by Garmin Connect APIs.
- Persist health-data responses in ignored repository-relative `garmin_data/`,
  primarily by calendar date and endpoint. Read local data first; fetch missing
  or expired records. Authentication tokens remain process-local.
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

User-selected increment: `src/garmin_connect_client.py` provides a standalone,
process-local `GarminConnectClient`. The async `get_client()` factory owns
creation and publication under an `asyncio.Lock`, rechecking the singleton after
acquiring the lock. Direct construction logs an ERROR and raises `TypeError`.
Initialization now obtains a token before publication, using an owned generic
HTTP wrapper. Failure or cancellation closes that wrapper and permits retry;
`aclose()` releases it and clears the singleton after requests stop. Callers must
use one application event loop. No separate API key member is retained. Token
exchange uses a locally loaded key and parses the plain-text JWT's `exp` as UNIX
seconds, following the [official Garmin authentication example](https://github.com/garmin/connect-personal-api-python/blob/main/src/garmin_personal_api/auth.py).
Parsing is for refresh scheduling, not signature verification. `_ensure_token()`
locks checks and refreshes when remaining lifetime is at most 600 seconds;
waiting calls recheck after acquiring the lock. `@token_check` guards future
public async remote instance methods. Invalid or near-expiry new tokens fail
without replacing existing state. Refresh failure prevents remote execution.
Token storage is intentionally process-local; disk persistence is outside the agreed
client scope. Authentication-status recovery is not implemented.
All 51 tests pass in the existing `daybreak` environment using synthetic keys,
JWTs, and mocked HTTP calls. No live Garmin request or real credential access was
performed by the agent. The later user-confirmed live validation is recorded below.

Endpoint increment: all 26 public GET routes have explicit async methods
using `@token_check`. On 2026-10-31 the official Swagger page's embedded API
specification version 1.0.0 (OpenAPI format 3.0.1) was retrieved and all declared parameters were checked.
Corrections include search limit 99 and all 32 filters, weight includeAll=false,
optional query dates, generateDefaults/fullHistoryScan, nutrition and menstrual
options, explicit calendarDate for daily user summary, and ZIP download Accept.
Arrays use repeated query parameters; booleans serialize as lowercase strings.
The parameter-only public snapshot in `tests/fixtures/garmin_openapi_parameters.json`
backs tests for every method signature, default, and wire mapping.
[Endpoint contracts](../garmin-connect-client.md) record the complete mapping and
server-side date-range limits. All 58 tests pass in `daybreak`, including an HTTPX
MockTransport check for repeated array filters. No real credentials, health data,
or live Garmin API calls were used. The automated checks do not validate live response schemas. User-confirmed live
access is recorded below. Existing DEBUG response previews are retained by user decision.

Remote error-handling increment: all 26 remote methods have `@handle_api_errors`
outside `@token_check`. Expected HTTP/transport and `ValueError` failures are
logged with safe operation/category/status fields and return `None`, including
refresh and JSON parsing failures. Status errors are not mislabeled as key/token
expiry. Cancellation and unrelated programming errors propagate; initial factory
authentication and explicit shutdown retain exception behavior. `None` also
represents empty/null responses, as documented. All 61 tests pass in `daybreak`,
covering documented and unknown statuses, transport failures, refresh/JSON errors,
safe logging, cancellation, and programming-error propagation. No live access.

Standalone entry point: `python src/garmin_connect_client.py` loads repository
TOML plus dotted CLI overrides, prints Garmin settings with the inline key masked,
initializes the authenticated singleton, and prints heart rate zones and profile
settings as JSON. It prints token expiration but never the token. Cleanup closes
the client and logger; expected failures return exit status 1 without raw exception
text. Importing does not run the command. All 64 tests pass in `daybreak`, including
synthetic entry-point output masking, cleanup, and failure exit codes. No real
credentials or health data were read, and the real-network command was not run.

Standalone creation diagnostics (2026-10-31): the shared environment lacked
`socksio`. Client construction succeeded with the agent's HTTP proxy environment,
but a synthetic SOCKS proxy environment reproduced an ImportError before any
Garmin request. Requirements now select `httpx[socks]==0.28.1`; synchronizing the
existing `daybreak` environment installed socksio 1.0.0. SOCKS-configured client
construction/cleanup now succeeds without network requests. Creation logs expose
only the exception type and a safe dependency hint, preserving the original
exception. A full `main([])` test uses the real wrapper and HTTPX MockTransport for
token acquisition and two GETs, checks redaction, and closes resources. All 66 tests
pass. The user's exact shell failure remains unconfirmed; no real API key or
health data was accessed, and no live Garmin call was made.

Proxy-mode verification (2026-10-31): a temporary local TLS origin and local
HTTP CONNECT/SOCKS servers exercised the real Garmin factory, token POST, and two
HTTPS data GETs. Direct mode with proxy variables removed, HTTP proxy, SOCKS5,
SOCKS5h, and NO_PROXY bypass all passed with certificate verification enabled.
Proxy hit counts confirmed actual routing. A deliberately unavailable proxy failed
cleanly without publishing a singleton. Tests used generated local certificates,
synthetic keys/tokens/data, and only 127.0.0.1; sandbox loopback binding required
an approved rerun. No Garmin or other external API requests were sent. This
verifies client proxy behavior, not reachability of a user's proxy or Garmin.
Stopping a proxy while retaining its environment variables does not switch to
direct mode; clear settings and recreate the client. No automatic direct fallback.

Swagger provenance: README links to the official Personal API Swagger page.
`GarminConnectClient.SWAGGER_VERSION="1.0.0"` and `SWAGGER_URL` record the current
reference in code, with the same version and address in the endpoint document.
This version is the specification's `info.version`, distinct from OpenAPI 3.0.1.

PR scope agreement (2026-10-31): the user accepts process-local token storage for
the long-running MCP server; disk persistence is not required. Existing generic
HTTP DEBUG response previews are also accepted for this personal application;
preview suppression is not required for this increment. These are deliberate
scope decisions, not outstanding PR blockers. Automated and local proxy checks pass. The user subsequently confirmed successful
live Garmin validation; README and roadmap reflect that confirmation while keeping
MCP integration pending.

User-confirmed live validation (2026-10-31): the user reports that real Garmin
validation has completed successfully. This is user-provided verification, separate
from the agent's synthetic tests and local proxy checks. The exact endpoint set
and error cases were not provided, so this record does not claim live coverage of
all 26 endpoints. No credentials, health data, or real responses are included.
PR validation summary: aligned with Garmin API specification 1.0.0, 66 automated
tests passing, local proxy modes verified, and live Garmin validation confirmed
by the user. MCP integration remains outside this branch's scope.

Configuration increment: the singleton now captures the `GarminConnectClient`
section during factory initialization. `api_key_string` (default empty, excluded from
representations) takes precedence over `api_key_file` (default `config/API_KEY.txt`). Key files
are read during factory initialization as UTF-8 relative to the repository root; whitespace is stripped,
and missing, unreadable, empty, or out-of-repository sources are rejected without
exposing contents. `http_client_pool_size=10` replaces `pool_size` and must be
positive and controls the owned transport connection limit. No expiration
configuration was added; distinct authentication error codes remain unverified. The official FAQ
states a maximum 24-hour token lifetime bounded by key expiry, with no refresh
tokens. All 41 tests pass in the existing `daybreak` environment using synthetic
credentials and mocked file reads; no real credentials or health data were read.

HTTP configuration translation: `generate_http_client_config(config)` is a class
method returning `AsyncHttpClientConfig` without singleton access or side effects.
Garmin settings declare `base_url`, `timeout`,
`max_keepalive_connections`, and `keepalive_expiry` in both the schema and default
TOML. The code-level `http_client_name="GarminConnect"` default maps to HTTP
`name` and is omitted from the default TOML. `http_client_pool_size` maps directly
to `max_connections`. Initialization
uses this translator and no longer reads `GeneralHttpClient` or hardcodes/clamps
transport settings. Runtime authentication remains outside static configuration.

Method layout: Garmin client attributes precede public class methods, public
instance methods, special methods, and internal methods. Repository instructions
now define this order and require explicit class-name calls for class/static
methods, with `cls` reserved for intentional subclass dispatch inside class methods.
This reordering changes no runtime behavior; all 51 tests pass in `daybreak`.

Credential error logging: every explicit exception in `_load_api_key` is preceded
by the shared `Logger.ERROR` with a safe message matching the exception. Tests
verify one error log per failure without file contents or underlying error text.
The repository instructions now require shared ERROR logging before explicit
raises. All 41 tests pass in the existing `daybreak` environment.

- [ ] Investigate current API access options and authentication using available first-party documentation and relevant dependency sources.
- [ ] Document the selected access method, limitations, and any undocumented behavior.
- [ ] Implement the minimum Garmin-specific authentication and request flow on top of the generic client.
- [x] With the user's authorization and local credentials, validate access to representative account data (confirmed by the user on 2026-10-31).
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
- Finalize the proposed JSON envelope, configurable refresh periods, calendar
  timezone, and per-endpoint daily partition semantics in the local-data draft.
- Final tool contracts, result-size limits, and service auto-start; FastMCP and
  the shared local HTTP transport/lifecycle are selected.
- Skills packaging and discovery, Codex invocation, output contract, and authorized data scope.
- Scheduling mechanism, execution time, retry policy, and unattended environment.
- Report language, format, sections, and output behavior.

Markdown is a candidate report format. `Asia/Shanghai` is a candidate timezone. Neither is a confirmed product requirement.

## User-selected increment: local persistence design

On 2026-10-31 the user approved file persistence and local-first MCP reads.
[Local data and MCP contract draft](../local-data-contracts.md) records the design.

- [x] Record storage layout, parameter identity, atomic writes, stale fallback,
  range handling, initial Skill workflow, and provisional MCP tool contracts.
- [x] Ignore the complete `garmin_data/` tree before any personal data is written.
- [ ] Confirm dataset mappings and daily partition completeness using synthetic
  or explicitly approved sanitized response structures.
- [ ] Finalize timezone, freshness defaults, limits, and non-dated/binary contracts.
- [ ] Distinguish client failures from successful empty responses before caching
  no-data outcomes; preserve or explicitly migrate the existing client contract.
- [x] Implement and verify the initial JSON file store and local-first data service
  with synthetic fixtures in the existing `daybreak` environment.
- [ ] Integrate MCP tools and verify the initial Skill through the planned workflow.

Design verification: check Markdown diffs and the ignore rule using synthetic
paths only. No store contents, credentials, or health data were accessed. No
runtime implementation or milestone completion is claimed. Suggested next step:
finalize daily endpoint adapters and implement the persistence layer against
synthetic responses before MCP integration.

### First MCP implementation (2026-10-31)

The later user request selected `src/mcp_server.py` implementation. It now
registers six FastMCP stdio tools over `src/garmin_data_store.py`. Daily summary,
sleep, HRV, heart rate, SpO2, and fitness age use independently reusable dated
records. Weight, steps, stress, hydration, Body Battery, and activity search
preserve exact request ranges/pages until response partitions are verified.
Activity details/workouts and profile/settings tools are also available.
See [MCP server usage](../mcp-server.md) for the actual contract and commands.

The entry point reads timezone and refresh settings from `GlobalConfig.MCPServer`;
UTC is the default timezone and deployments can override it. All filenames include the endpoint plus parameter hash,
including default calls. Local hits do not authenticate. Refresh failures retain
old data, ambiguous `None` is never cached, empty collections refresh conservatively,
and persistence failures return explicit warnings. One writer process owns the
store. No database, scheduler, Codex invocation, or client registration was added.

Verification: all 76 tests pass in the existing `daybreak` environment, including
10 new synthetic tests with in-process MCP calls and real stdio subprocess tool
discovery from another working directory. Coverage includes persisted reuse after
service restart, missing-date retrieval, concurrent misses, expiration, stale
fallback, initial auth transport failure, parameter isolation, corrupt records,
atomic replacement failure, symlink rejection, cancellation, limits, and partial
results. No real credentials or health data were read; no live Garmin call was
made. Pre-existing design edits and unrelated user editor settings were preserved.

Remaining work: verify endpoint response shapes before range partitioning; add
projections for oversized single records, additional endpoint filters/datasets,
and typed success/no-data outcomes if required. Live MCP validation and Skill/
Codex discovery remain separate acceptance checks. Suggested next step: connect
the local MCP server to Codex and verify discovery before authorizing live tools.

### MCP configuration consolidation

The user requires application configuration to be centralized in GlobalConfig.
`MCPServerConfig` now owns `data_source`, `data_directory`, `timezone_name`,
`recent_days`, `recent_ttl_seconds`, and `profile_ttl_seconds`. The default TOML
mirrors these fields, and existing dotted CLI parsing replaces the standalone
MCP argument parser. StorePolicy was removed; the store consumes the same frozen
configuration snapshot. Server initialization selects the Garmin client factory
only for `garmin_connect`; all other source values log ERROR and raise
`NotImplementedError`. Authentication remains lazy for local-only operation.
Tests verify layered configuration, invalid updates, source selection, unsupported
sources, and updated stdio startup. No credentials or personal data are accessed.
Verification: all 78 tests pass in the existing `daybreak` environment; the
updated dotted CLI also passes subprocess stdio discovery. Diff whitespace checks
pass. Live Garmin/MCP validation remains outside this increment.

Startup configuration output: after TOML and CLI loading, the server logs the
complete effective snapshot at INFO before initialization. `to_display_dict()`
preserves outer-to-inner schema order and masks dataclass fields with `repr=False`,
including the inline Garmin key. Logging honors configured handlers and levels;
stdout remains reserved for MCP. Synthetic tests verify masking without mutation
and stderr configuration output alongside successful stdio discovery. All 79
tests pass in `daybreak`; no real credentials or health data were accessed.

### Shared local HTTP service

The user selected a persistent local service serving multiple Codex processes.
`MCPServer` now declares `transport="http"`, `host="127.0.0.1"`, `port=8000`,
and `path="/mcp"` before data settings. Startup uses Streamable HTTP with explicit
stateful sessions and Host/Origin protection; stdio remains an explicit option.
Only loopback binding is supported in this increment. Unsupported transports,
invalid ports/paths, and non-loopback hosts are rejected during configuration.
One server process shares its store, per-key locks, and lazy Garmin client across
client sessions; disconnecting a session does not close the shared client.

Verification: all 81 tests pass in `daybreak`. Loopback binding was blocked in
the sandbox; the approved rerun passed. A real temporary HTTP listener served
MCP calls from two independent client processes, retained service after disconnect,
reused one successful remote fetch, accepted reconnects, and closed the mock Garmin
client exactly once on shutdown. Startup dispatch, config validation, and explicit
stdio discovery also pass. Tests use synthetic data; no real Garmin requests,
credentials, or personal data are accessed. Service auto-start and actual Codex
client registration remain pending; no long-running service was left behind.

### Complete Garmin MCP endpoint coverage

The user explicitly selected all 26 existing client APIs and all their parameters
for MCP exposure. `src/garmin_mcp_tools.py` now registers an explicit endpoint
allowlist, deriving required fields, defaults and parameter types from client
signatures. The six existing convenience tools remain, giving 32 tools total.
Direct tools preserve optional date semantics and use a calendar-day cache context
for implicit dates. They validate dates, IDs, search controls and documented range
caps without fixing optional filters or boolean values. Lifecycle/auth methods
remain private. No new Garmin remote endpoints are invented.

`download_activity` stores immutable content-addressed ZIPs with atomic JSON
metadata publication and exposes a validated local-only MCP binary resource.
Checksums detect missing/corrupt binaries; failed refresh retains previous data.
Files are not extracted. Failed metadata publication may leave an unreferenced
ZIP; garbage collection and streaming large files remain follow-up work.
See [MCP server usage](../mcp-server.md) for all 26 names and binary semantics.

The user's TOML listener port 15666 is preserved; the schema default and current
usage examples now match it. Other existing user edits are retained.

Verification: all 86 tests pass in the shared `daybreak` environment. Five added
tests check inventory/schema coverage, every parameter forwarded through MCP,
local reuse, optional dates, parameter variants, invalid arguments, ZIP resource
reading, checksums, repair, refresh fallback, and persistence failure. Existing
HTTP multi-process and stdio discovery tests now discover 32 tools. The sandbox
blocked loopback binding; the approved network-enabled rerun passed. Diff checks
pass. No live Garmin requests, credentials, or personal health data were accessed
for this increment. Restart the running server and refresh client discovery to
load the new tools. Full live endpoint coverage remains unverified.

### PR handoff verification

Live MCP verification after server restart discovered 32 tools and the binary
resource template through an MCP SDK client. Selected single-day and multi-day
wellness, sleep, HRV, weight, Body Battery, activity search and activity detail
queries succeeded, and local-only reads reused persisted records. This confirms
representative end-to-end access, not live coverage of all 26 endpoints or native
Codex/Skill discovery. No credentials, responses, metrics, or personal analysis
are stored in tracked files.

PR review identified ZIP content hashing overwriting the request identity variable,
which prevented concurrent forced downloads from sharing a successful refresh.
Separate request and archive hashes now preserve the correct generation counter;
a synthetic concurrent-refresh regression covers the fix. All 87 tests pass in
the shared environment, including loopback HTTP and subprocess discovery.

Follow-up boundaries remain exact-range caching, source/configured timezone
semantics, oversized JSON projections, ambiguous client empty/error outcomes,
and whole-file binary buffering. These do not claim to be completed milestones.
Keep the ignored local store and any personal output outside the PR; existing
unrelated editor changes remain untouched.

### HTTP request DEBUG context

The user requests complete URI/path/query diagnostics. HTTP requests are now
built once before sending, so lazy DEBUG formatting uses the actual resolved URL
and serialized repeated parameters. Start and response entries share a generated
request ID. Ordinary query values are not truncated; URL user information,
credential-like query fields, and known header/query credentials are redacted.
Headers and request bodies remain unprinted; response previews retain the existing
2048-byte/character limit. ERROR logs remain unchanged. MockTransport tests verify
wire values, relative URLs, repeated parameters, query/header credential redaction,
response echoes, and failed-request logging without live access. The default TOML
schema check now permits the explicitly requested diagnostic DEBUG override while
retaining INFO code defaults. All 92 tests pass in `daybreak` using synthetic data.

## Progress and handoff

Storage directory typo corrected: the schema default, TOML, Git ignore rule, and
usage/planning documentation consistently use `garmin_data/`. Neither the old nor
new default directory existed locally at this change, so no cache migration was
needed and no personal data was read. Configuration checks pass in `daybreak`.

User-selected diagnostic configuration: TOML shared and console logging levels
are temporarily DEBUG for the next live MCP analysis after the user restarts the
service. Code defaults remain INFO; dependency loggers remain disabled. File
logging remains disabled. This is a deliberate diagnostic override of schema
defaults, not a change to logging behavior. Configuration loading was checked
without credentials, health-data access, or remote requests.

MCP request INFO logging: middleware now records tool calls/discovery and resource
reads/discovery through the shared Logger. Received and finished entries share
a generated call ID and report method, allowlisted tool name, status, and elapsed
milliseconds. Parameters, resource URIs, payloads, and raw exceptions are excluded;
unknown tool names are redacted. Result-level partial/error and cancellation
statuses are preserved without changing results or exceptions. Two added tests
verify real MCP logging, privacy markers, paired IDs, partial results, and
cancellation. All 90 tests pass with synthetic data; no live Garmin access.

Server dependency logging: at the user's request, `mcp_server.main()` now disables
FastMCP and Uvicorn logger namespaces and existing children before starting the
service. Null handlers and disabled propagation silence later propagating children.
Uvicorn receives `log_config=None` and `access_log=False`, preventing default
handler reconfiguration and stdout access logs. Dependency warnings/errors are
also intentionally suppressed. Shared Daybreak logging is unchanged. Tests cover
Uvicorn initialization, late child loggers, application logging, startup dispatch,
and stdio discovery without the FastMCP startup message. All 88 tests pass using
synthetic data; no live Garmin access was performed.

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
