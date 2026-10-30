# Daybreak

Daybreak uses Garmin Connect data and the AI capabilities of ChatGPT/Codex to generate a daily report. Daybreak is primarily a local MCP server. Predefined Skills guide a local Codex process to retrieve data through that server and produce the report. Manual or scheduled tasks trigger the workflow.

Status: planning only. No application functionality has been implemented.

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

Python and `httpx` are the foundation of the HTTP layer. Packaging, supported Python version, and runnable commands will be documented when implemented. The exact Codex invocation will be verified during integration.

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
configuration does not create handlers, directories, or log files. Handler
initialization and application integration remain follow-up work.

Communicate with the user in Chinese. All tracked file content, code comments, and Git commit messages must be in English.

Do not commit credentials, session tokens, personal health data, or generated personal reports.
