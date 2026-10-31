# Daybreak Roadmap

## Goal

Generate a daily report based on Garmin Connect data, using ChatGPT/Codex for AI analysis. Daybreak provides a local MCP server. Predefined Skills guide Codex to call its tools; a manual or scheduled task starts the local Codex process.

## Milestones

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 0 | Repository instructions and initial implementation plan | Documents prepared; initial commit pending |
| 1 | Initial Skills workflow and draft MCP tool contracts | Local-first workflow and provisional tools drafted; packaging and discovery pending |
| 2 | General-purpose asynchronous HTTP client based on `httpx` | Managed client wrappers and response/error contracts implemented; 21 tests pass |
| 3 | Validated Garmin Connect API access | Standalone client and 26 GET endpoints implemented; 66 tests pass; live access confirmed by the user |
| 4 | Data inventory and finalized MCP response contracts | Initial file store implemented; range partition discovery and finalized schemas pending |
| 5 | Local MCP server, Skills, and Codex integration | All 26 API tools plus six convenience tools and ZIP resource served over local HTTP; complete parameter coverage tested synthetically; full live coverage and native Codex/Skill integration pending |
| 6 | Daily reports with manual and scheduled execution | Not started |

See the [implementation plan](plans/garmin-daily-report.md) for tasks and acceptance criteria.

## Initial scope

- Support a single user, validating manual execution before scheduled execution.
- Separate generic HTTP transport, Garmin integration, MCP tools, Skills, task invocation, and report output.
- Keep Garmin credentials within the server integration; Codex retrieves data only through MCP tools.
- Establish the available data before fixing report metrics and analysis requirements.
- Treat Codex analysis as a core capability, rather than optional prose polishing.
- Keep credentials, source health data, and generated personal reports outside Git.
- Persist Garmin responses under ignored `garmin_data/`; serve local records first
  and fetch missing or expired data through the server's Garmin integration.

Dashboards, message delivery, multi-user support, and direct model API integration are outside the initial plan. Persistence beyond local files will be considered only if required.

## Planning policy

This roadmap tracks milestones. The implementation plan owns detailed tasks and decisions. Update both when agreed scope or milestone completion changes; avoid duplicating detailed checklists.
