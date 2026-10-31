# Local Garmin Data and MCP Contract Draft

Status: design direction approved on 2026-10-31. A first subset is implemented;
[MCP server usage](mcp-server.md) specifies the actual available tools and behavior.
The sections below retain provisional requirements beyond that subset. Live
response discovery and Codex/Skill integration remain pending. Implementation
uses parameter hashes on every filename rather than a separate default filename.

## Responsibilities

Daybreak serves Garmin data from a local file store first. It calls the existing
Garmin client only for missing or expired records, or an explicit refresh.
Codex retrieves both current and historical data through MCP tools. It does not
read the store directly, access credentials, or call Garmin APIs. The server
does not launch Codex. Health-data persistence is separate from authentication;
tokens remain process-local under the existing client contract.

## Storage and identity

Use the repository-relative directory `garmin_data/`.
Create directories lazily when writing data. Ignore the entire directory in Git;
never place real data in fixtures or documentation. The store belongs to one
account. Switching accounts requires a separate store; never reuse an existing
store for a different account.

```text
garmin_data/
  2026-10-30/
    get_daily_user_summary.json
    get_daily_sleep.json
    get_daily_food_logs--<parameter-sha256>.json
  activities/
    12345/
      get_activity.json
  profile/
    get_user_profile_settings.json
  ranges/
    get_weight_measurements--<parameter-sha256>.json
```

Use explicit Garmin client method names as endpoint identifiers. Fixed-default
single-day calls use `<endpoint>.json`; variants append the full SHA-256 digest
of canonical request parameters. Identity includes endpoint, resolved dates,
all effective parameters (including defaults), and storage schema version.
Canonical JSON sorts object keys and uses stable JSON types. Preserve array order
unless endpoint semantics explicitly establish that order is irrelevant. Exclude
credentials and transport settings. Check embedded identity when reading, even
when the filename matches. Resolve omitted dates before constructing a key.

Use validated endpoint identifiers and typed dates/IDs, not caller-supplied paths.
Reject traversal and symlinks escaping the store. Local directories and files
should be owner-only. Never log record contents or credentials.

Store unchanged endpoint payloads inside a versioned envelope. This synthetic
example describes the envelope only; `{}` is not a verified Garmin response:

```json
{
  "schema_version": 1,
  "endpoint": "get_daily_user_summary",
  "parameters": {"calendar_date": "2026-10-30"},
  "calendar_timezone": "Asia/Shanghai",
  "fetched_at": "2026-10-31T00:10:00Z",
  "status": "ok",
  "data": {}
}
```

UTC timestamps describe retrieval; calendar dates retain Garmin's date semantics.
The timezone above is illustrative. The deployment timezone must be configured
explicitly before implementation uses it to resolve today or freshness windows.
Preserve source units and timestamps; do not infer missing units or convert nulls
to zero. Profile and range records use the same envelope with their own parameters.

## Read and refresh rules

The following are proposed configurable defaults, not observed Garmin guarantees:

| Record | Default freshness |
| --- | --- |
| Today and the preceding 7 calendar days | Refresh after 1 hour |
| Older successful dated records | Reuse until explicitly refreshed |
| Confirmed successful no-data response | Retry after 1 hour, regardless of date |
| Profile and non-dated settings | Refresh after 24 hours |
| Activity details | Use the activity's local date when known; otherwise 1 hour |
| Unsplittable range | Refresh if any covered date needs refresh |

Freshness uses the configured calendar timezone and an injectable clock. Future
dates are rejected. Old data can still change; `refresh` allows deliberate
corrections. There is no automatic historical backfill or scheduled sync in this
increment. Records are retained until manually removed; no automatic deletion.

1. Validate arguments and request limits before reading or fetching.
2. Read and validate the matching envelope. Corrupt, incompatible, or mismatched
   records are unavailable, never returned as measurements.
3. Return a fresh local record immediately, without initializing Garmin auth.
4. Fetch missing/expired records; publish only successful, serializable responses.
5. On refresh failure, preserve a previous valid record and return it as stale
   with an explicit warning. Without a usable record, return an error.
6. Write a temporary file in the destination directory and atomically replace
   the final file. Failed writes leave previous data intact and report persistence
   failure; a remotely obtained value may be returned with `persisted=false`.

Coalesce concurrent requests for the same identity inside one server process,
then recheck the file after acquiring the per-key lock. Cancellation propagates
and temporary files are cleaned up. Initial deployment supports one writer
process per store; multi-process writers need a later locking design.

An empty array is not automatically proof of absence. Each endpoint adapter must
define verified success/no-data semantics. The existing Garmin client returns
`None` for both handled failures and empty/null results. Until a typed outcome
distinguishes them, treat `None` as unavailable and never persist it as `no_data`.
Any client contract refinement must preserve or explicitly migrate existing users.

## Date ranges and incremental retrieval

For endpoints with a verified daily partition, read each requested date and fetch
only missing or expired partitions. Batch contiguous gaps within documented
Garmin limits, then persist daily records only when response mapping proves their
dates and completeness. A missing day in a range response is not proof of no data.
Keep distinct detail and summary endpoints distinct; one does not satisfy the other.

Until partition semantics are verified, preserve the exact range response under
`ranges/` with all parameters in its identity. Never assign a multi-day payload
to a single day or silently combine averages, pagination, or boundary-dependent
results. Overlapping exact-range requests can still fetch overlapping remote data;
general incremental reuse is an acceptance target for verified daily adapters,
not a promise for all 26 endpoints.

Activity searches include filters and pagination in identity. A page is not a
complete activity inventory. ZIP downloads use a separate binary file and metadata contract now documented
in [MCP server usage](mcp-server.md); they are exposed as a tool plus a local
binary resource.

## Draft MCP tools

These are provisional names pending the dataset inventory. Tools accept named,
allowlisted datasets, never arbitrary remote URLs or filesystem paths.

| Tool | Arguments | Purpose |
| --- | --- | --- |
| `get_garmin_data` | `dataset`, `start_date`, optional `end_date`, validated dataset-specific `parameters`, `cache_mode` | Retrieve a dated dataset; omitted end date means the start date |
| `get_garmin_day` | `date`, explicit `datasets`, `cache_mode` | Aggregate selected daily datasets with independent outcomes |
| `list_local_garmin_data` | `start_date`, `end_date`, optional `datasets`, `cursor`, `limit` | List local availability and freshness without remote access |

`cache_mode` is `prefer_local` (default), `local_only` (never authenticate or fetch),
or `refresh` (force a remote attempt). All modes preserve an old record on failure;
stale fallback is explicit. Non-dated profile/activity tool schemas remain pending.

Proposed limits: at most 31 inclusive dates per data request, 100 metadata entries
per listing page, and 256 KiB serialized per tool result. Validate before fan-out.
Never silently truncate. Return `result_too_large` with instructions to narrow the
request; larger historical retrieval uses multiple calls. Sample selection belongs
to the response layer and must not discard the full persisted source payload.

Each result has `schema_version`, requested dataset/date/parameters, and records
with `status` (`ok`, `no_data`, or `error`), `source` (`local` or `remote`),
`fetched_at`, `stale`, `persisted`, `data`, and safe warnings/errors. Unavailable
records have null source/retrieval metadata and no measurement payload. Aggregate
status is `ok`, `partial`, or `error`; one failed dataset must not erase others.
Include per-record endpoint/parameter provenance and source units when known.
Never expose absolute local paths, credentials, or raw transport exception text.

Error categories include `invalid_request`, `local_miss`, `invalid_local_record`,
`remote_unavailable`, `persistence_failed`, and `result_too_large`. Distinguish
authentication, timeout, and no-data outcomes only when the client supplies
reliable evidence. Use shared `Logger.ERROR` before explicitly raising; logs
exclude personal data.

## Initial Skill workflow

For a requested report date, request selected daily datasets through MCP, then
retrieve the agreed historical window in bounded calls. Prefer local records;
use `local_only` if the user requests offline analysis. Inspect each outcome,
freshness, and provenance before analysis. Mark missing/stale inputs explicitly,
cite endpoint/date evidence, and never infer zero from absence. Request samples
only when needed. Produce the report through Codex; never access the store or
credentials directly. Skill packaging/discovery and report metrics remain pending.

Synthetic scenario: `get_garmin_day` requests summary and sleep for 2026-10-30.
Summary is fresh locally; sleep is expired and remote retrieval fails. Return the
local summary and stale sleep with a remote warning, aggregate status `partial`.
The Skill identifies the stale sleep input and qualifies its conclusions. If no
sleep record exists, report it as unavailable rather than inventing sleep metrics.

## Implementation acceptance checks

- Verify local hits and `local_only` do not initialize authentication or network.
- Verify freshness boundaries, recent-day updates, explicit refresh, and no-data
  expiry with a controlled clock.
- Verify parameter identity, range gaps, partial results, and source provenance
  using synthetic endpoint payloads with verified partition contracts.
- Verify concurrent fetch coalescing, atomic replacement, cancellation, corrupt
  records, unsafe paths, and read/write failures preserve prior successful data.
- Verify ambiguous `None` never becomes a successful/no-data cached response.
- Verify result-size limits and logs do not disclose fixtures' sensitive markers.
- Integrate and test in the existing `daybreak` Conda environment. Real health-data
  inspection requires task-specific authorization and Daybreak MCP tools.
