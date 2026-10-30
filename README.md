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

Communicate with the user in Chinese. All tracked file content, code comments, and Git commit messages must be in English.

Do not commit credentials, session tokens, personal health data, or generated personal reports.
