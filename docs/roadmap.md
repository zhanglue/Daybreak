# Daybreak Roadmap

## Goal

Generate a daily report based on Garmin Connect data, using ChatGPT/Codex for AI analysis. Daybreak provides a local MCP server. Predefined Skills guide Codex to call its tools; a manual or scheduled task starts the local Codex process.

## Milestones

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 0 | Repository instructions and initial implementation plan | Documents prepared; initial commit pending |
| 1 | Initial Skills workflow and draft MCP tool contracts | Not started |
| 2 | General-purpose asynchronous HTTP client based on `httpx` | Managed client wrappers and response/error contracts implemented; 21 tests pass |
| 3 | Validated Garmin Connect API access | Not started |
| 4 | Data inventory and finalized MCP response contracts | Not started |
| 5 | Local MCP server, Skills, and Codex integration | Not started |
| 6 | Daily reports with manual and scheduled execution | Not started |

See the [implementation plan](plans/garmin-daily-report.md) for tasks and acceptance criteria.

## Initial scope

- Support a single user, validating manual execution before scheduled execution.
- Separate generic HTTP transport, Garmin integration, MCP tools, Skills, task invocation, and report output.
- Keep Garmin credentials within the server integration; Codex retrieves data only through MCP tools.
- Establish the available data before fixing report metrics and analysis requirements.
- Treat Codex analysis as a core capability, rather than optional prose polishing.
- Keep credentials, source health data, and generated personal reports outside Git.

Dashboards, message delivery, multi-user support, and direct model API integration are outside the initial plan. Persistence beyond local files will be considered only if required.

## Planning policy

This roadmap tracks milestones. The implementation plan owns detailed tasks and decisions. Update both when agreed scope or milestone completion changes; avoid duplicating detailed checklists.
