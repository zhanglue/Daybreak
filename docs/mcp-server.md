# Daybreak MCP Server

Daybreak uses FastMCP 4.1.4 and defaults to a persistent local Streamable HTTP
service. Start one server process, then connect multiple Codex/MCP client processes
to the same URL. Clients may connect, disconnect, and reconnect independently;
the shared store and lazy Garmin client remain alive until server shutdown.
The server never launches Codex. One process owns one single-account data store.

## Start

From the repository root, activate the existing environment and choose the
calendar timezone through GlobalConfig:

```bash
conda activate daybreak
python src/mcp_server.py --MCPServer.timezone-name Asia/Shanghai
```

The process listens at `http://127.0.0.1:15666/mcp` and runs until stopped with
Ctrl+C or a termination signal. Configure clients to connect to that HTTP URL;
they should not start a separate server per session. The server can start from
other working directories using the absolute script path. Automatic background
startup, Codex registration, and Skill discovery remain separate integration tasks.
This increment does not modify client configuration.

To choose a different port or endpoint:

```bash
python src/mcp_server.py --MCPServer.port 8123 --MCPServer.path /daybreak
```

The service permits only loopback addresses or `localhost`, enables FastMCP
Host/Origin protection, and provides no network authentication. Remote/LAN access
is outside this local-service increment. Run only one server/writer process per
store; multiple client processes share that server. Port conflicts fail startup
rather than silently selecting another port. Shutdown closes the acquired Garmin
client after server request handling stops.

For clients requiring stdio, explicitly select `--MCPServer.transport stdio`.
In this mode the client owns its server subprocess and stdout remains reserved
for MCP messages; it is not the shared-service mode.

The entry point loads repository-relative `config/default_config.toml`, followed
by existing dotted CLI overrides. Before initializing the server, it logs all
effective configuration sections at INFO in outer-to-inner schema order:
MCPServer, GarminConnectClient, GeneralHttpClient, and Logging. Fields hidden from
configuration representations, including the inline API key, appear as `********`.
The snapshot does not read credential files or alter configuration. Output follows
the configured logging handlers/levels; console output goes to stderr, preserving
stdout for MCP. It acquires Garmin credentials lazily only
when a tool needs a remote fetch. Import, discovery, fresh local hits, and
`local_only` calls do not initialize Garmin authentication. Shutdown closes an
acquired Garmin client. Existing client authentication and configuration rules
still apply.

The entry point suppresses the `fastmcp` and `uvicorn` logger namespaces,
including their existing child loggers, before server initialization. Uvicorn
receives `log_config=None` and `access_log=False` so startup does not reinstall
handlers or emit HTTP access logs. This also suppresses those dependencies'
warnings and errors by design. Daybreak's shared Logger remains independent and
continues to honor `GlobalConfig.Logging`. Library imports and embedded
`create_server()` calls do not apply this process-level logging policy.

Daybreak's MCP middleware logs `tools/call`, `tools/list`, `resources/read`,
`resources/list`, and `resources/templates/list` at INFO. Each request emits a
received and finished entry with a generated `call_id`, protocol method, known
tool name where applicable, final status (`ok`, `partial`, `error`, or `cancelled`),
and elapsed milliseconds. Tool-result error/partial statuses are retained even
when protocol execution succeeds. Unknown tool names are logged as `unknown`.
Arguments, dates, activity IDs, resource URIs, result payloads, and raw exception
text are excluded. These logs use the shared Logger and its configured handlers
and levels; dependency logging remains disabled by the entry point.

All application settings live under `GlobalConfig.MCPServer`, mirrored by the
`[MCPServer]` table in `config/default_config.toml`:

```toml
[MCPServer]
transport = "http"
host = "127.0.0.1"
port = 15666
path = "/mcp"
data_source = "garmin_connect"
data_directory = "garmin_data"
timezone_name = "UTC"
recent_days = 7
recent_ttl_seconds = 3600
profile_ttl_seconds = 86400
```

`transport` accepts `http` (Streamable HTTP) or `stdio`. `port` must be 1..65535;
`path` must be an absolute endpoint path without query, fragment, traversal, or
empty segments. Hostnames other than `localhost` and non-loopback IPs are rejected.
`host`, `port`, and `path` apply to HTTP mode.

`data_directory` is resolved relative to the repository root; an absolute path
can select a separate single-account store. Keep any custom directory outside
Git. UTC is the default calendar timezone; select the account's timezone for
local-date analysis. All fields support standard dotted CLI overrides, such as
`--MCPServer.recent-ttl-seconds 1800`. The old standalone flags are not supported.
Configuration retains defaults < TOML < CLI precedence and atomic validation.

Server initialization selects the client factory from `data_source`.
`garmin_connect` selects `GarminConnectClient.get_client`; every other value
logs a safe ERROR and raises `NotImplementedError` before serving tools, even
for local-only use. Factory selection does not authenticate: client acquisition
remains lazy until a remote read is needed.

Today and the preceding seven days refresh
after one hour. Older nonempty dated responses remain reusable until forced
refresh. Empty arrays/objects refresh after one hour even for old dates; they
are successful payloads, not verified `no_data` claims. Activity details use a
one-hour TTL because their date mapping is not yet established.

## Endpoint tools

All 26 existing Garmin client endpoints are exposed as individual MCP tools,
using the exact client method names. Every client argument, required/optional
status, type and default appears in the tool schema, followed by `cache_mode`.
Schemas derive from the existing client signatures through an explicit allowlist;
authentication, transport and lifecycle methods are never exposed. Agents choose
which endpoints to use. Existing convenience tools below remain compatible.

| Endpoint tool | Purpose |
| --- | --- |
| `get_activity` | Read one activity, including the summary and available performance metrics. |
| `get_activity_workouts` | Read the structured workout followed during an activity. |
| `search_activities` | Search one page of activities using every supported filter. Paginate with start and limit (1..99). |
| `get_heart_rate_zones` | Read sport-specific heart-rate zones; choose whether Garmin generates defaults. |
| `download_activity` | Download the original activity ZIP to the local store. Returns metadata and a binary MCP resource URI, not inline bytes. |
| `get_fitness_age` | Read fitness age for a date, optionally scanning full history. |
| `get_effective_weight_goals` | Read weight goals effective over a date range. |
| `get_daily_hrv` | Read overnight HRV readings, seven-day average, personal baseline and status. |
| `get_daily_hrv_summaries` | Read daily HRV summaries over a date range. |
| `get_daily_food_logs` | Read nutrition logs with optional goals, nutrition, media and meal selection. |
| `get_menstrual_cycle_summary` | Read menstrual-cycle summary and predictions for a date. |
| `get_menstrual_cycle_day_view` | Read menstrual-cycle day details with all analysis and response options. |
| `get_daily_sleep` | Read one night of sleep, stages, scores and available overnight vitals. |
| `get_daily_sleep_summaries` | Read sleep summaries over up to 31 inclusive dates. |
| `get_user_profile_settings` | Read user profile settings, units and timezone preferences. |
| `get_daily_hydration` | Read daily hydration over up to 31 inclusive dates. |
| `get_daily_steps` | Read daily steps over up to 28 inclusive dates. |
| `get_daily_stress` | Read daily stress over up to 28 inclusive dates. |
| `get_daily_user_summary` | Read one calendar day of wellness totals and recovery indicators. |
| `get_daily_summaries` | Read daily wellness summaries over up to 365 inclusive dates. |
| `get_all_weight_measurements` | Read all weight measurements over a date range. |
| `get_weight_measurements` | Read weight summaries over a range; include_all controls individual measurements. |
| `get_daily_body_battery` | Read Body Battery over up to 31 inclusive dates with optional intraday chunks. |
| `get_daily_spo2` | Read daily pulse-ox readings and available hourly summaries. |
| `get_daily_heart_rate` | Read daily heart-rate readings and resting/minimum/maximum summaries. |
| `get_wellness_activity_summaries` | Read wellness activity summaries over a date range. |

Each direct endpoint caches the exact effective parameter set, including all
filter, pagination, nutrition, menstrual, chunks and boolean options. Dates and
activity IDs are normalized before caching; variants cannot overwrite each other.
Dates can be supplied as ISO strings. Optional dates remain `None` when omitted,
so Garmin retains its own default-query behavior. Such requests include the
current configured calendar date in cache identity and use short freshness,
rather than being mistaken for a complete, immutable historical range. An omitted
Garmin date is not evidence that the payload belongs to today.

Direct endpoint tools validate date syntax and range ordering. Documented range
caps are 28 dates for steps/stress, 31 for hydration/sleep summaries/Body Battery,
and a conservative 365 dates for daily summaries. Other endpoint ranges are not
artificially limited to the convenience tools' 31 dates. Large results still use
the response-size limit below. Unlike convenience date queries, direct tools do
not reject future dates globally: Garmin endpoint semantics determine whether
future goals or predictions are supported. Search exposes all 32 filters with
client defaults, including `limit=99` and `activity_type=null`; all filters are
passed through. A page is never treated as the entire activity history.

## Activity downloads

`download_activity(activity_id, cache_mode)` persists an original ZIP without
extracting it. The normal JSON result contains `media_type`, `size_bytes`, `sha256`,
and `resource_uri`, for example
`daybreak://activities/123/<sha256>`. Use MCP `resources/read` to retrieve that
URI as `application/zip` blob content. Resource reads are local-only and validate
the activity ID, hash, path containment, and checksum. No absolute server file
paths are exposed. Reading a binary resource does not parse FIT data or create
new Garmin capabilities.

Content-addressed ZIP files live under `activities/<id>/` beside the endpoint's
JSON metadata. Binary publication happens before atomic metadata replacement;
old metadata and its referenced ZIP remain usable if refresh or metadata writing
fails. Unreferenced content-addressed files may remain after a failed publication;
automatic garbage collection is not implemented. Missing or corrupt binaries
invalidate a cached download and may be repaired by a normal remote retrieval.
Invalid ZIP responses are not cached. Failed persistence returns
`persisted=false`, a warning, and no resource URI. Binary resource reads return
the complete file rather than the ordinary 256 KiB JSON tool-result envelope;
clients should request them explicitly when needed. The client currently buffers
the original download in memory, and resources return it whole.

## Convenience tools

| Tool | Main arguments | Behavior |
| --- | --- | --- |
| `get_garmin_data` | `dataset`, `start_date`, optional `end_date`, `cache_mode` | Retrieve at most 31 inclusive calendar dates |
| `get_garmin_day` | `calendar_date`, explicit distinct `datasets`, `cache_mode` | Independently collect selected datasets for one date |
| `search_garmin_activities` | `start_date`, `end_date`, `activity_type="cycling"`, `start=0`, `limit=20`, `cache_mode` | Fetch/cache one page; limit 1..99 |
| `get_garmin_activity` | positive `activity_id`, `workouts=false`, `cache_mode` | Fetch details, or the activity's structured workout |
| `get_garmin_profile` | `dataset="settings"` or `"heart_rate_zones"`, `cache_mode` | Retrieve settings or zone definitions |
| `list_local_garmin_data` | `start_date`, `end_date`, distinct `datasets`, `cursor=0`, `limit=100` | Inspect known request identities without remote access; omit payloads |

Supported daily datasets are `summary`, `sleep`, `hrv`, `heart_rate`, `spo2`,
and `fitness_age`. Each maps to its corresponding single-date Garmin method.
Each date is independently cached; overlapping queries fetch only missing or
expired dates. `fitness_age` currently fixes `full_history_scan=true`.

Range datasets are `weight`, `steps`, `stress`, `hydration`, and `body_battery`.
These preserve the exact requested range response without inferring daily record
boundaries. Weight uses `include_all=false`. Steps and stress allow at most 28
inclusive dates. Other range tools and activity search allow 31. Request longer
history in bounded calls. Exact-range caching can repeat remote data for overlapping
ranges; daily partition adapters remain follow-up work.

Convenience activity searches preserve page offset, limit, type, dates, and fixed filters
in cache identity; the direct `search_activities` tool opens all client filters. A page is not an exhaustive inventory. Paginate explicitly;
no claim is made about unseen pages. Activity samples/splits beyond fields already
returned by the 26 existing client methods are not additional supported endpoints.

`cache_mode` is `prefer_local`, `local_only`, or `refresh`. Stale records are
returned explicitly on remote failure. Without a valid old record, failure is
`remote_unavailable`; ambiguous client `None` is never stored. Convenience queries reject future
or reversed dates before remote access; direct endpoints follow the rules above.

## Persistence and results

The default ignored repository-root `garmin_data/` is created only on a successful write.
All filenames currently use `<endpoint>--<sha256>.json`, including default calls,
so effective parameters, endpoint, schema version, and timezone always contribute
to identity. This simplifies the original draft's default/variant filename split.
Daily records live under `YYYY-MM-DD/`; activity records under `activities/<id>/`;
settings under `profile/`; exact ranges and search pages under `ranges/`.
Do not reuse the store for a different Garmin account.

Payloads are preserved inside versioned envelopes with parameters, timezone,
and UTC `fetched_at`. Writes use owner-only files, directory permissions, and
atomic replacement. Unsafe symlinks and traversal are rejected. Corrupt or
incompatible records are unavailable. Failed writes preserve old data and return
new remote values with `persisted=false`. Same-key concurrent successful fetches
are reused within one process. Multi-process writers are unsupported.

Data tools return `schema_version`, aggregate `status` (`ok`, `partial`, `error`),
and `records`. Records expose endpoint/parameters, `status`, `source`, `fetched_at`,
`stale`, `persisted`, and payload or a safe error/warning. Missing records have
null source and retrieval time. A stale record or persistence warning makes the
aggregate partial. Units remain exactly as Garmin returns them; unknown units
must not be invented. The listing returns metadata and `next_cursor` only.

Data responses exceeding 256 KiB return `result_too_large` without silently
truncating data; the full successful payload remains persisted. Narrow the date
range or activity page. A single oversized endpoint response currently cannot
be retrieved via samples/projection; this is a follow-up requirement.

## Verification

```bash
conda activate daybreak
PYTHONPATH=src python -m unittest discover -s tests -v
```

Synthetic tests compare all 26 schemas against the reviewed endpoint inventory,
exercise every client argument over MCP, verify variant cache separation, and
read/check/repair binary download resources. They also cover HTTP requests from independent client processes, disconnect/
reconnect behavior, shared fetch reuse, service shutdown, configured listener
selection, MCP discovery and calls, stdio subprocess startup from a
separate directory, local-only behavior, daily gap retrieval, concurrent misses,
freshness boundaries, empty response refresh, stale fallback, exact-range and
parameter identity, corrupt files, failed atomic replacement, symlink rejection,
cancellation, endpoint limits, partial results, and response size limits. No real
credentials or health data are used. Loopback tests require permission to bind
a temporary local port. Complete live coverage of the 26 tools and native Codex/Skill integration
remain unverified. Automated checks use synthetic data only. Separately, live
HTTP discovery confirmed all 32 tools and the ZIP resource template. Selected
single-day/multi-day health and activity queries, activity details, and local-only
cache reuse have worked through an MCP SDK client. This is not live verification
of every endpoint, binary download, or native Codex tool loading. No private
responses or personal analysis are included in tracked documentation.

## Current boundaries

- One account and one writer server process own a store; many MCP client processes
  may share that service. It is not a multi-user server.
- Range responses cache exact requests. Overlapping ranges may fetch overlapping
  data; general daily partition reuse remains pending response adapters.
- `calendar_timezone` records the configured cache/refresh timezone. It does not
  convert Garmin payloads or establish the source's day boundaries. Actual live
  source timestamps can reflect a different account timezone. Configure the
  account's calendar timezone and retain source timestamps in analysis.
- Existing client `None` outcomes cannot distinguish failed requests from empty
  responses; the store conservatively treats them as unavailable.
- The ordinary JSON result limit is 256 KiB. A single oversized record currently
  needs a future projection/resource contract; ZIP resources return full binary
  content and are buffered in memory.

PR verification also includes a regression for concurrent download refreshes:
request identities remain separate from content hashes, so concurrent successful
refreshes of the same activity reuse one fetch.

HTTP transport DEBUG entries additionally include the resolved upstream method,
URL, path, and query values (including repeated parameters), plus a request ID
shared with the response entry. Credential-like query fields, URL user information,
and known authorization values are redacted. Ordinary query values are not
truncated. Request bodies/headers are not printed; response preview limits remain
2048 bytes/characters. MCP INFO logs continue to omit argument and payload values.
